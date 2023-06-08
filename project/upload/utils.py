import codecs
from collections import defaultdict, OrderedDict
import csv
from io import StringIO
from typing import Callable, Dict, List, Optional, Tuple

import charset_normalizer
from django.urls import reverse

from annotations.models import ImageAnnotationInfo
from images.forms import MetadataForm
from images.models import Image, Metadata, Source
from images.utils import (
    aux_label_name_collisions,
    generate_points,
    metadata_field_names_to_labels,
)
from lib.exceptions import FileProcessError
from vision_backend.models import Features


def text_file_to_unicode_stream(text_file):
    # Detect charset and convert to Unicode as needed.
    content_bytes = text_file.read()
    unicode_text = content_bytes.decode(
        charset_normalizer.detect(content_bytes)['encoding'])
    # Convert the text into a line-by-line stream.
    return StringIO(unicode_text, newline='')


def csv_to_dicts(
        csv_stream: StringIO,
        required_columns: Dict[str, str],
        optional_columns: Dict[str, str],
        unique_keys: List[str],
        more_column_checks: Optional[Callable[[List[str]], None]] = None,
) -> List[dict]:
    """
    required_columns must be filled in for every row.
    optional_columns may have blank cells and may not be included in the
    CSV at all.
    unique_keys aren't necessarily required columns.
    """
    # DictReader is not used here, because the fact that column names need
    # to be transformed to get the dict keys makes usage a bit clunky.
    reader = csv.reader(csv_stream, dialect='excel')

    # Read the first row, which should have column headers.
    csv_headers = next(reader)
    # There could be a UTF-8 BOM character at the start of the file.
    # Strip it in that case.
    csv_headers[0] = csv_headers[0].lstrip(codecs.BOM_UTF8.decode())
    # Strip whitespace in general.
    csv_headers = [h.strip() for h in csv_headers]

    # Combine required and optional.
    known_columns = dict(**required_columns, **optional_columns)
    # Make a reverse lookup.
    known_headers_to_keys = dict(
        (h, k) for k, h in known_columns.items())

    # To facilitate header matching, use the same case as what's used in
    # known_columns.
    csv_headers_standard_case = []
    for csv_h in csv_headers:
        standard_case = None
        for known_h in known_columns.values():
            if csv_h.lower() == known_h.lower():
                standard_case = known_h
                break
        if standard_case:
            csv_headers_standard_case.append(standard_case)
        else:
            csv_headers_standard_case.append(None)
    accepted_headers = [
        h for h in csv_headers_standard_case if h is not None]

    # Enforce required columns.
    for h in required_columns.values():
        if h not in accepted_headers:
            raise FileProcessError(f"CSV must have a column called {h}")
    # Enforce any other column constraints.
    if more_column_checks:
        more_column_checks(accepted_headers)

    row_dicts = []
    unique_values = set()

    # Read the data rows.
    for row in reader:
        # Pad the row to the same number of columns as the column headers.
        row = row + ['']*(len(csv_headers) - len(row))

        row_data = dict()
        for h, cell_value in zip(csv_headers_standard_case, row):
            if not h:
                # Not a known column header
                continue
            key = known_headers_to_keys[h]
            row_data[key] = cell_value.strip()

        # Enforce presence of a value for each required column.
        for k in required_columns.keys():
            if row_data[k] == '':
                raise FileProcessError(
                    f"CSV row {reader.line_num}:"
                    f" Must have a value for {known_columns[k]}")

        # Check for uniqueness of values under the unique_keys.
        # If unique_keys has more than one key, it specifies
        # columns that are unique *together*.
        if unique_keys:
            if len(unique_keys) > 1:
                unique_value = tuple(row_data.get(key) for key in unique_keys)
            else:
                unique_value = row_data.get(unique_keys[0])
            if unique_value in unique_values:
                unique_headers_str = ' + '.join(
                    known_columns[k] for k in unique_keys)
                raise FileProcessError(
                    f"More than one row with the same"
                    f" {unique_headers_str}: {unique_value}")
            unique_values.add(unique_value)

        row_dicts.append(row_data)

    if len(row_dicts) == 0:
        raise FileProcessError("No data rows found in the CSV.")

    return row_dicts


def metadata_csv_to_dict(
        csv_stream: StringIO, source: Source) -> Dict[int, Dict]:
    """
    Go from metadata CSV file stream to a dict of metadata dicts.
    Valid column headers are metadata field labels like
    "Date", "Aux3", and "White balance card".
    """
    dupe_labels = aux_label_name_collisions(source)
    if dupe_labels:
        raise FileProcessError(
            f"More than one metadata field uses the label '{dupe_labels[0]}'."
            " Your auxiliary fields' names must be unique"
            " and different from the default metadata fields.")

    def exists_non_name_column(accepted_columns):
        if len(accepted_columns) <= 1:
            raise FileProcessError(
                "CSV must have at least one metadata column other than Name")

    metadata_fields_dict = metadata_field_names_to_labels(source)
    csv_metadata = csv_to_dicts(
        csv_stream,
        required_columns=dict(name=metadata_fields_dict['name']),
        optional_columns=dict(
            (k, v)
            for k, v in metadata_fields_dict.items()
            if k != 'name'
        ),
        unique_keys=['name'],
        more_column_checks=exists_non_name_column,
    )

    verified_csv_metadata = metadata_csv_verify_contents(csv_metadata, source)

    return verified_csv_metadata


def metadata_csv_verify_contents(
        row_dicts: List[Dict], source: Source) -> Dict[int, Dict]:
    """
    Return dict has keys = metadata id, value = input dict.
    Meanwhile, this verifies image existence and metadata validity.
    """
    csv_metadata = OrderedDict()

    for metadata_for_image in row_dicts:

        try:
            metadata = Metadata.objects.get(
                name=metadata_for_image['name'], image__source=source)
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
                if len(error_messages) > 0:
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
            new_value = str(metadata_form.cleaned_data[field_name] or '')
            old_value = str(metadata_form.initial[field_name] or '')

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


def annotations_csv_to_dict(
        csv_stream: StringIO, source: Source) -> Dict[int, List[Dict]]:
    """
    Returned dict has keys = image ids, and
    values = lists of dicts with keys row, column, (opt.) label).

    Valid CSV headers: Name, Row, Column, Label (not case sensitive)
    Label is optional.
    """
    row_dicts = csv_to_dicts(
        csv_stream,
        required_columns=dict(
            name="Name",
            row="Row",
            column="Column",
        ),
        optional_columns=dict(
            label="Label",
        ),
        unique_keys=[],
    )

    csv_annotations = defaultdict(list)
    for row_dict in row_dicts:
        image_name = row_dict.pop('name')
        csv_annotations[image_name].append(row_dict)

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

    for image_name, annotations_for_image in csv_annotations.items():
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
                f"For image {image_name}, point {point_number}:"

            row_str = point_dict['row']
            try:
                row = int(row_str)
                if row < 0:
                    raise ValueError
            except ValueError:
                raise FileProcessError(
                    point_error_prefix +
                    f" Row should be a non-negative integer, not {row_str}")

            column_str = point_dict['column']
            try:
                column = int(column_str)
                if column < 0:
                    raise ValueError
            except ValueError:
                raise FileProcessError(
                    point_error_prefix +
                    f" Column should be a non-negative integer,"
                    f" not {column_str}")

            if row > img.max_row:
                raise FileProcessError(
                    point_error_prefix +
                    f" Row value is {row}, but"
                    f" the image is only {img.original_height} pixels high"
                    f" (accepted values are 0~{img.max_row})")

            if column > img.max_column:
                raise FileProcessError(
                    point_error_prefix +
                    f" Column value is {column}, but"
                    f" the image is only {img.original_width} pixels wide"
                    f" (accepted values are 0~{img.max_column})")

            label_code = point_dict.get('label')
            if label_code:
                # Check that the label is in the labelset
                if not source.labelset.get_global_by_code(label_code):
                    raise FileProcessError(
                        point_error_prefix +
                        f" No label of code {label_code} found"
                        f" in this source's labelset")

        annotations[img.pk] = annotations_for_image

    if len(annotations) == 0:
        raise FileProcessError("No matching image names found in the source")

    return annotations


def annotations_preview(
        csv_annotations: Dict[int, list],
        source: Source,
) -> Tuple[list, dict]:

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
            sum(1 for point_dict in points_list if point_dict.get('label'))
        total_csv_annotations += num_csv_annotations
        preview_dict['createInfo'] = \
            "Will create {points} points, {annotations} annotations".format(
                points=num_csv_points, annotations=num_csv_annotations)

        num_existing_annotations = img.annotation_set.confirmed().count()
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

    # Save the image into the DB
    img = Image(
        original_file=image_file,
        uploaded_by=current_user,
        point_generation_method=source.default_point_generation_method,
        metadata=metadata_obj,
        source=source,
    )
    img.save()

    annotation_info = ImageAnnotationInfo(image=img)
    annotation_info.save()

    features = Features(image=img)
    features.save()

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
