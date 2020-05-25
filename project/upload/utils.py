from __future__ import division, unicode_literals
import codecs
from collections import OrderedDict
from backports import csv
import functools
import re
import six
from six import next, viewitems
from six.moves import range
try:
    # Python 3.4+
    from pathlib import PureWindowsPath
except ImportError:
    # Python 2.x with pathlib2 package
    from pathlib2 import PureWindowsPath

from django.urls import reverse

from accounts.utils import get_robot_user
from annotations.models import Annotation
from images.forms import MetadataForm
from images.models import Metadata, Image
from images.utils import generate_points, aux_label_name_collisions, \
    metadata_field_names_to_labels
from vision_backend.models import Features
from lib.exceptions import FileProcessError


def metadata_csv_to_dict(csv_stream, source):
    """
    Go from metadata CSV file stream to a dict of metadata dicts.
    The first CSV row is assumed to have metadata field labels like
    "Date", "Aux3", and "White balance card".

    DictReader is not used here because (1) it can't return an OrderedDict,
    and (2) the fact that column names need to be transformed to get the
    dict keys makes usage a bit clunky.
    """
    reader = csv.reader(csv_stream, dialect='excel')

    # Read the first row, which should have column names.
    column_names = next(reader)
    # There could be a UTF-8 BOM character at the start of the file.
    # Strip it in that case.
    column_names[0] = column_names[0].lstrip(codecs.BOM_UTF8.decode('utf-8'))
    column_names = [n.lower().strip() for n in column_names]

    # The column names are field labels (e.g. Date) while we want
    # dicts of the metadata model fields' names (e.g. photo_date).
    #
    # lower() is used to tolerate the CSV column names being in a different
    # case from the model fields' names.
    #
    # If a column name doesn't match any metadata field, we'll use
    # a field name of None to indicate that we're ignoring that column.
    field_names_to_labels = metadata_field_names_to_labels(source)
    field_labels_to_names = dict(
        (v.lower(), k)
        for k, v in field_names_to_labels.items()
    )
    fields_of_columns = [
        field_labels_to_names.get(label, None)
        for label in column_names
    ]

    dupe_labels = aux_label_name_collisions(source)
    if dupe_labels:
        raise FileProcessError(
            "More than one metadata field uses the label '{}'."
            " Your auxiliary fields' names must be unique"
            " and different from the default metadata fields.".format(
                dupe_labels[0]))

    if 'name' not in column_names:
        raise FileProcessError("CSV must have a column called Name")

    if len(set(fields_of_columns) - {None}) <= 1:
        # If we subtract the ignored columns,
        # all we are left with is the name column
        raise FileProcessError(
            "CSV must have at least one metadata column other than Name")

    csv_metadata = OrderedDict()
    image_names_seen = set()

    # Read the rest of the rows, which have metadata for one image per row.
    for row in reader:
        # Make a metadata dict for one image,
        # e.g. {photo_date='2016-06-12', camera='Nikon', ...}
        # A field name of None indicates that we're ignoring that column.
        # strip() removes leading/trailing whitespace from the CSV value.
        metadata_for_image = OrderedDict(
            (k, v.strip())
            for (k, v) in zip(fields_of_columns, row)
            if k is not None
        )

        image_name = metadata_for_image['name']
        if image_name in image_names_seen:
            raise FileProcessError(
                "More than one row with the same image name: {}".format(
                    image_name))
        image_names_seen.add(image_name)

        csv_metadata[image_name] = metadata_for_image

    verified_csv_metadata = metadata_csv_verify_contents(csv_metadata, source)

    return verified_csv_metadata


def metadata_csv_verify_contents(csv_metadata_by_image_name, source):
    """
    Argument dict is indexed by image name. We'll create a new dict indexed
    by metadata id, while verifying image existence and metadata validity.
    """
    csv_metadata = OrderedDict()

    for image_name, metadata_for_image in csv_metadata_by_image_name.items():

        try:
            metadata = \
                Metadata.objects.get(name=image_name, image__source=source)
        except Metadata.DoesNotExist:
            # This filename isn't in the source. Just skip this CSV row
            # without raising an error. It could be an image the user is
            # planning to upload later, or an image they're not planning
            # to upload but are still tracking in their records.
            continue

        # Use this form just to check the metadata, not to save anything.
        metadata_form = MetadataForm(
            metadata_for_image, instance=metadata, source=source)

        if not metadata_form.is_valid():
            # One of the filenames' metadata is not valid. Get one
            # error message and return that.
            for field_name, error_messages in metadata_form.errors.items():
                field_label = metadata_form.fields[field_name].label
                if error_messages != []:
                    error_message = error_messages[0]
                    raise FileProcessError(
                        "({filename} - {field_label}) {message}".format(
                            filename=metadata_for_image['name'],
                            field_label=field_label,
                            message=error_message,
                        )
                    )

        csv_metadata[metadata.pk] = metadata_for_image

    if len(csv_metadata) == 0:
        raise FileProcessError("No matching filenames found in the source")

    return csv_metadata


def metadata_preview(csv_metadata, source):
    table = []
    details = dict()
    field_names_to_labels = metadata_field_names_to_labels(source)
    num_fields_replaced = 0

    for metadata_id, metadata_for_image in csv_metadata.items():

        if len(table) == 0:
            # Column headers: Get the relevant field names from any data row
            # (the first one in our case), and go from field names to labels
            table.append(
                [field_names_to_labels[name]
                 for name in metadata_for_image.keys()]
            )

        metadata = Metadata.objects.get(pk=metadata_id, image__source=source)

        # Use this form just to preview the metadata, not to save anything.
        metadata_form = MetadataForm(
            metadata_for_image, instance=metadata, source=source)
        # We already validated previously, so this SHOULD be valid.
        if not metadata_form.is_valid():
            raise ValueError("Metadata became invalid for some reason.")

        row = []
        for field_name in metadata_for_image.keys():
            new_value = six.text_type(
                metadata_form.cleaned_data[field_name] or '')
            old_value = six.text_type(metadata_form.initial[field_name] or '')

            if (not old_value) or (old_value == new_value):
                # Old value is blank, or old value is equal to new value.
                # No value is being replaced here.
                row.append(new_value)
            else:
                # Old value is present and different; include this in the
                # display so the user knows what's going to be replaced.
                row.append([new_value, old_value])
                num_fields_replaced += 1
        table.append(row)

    details['numImages'] = len(csv_metadata)
    details['numFieldsReplaced'] = num_fields_replaced

    return table, details


def annotations_csv_to_dict(csv_stream, source):
    """
    Go from annotations CSV file stream to
    dict of (image ids -> lists of dicts with keys row, column, (opt.) label).

    The first CSV row is assumed to have column headers.
    Valid headers: Name, Row, Column, Label (not case sensitive)
    Label is optional.
    """
    reader = csv.reader(csv_stream, dialect='excel')

    # Read the first row, which should have column names.
    column_names = next(reader)
    # There could be a UTF-8 BOM character at the start of the file.
    # Strip it in that case.
    column_names[0] = column_names[0].lstrip(codecs.BOM_UTF8.decode('utf-8'))
    column_names = [name.lower().strip() for name in column_names]

    required_field_names = ['name', 'row', 'column']
    field_names = required_field_names + ['label']
    fields_of_columns = [
        name if name in field_names else None
        for name in column_names
    ]

    for name in required_field_names:
        if name not in column_names:
            raise FileProcessError(
                "CSV must have a column called {name}".format(
                    name=name.title()))

    csv_annotations = OrderedDict()

    # Read the rest of the rows. Each row has data for one point.
    for row in reader:
        csv_point_dict = OrderedDict(
            (k, v.strip())
            for (k, v) in zip(fields_of_columns, row)
            if k is not None and v != ''
        )

        for name in required_field_names:
            if name not in csv_point_dict:
                raise FileProcessError(
                    "CSV row {line_num} is missing a {name} value".format(
                        line_num=reader.line_num, name=name.title()))

        image_name = csv_point_dict.pop('name')
        if image_name not in csv_annotations:
            csv_annotations[image_name] = []

        csv_annotations[image_name].append(csv_point_dict)

    # So far we've checked the CSV formatting. Now check the validity
    # of the contents.
    csv_annotations = annotations_csv_verify_contents(csv_annotations, source)

    return csv_annotations


def annotations_csv_verify_contents(csv_annotations, source):
    """
    Argument dict is indexed by image name. We'll create a new dict indexed
    by image id, while verifying image existence, row, column, and label.
    """
    annotations = OrderedDict()

    for image_name, annotations_for_image in viewitems(csv_annotations):
        try:
            img = Image.objects.get(metadata__name=image_name, source=source)
        except Image.DoesNotExist:
            # This filename isn't in the source. Just skip it
            # without raising an error. It could be an image the user is
            # planning to upload later, or an image they're not planning
            # to upload but are still tracking in their records.
            continue

        for point_number, point_dict in enumerate(annotations_for_image, 1):

            # Check that row/column are integers within the image dimensions.

            point_error_prefix = \
                "For image {image_name}, point {point_number}:".format(
                    image_name=image_name, point_number=point_number)

            row_str = point_dict['row']
            try:
                row = int(row_str)
                if row < 0:
                    raise ValueError
            except ValueError:
                raise FileProcessError(
                    point_error_prefix +
                    " Row should be a non-negative integer, not {row}".format(
                        row=row_str))

            column_str = point_dict['column']
            try:
                column = int(column_str)
                if column < 0:
                    raise ValueError
            except ValueError:
                raise FileProcessError(
                    point_error_prefix +
                    " Column should be a non-negative integer,"
                    " not {column}".format(
                        column=column_str))

            if row > img.max_row:
                raise FileProcessError(
                    point_error_prefix +
                    " Row value is {row},"
                    " but the image is only {height} pixels high"
                    " (accepted values are 0~{max_row})".format(
                        row=row, height=img.original_height,
                        max_row=img.max_row))

            if column > img.max_column:
                raise FileProcessError(
                    point_error_prefix +
                    " Column value is {column},"
                    " but the image is only {width} pixels wide"
                    " (accepted values are 0~{max_column})".format(
                        column=column, width=img.original_width,
                        max_column=img.max_column))

            if 'label' in point_dict:
                # Check that the label is in the labelset
                label_code = point_dict['label']
                if not source.labelset.get_global_by_code(label_code):
                    raise FileProcessError(
                        point_error_prefix +
                        " No label of code {code} found"
                        " in this source's labelset".format(
                            code=label_code))

        annotations[img.pk] = annotations_for_image

    if len(annotations) == 0:
        raise FileProcessError("No matching image names found in the source")

    return annotations


def annotations_cpcs_to_dict_read_csv_row(
        reader, cpc_filename, num_tokens_expected):
    """
    Helper for annotations_cpcs_to_dict().
    Basically like calling next(reader), but with more controlled error
    handling.
    :param reader: A CSV reader object.
    :param cpc_filename: The filename of the .cpc file we're reading.
     Used for error messages.
    :param num_tokens_expected: Number of tokens expected in this CSV row.
    :return: iterable of the CSV tokens, stripped of leading and
     trailing whitespace.
    """
    try:
        row_tokens = [token.strip() for token in next(reader)]
    except StopIteration:
        raise FileProcessError(
            "File {cpc_filename} seems to have too few lines.".format(
                cpc_filename=cpc_filename))

    if len(row_tokens) != num_tokens_expected:
        raise FileProcessError((
            "File {cpc_filename}, line {line_num} has"
            " {num_tokens} comma-separated tokens, but"
            " {num_tokens_expected} were expected.").format(
                cpc_filename=cpc_filename,
                line_num=reader.line_num,
                num_tokens=len(row_tokens),
                num_tokens_expected=num_tokens_expected))

    return row_tokens


def annotations_cpcs_to_dict(cpc_names_and_streams, source):
    """
    :param cpc_names_and_streams: An iterable of Coral Point Count .cpc files
      as (file name, Unicode stream) tuples. One .cpc corresponds to one image.
    :param source: The source these .cpc files correspond to.
    :return: A dict of relevant info, with the following keys::
      annotations: dict of (image ids -> lists of dicts with keys row,
        column, (opt.) label).
      cpc_contents: dict of image ids -> .cpc's full contents as a string
      code_filepath: Local path to CPCe code file used by one of the .cpc's.
        Since CPCe is Windows only, this is going to be a Windows path.
      image_dir: Local path to image directory used by one of the .cpc's.
        Again, a Windows path. Ending slash can be present or not.
    Throws a FileProcessError if a .cpc has a problem.
    """

    cpc_dicts = []
    code_filepath = None

    for cpc_name, cpc_stream in cpc_names_and_streams:

        cpc_dict = dict(cpc_filename=cpc_name)

        # Each line of a .cpc file is like a CSV row.
        #
        # But different lines have different kinds of values, so we'll go
        # through the lines with next() instead of with a for loop.
        reader = csv.reader(cpc_stream, delimiter=',', quotechar='"')
        read_csv_row_curried = functools.partial(
            annotations_cpcs_to_dict_read_csv_row, reader, cpc_name)

        # Line 1
        code_filepath, image_filepath, _, _, _, _ = read_csv_row_curried(6)
        cpc_dict['image_filepath'] = image_filepath

        # Lines 2-5; don't need any info from these,
        # but they should have 2 tokens each
        for _ in range(4):
            read_csv_row_curried(2)

        # Line 6: number of points
        token = read_csv_row_curried(1)[0]
        try:
            num_points = int(token)
            if num_points <= 0:
                raise ValueError
        except ValueError:
            raise FileProcessError((
                "File {cpc_filename}, line {line_num} is supposed to have"
                " the number of points, but this line isn't a"
                " positive integer: {token}").format(
                    cpc_filename=cpc_name,
                    line_num=reader.line_num,
                    token=token))

        # Next num_points lines: point positions.
        # CPCe point positions are on a scale of 15 units = 1 pixel, and
        # the positions start from 0, not 1.
        cpc_dict['points'] = []
        for _ in range(num_points):
            x_str, y_str = read_csv_row_curried(2)
            cpc_dict['points'].append(dict(x_str=x_str, y_str=y_str))

        # Next num_points lines: point labels.
        # Assumption: label code in CoralNet source's labelset == label code
        # in the .cpc file (case insensitive).
        # We're taking advantage of the fact that the previous section
        # and this section are both in point-number order. As long as we
        # maintain that order, we assign labels to the correct points.
        for point_index in range(num_points):
            _, label_code, _, _ = read_csv_row_curried(4)
            if label_code:
                cpc_dict['points'][point_index]['label'] = label_code

        cpc_stream.seek(0)
        cpc_dict['cpc_content'] = cpc_stream.read()

        cpc_dicts.append(cpc_dict)

    # So far we've checked the .cpc formatting. Now check the validity
    # of the contents.
    cpc_annotations, cpc_contents, cpc_filenames, image_dir = \
        annotations_cpc_verify_contents(cpc_dicts, source)

    return dict(
        annotations=cpc_annotations,
        cpc_contents=cpc_contents,
        cpc_filenames=cpc_filenames,
        code_filepath=code_filepath,
        image_dir=image_dir,
    )


def annotations_cpc_verify_contents(cpc_dicts, source):
    """
    Argument dict is a list of dicts, one dict per .cpc file.

    We'll create a new annotations dict indexed
    by image id, while verifying image existence, row, column, and label.

    While we're at it, we'll also make a dict from image id to .cpc contents.
    """
    annotations = OrderedDict()
    cpc_contents = OrderedDict()
    cpc_filenames = OrderedDict()
    image_names_to_cpc_filenames = dict()
    image_dir = None

    for cpc_dict in cpc_dicts:

        cpc_filename = cpc_dict['cpc_filename']

        # The image filepath follows the rules of the OS running CPCe,
        # not the rules of the server OS. So we don't use Path.
        # CPCe only runs on Windows, so we can assume it's a Windows
        # path. That means using PureWindowsPath (WindowsPath can only
        # be instantiated on a Windows OS).
        cpc_image_filepath = PureWindowsPath(cpc_dict['image_filepath'])
        image_filename = cpc_image_filepath.name

        # Match up the CPCe image filepath to an image name on CoralNet.
        #
        # Let's say the image filepath is D:\Site A\Transect 1\01.jpg
        # Example image names:
        # D:\Site A\Transect 1\01.jpg: best match
        # Site A\Transect 1\01.jpg: 2nd best match
        # Transect 1\01.jpg: 3rd best match
        # 01.jpg: 4th best match
        # Transect 1/01.jpg: same as with backslash
        # /Transect 1/01.jpg: same as without leading slash
        # 23.jpg: non-match 1
        # 4501.jpg: non-match 2
        # sect 1\01.jpg: non-match 3
        #
        # First get names consisting of 01.jpg preceded by /, \, or nothing.
        # This avoids non-match 1 and non-match 2.
        regex_escaped_filename = re.escape(image_filename)
        name_regex = r'^(.*[\\|/])?{fn}$'.format(fn=regex_escaped_filename)
        image_candidates = source.image_set.filter(
            metadata__name__regex=name_regex)
        # Find the best match while avoiding non-match 3.
        img = None
        for image_candidate in image_candidates:
            # Passing through PWP ensures we consistently use backslashes
            # instead of forward slashes
            image_name = str(PureWindowsPath(image_candidate.metadata.name))
            if image_name == str(cpc_image_filepath):
                # Best possible match
                img = image_candidate
                image_dir = ''
                break

            # Iterate over parents, from top (D:\)
            # to bottom (D:\Site A\Transect 1).
            # If a parent combines with image_name to form the full path, then
            # we have a match.
            # TODO: This won't work if image_name starts with a slash; do we
            # want to accommodate that or not?
            for parent in cpc_image_filepath.parents:
                if PureWindowsPath(parent, image_name) == cpc_image_filepath:
                    # It's a match
                    if img and len(img.metadata.name) > len(image_name):
                        # There's already a longer match
                        pass
                    else:
                        # This is the best match so far
                        img = image_candidate
                        image_dir = str(parent)
                    # Move onto the next candidate
                    break

        if img is None:
            # No matching image names in the source. Just skip this CPC
            # without raising an error. It could be an image the user is
            # planning to upload later, or an image they're not planning
            # to upload but are still tracking in their records.
            continue

        image_name = img.metadata.name

        if image_name in image_names_to_cpc_filenames:
            raise FileProcessError((
                "Image {name} has points from more than one .cpc file: {f1}"
                " and {f2}. There should be only one .cpc file"
                " per image.").format(
                    name=image_name,
                    f1=image_names_to_cpc_filenames[image_name],
                    f2=cpc_filename,
                )
            )
        image_names_to_cpc_filenames[image_name] = cpc_filename

        annotations_for_image = []

        for point_number, cpc_point_dict in enumerate(cpc_dict['points'], 1):

            # Check that row/column are integers within the image dimensions.
            # Convert from CPCe units to pixels in the meantime.

            point_error_prefix = \
                "From file {cpc_filename}, point {point_number}:".format(
                    cpc_filename=cpc_filename, point_number=point_number)

            try:
                y = int(cpc_point_dict['y_str'])
                if y < 0:
                    raise ValueError
            except ValueError:
                raise FileProcessError((
                    point_error_prefix +
                    " Row should be a non-negative integer, not"
                    " {y_str}").format(
                        y_str=cpc_point_dict['y_str']))

            try:
                x = int(cpc_point_dict['x_str'])
                if x < 0:
                    raise ValueError
            except ValueError:
                raise FileProcessError((
                    point_error_prefix +
                    " Column should be a non-negative integer, not"
                    " {x_str}").format(
                        x_str=cpc_point_dict['x_str']))

            row = int(round(y/15))
            column = int(round(x/15))
            point_dict = dict(
                row=row,
                column=column,
            )

            if row > img.max_row:
                raise FileProcessError(
                    point_error_prefix +
                    " Row value of {y} corresponds to pixel {row},"
                    " but image {name} is only {height} pixels high"
                    " (accepted values are 0~{max_row})".format(
                        y=y, row=row, name=image_name,
                        height=img.original_height,
                        max_row=img.max_row))

            if column > img.max_column:
                raise FileProcessError(
                    point_error_prefix +
                    " Column value of {x} corresponds to pixel {column},"
                    " but image {name} is only {width} pixels wide"
                    " (accepted values are 0~{max_column})".format(
                        x=x, column=column, name=image_name,
                        width=img.original_width,
                        max_column=img.max_column))

            if 'label' in cpc_point_dict:
                # Check that the label is in the labelset
                label_code = cpc_point_dict['label']
                if not source.labelset.get_global_by_code(label_code):
                    raise FileProcessError(
                        point_error_prefix +
                        " No label of code {code} found"
                        " in this source's labelset".format(
                            code=label_code))
                point_dict['label'] = label_code

            annotations_for_image.append(point_dict)

        annotations[img.pk] = annotations_for_image
        cpc_contents[img.pk] = cpc_dict['cpc_content']
        cpc_filenames[img.pk] = cpc_filename

    if len(annotations) == 0:
        raise FileProcessError("No matching image names found in the source")

    # Note that image_dir was set the last time we picked an image match.
    # So image_dir corresponds to an image match; that's all we want.
    return annotations, cpc_contents, cpc_filenames, image_dir


def annotations_preview(csv_annotations, source):
    table = []
    details = dict()
    total_csv_points = 0
    total_csv_annotations = 0
    num_images_with_existing_annotations = 0

    for image_id, points_list in csv_annotations.items():

        img = Image.objects.get(pk=image_id, source=source)
        preview_dict = dict(
            name=img.metadata.name,
            link=reverse('annotation_tool', kwargs=dict(image_id=img.pk)),
        )

        num_csv_points = len(points_list)
        total_csv_points += num_csv_points
        num_csv_annotations = \
            sum(1 for point_dict in points_list if 'label' in point_dict)
        total_csv_annotations += num_csv_annotations
        preview_dict['createInfo'] = \
            "Will create {points} points, {annotations} annotations".format(
                points=num_csv_points, annotations=num_csv_annotations)

        num_existing_annotations = (
            Annotation.objects.filter(image=img)
            .exclude(user=get_robot_user())
            .count()
        )
        if num_existing_annotations > 0:
            preview_dict['deleteInfo'] = \
                "Will delete {annotations} existing annotations".format(
                    annotations=num_existing_annotations)
            num_images_with_existing_annotations += 1

        table.append(preview_dict)

    details['numImages'] = len(csv_annotations)
    details['totalPoints'] = total_csv_points
    details['totalAnnotations'] = total_csv_annotations
    details['numImagesWithExistingAnnotations'] = \
        num_images_with_existing_annotations

    return table, details


def upload_image_process(image_file, image_name, source, current_user):

    metadata_obj = Metadata(
        name=image_name,
        annotation_area=source.image_annotation_area,
    )
    metadata_obj.save()

    image_features = Features()
    image_features.save()

    # Save the image into the DB
    img = Image(
        original_file=image_file,
        uploaded_by=current_user,
        point_generation_method=source.default_point_generation_method,
        metadata=metadata_obj,
        source=source,
        features=image_features
    )
    img.save()

    # Generate and save points
    generate_points(img)

    return img


def find_dupe_image(source, image_name):
    """
    Sees if the given source already has an image with this name.

    If a duplicate image was found, returns that duplicate.
    If no duplicate was found, returns None.
    """
    image_matches = Image.objects.filter(
        source=source, metadata__name=image_name)

    if len(image_matches) >= 1:
        return image_matches[0]
    else:
        return None
