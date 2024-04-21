import csv
from zipfile import ZipFile

from django.conf import settings
from django.core.exceptions import ValidationError
from django.http import HttpResponse

from sources.utils import metadata_field_names_to_labels
from vision_backend.utils import get_label_scores_for_point
from visualization.forms import create_image_filter_form


def get_request_images(request, source):
    if request.POST:
        image_form = create_image_filter_form(request.POST, source)
    else:
        image_form = create_image_filter_form(request.GET, source)

    if image_form:
        if image_form.is_valid():
            image_set = image_form.get_images()
        else:
            # This is an unusual error case where the current image search
            # worked for the Browse-images page load, but not for the
            # subsequent export.
            raise ValidationError("Image-search parameters were invalid.")
        applied_search_display = image_form.get_applied_search_display()
    else:
        image_set = source.image_set.order_by('metadata__name', 'pk')
        applied_search_display = "Sorting by name, ascending"
    return image_set, applied_search_display


def create_stream_response(content_type, filename):
    """
    Create a downloadable-file HTTP response.
    The response object can be used as a stream, which a file writer
    can write to.

    https://docs.djangoproject.com/en/dev/ref/request-response/#telling-the-browser-to-treat-the-response-as-a-file-attachment
    """
    response = HttpResponse(content_type=content_type)
    response['Content-Disposition'] = \
        'attachment;filename="{filename}"'.format(filename=filename)
    return response


def create_csv_stream_response(filename):
    return create_stream_response('text/csv', filename)


def create_zip_stream_response(filename):
    # https://stackoverflow.com/a/29539722/
    return create_stream_response('application/zip', filename)


def write_zip(zip_stream, file_strings):
    """
    Write a zip file to a stream.
    :param zip_stream:
      The file stream to write the zip file to.
    :param file_strings:
      Zip contents as a dict of filepaths to byte strings (e.g. result of
      getvalue() on a byte stream).
      Filepath is the path that the file will have in the zip archive.
    :return:
      None.
    """
    zip_file = ZipFile(zip_stream, 'w')
    for filepath, content_string in file_strings.items():
        zip_file.writestr(filepath, content_string)


def write_annotations_csv(response, source, image_set, optional_columns):
    """
    :param response: Stream response object which we can write file content to.
    :param source: The source we're exporting annotations for.
    :param image_set: Non-empty queryset of images to write annotations for.
        Images should all be from the source which was also passed in.
    :param optional_columns: List of string keys indicating optional column sets
        to add.
    :return: None. This function simply writes CSV file content to the
        response argument.
    """
    metadata_field_labels = metadata_field_names_to_labels(source)
    metadata_date_aux_fields = [
        'photo_date', 'aux1', 'aux2', 'aux3', 'aux4', 'aux5']
    metadata_other_fields = [
        f for f in metadata_field_labels.keys()
        if f not in [
            'name', 'photo_date', 'aux1', 'aux2', 'aux3', 'aux4', 'aux5']
    ]

    fieldnames = ["Name", "Row", "Column", "Label"]

    if 'annotator_info' in optional_columns:
        fieldnames.extend(["Annotator", "Date annotated"])

    if 'machine_suggestions' in optional_columns:
        for n in range(1, settings.NBR_SCORES_PER_ANNOTATION+1):
            fieldnames.extend([
                "Machine suggestion {n}".format(n=n),
                "Machine confidence {n}".format(n=n),
            ])

    if 'metadata_date_aux' in optional_columns:
        date_aux_labels = [
            metadata_field_labels[name]
            for name in metadata_date_aux_fields
        ]
        # Insert these columns before the Row column
        insert_index = fieldnames.index("Row")
        fieldnames = (
            fieldnames[:insert_index]
            + date_aux_labels
            + fieldnames[insert_index:])

    if 'metadata_other' in optional_columns:
        other_meta_labels = [
            metadata_field_labels[name]
            for name in metadata_other_fields
        ]
        # Insert these columns before the Row column
        insert_index = fieldnames.index("Row")
        fieldnames = (
            fieldnames[:insert_index]
            + other_meta_labels
            + fieldnames[insert_index:])

    writer = csv.DictWriter(response, fieldnames)
    writer.writeheader()

    # One image at a time.
    for image in image_set:

        # Order image annotations by point number.
        for annotation in image.annotation_set.order_by('point__point_number'):

            # One row per annotation.
            row = {
                "Name": image.metadata.name,
                "Row": annotation.point.row,
                "Column": annotation.point.column,
                "Label": annotation.label_code,
            }

            if 'annotator_info' in optional_columns:
                # Truncate date precision at seconds
                date_annotated = annotation.annotation_date.replace(
                    microsecond=0)
                row.update({
                    "Annotator": annotation.user.username,
                    "Date annotated": date_annotated,
                })

            if 'machine_suggestions' in optional_columns:
                label_scores = get_label_scores_for_point(
                    annotation.point, ordered=True)
                for i in range(settings.NBR_SCORES_PER_ANNOTATION):
                    try:
                        score = label_scores[i]
                    except IndexError:
                        # We might need to fill in some blank scores. For
                        # example, when the classification system hasn't
                        # annotated these points yet, or when the labelset has
                        # fewer than NBR_SCORES_PER_ANNOTATION labels.
                        score = {'label': "", 'score': ""}
                    n = i + 1
                    row.update({
                        "Machine suggestion {n}".format(n=n): score['label'],
                        "Machine confidence {n}".format(n=n): score['score'],
                    })

            if 'metadata_date_aux' in optional_columns:
                label_value_tuples = []
                for field_name in metadata_date_aux_fields:
                    label = metadata_field_labels[field_name]
                    value = getattr(image.metadata, field_name)
                    if value is None:
                        value = ""
                    label_value_tuples.append((label, value))
                row.update(dict(label_value_tuples))

            if 'metadata_other' in optional_columns:
                label_value_tuples = []
                for field_name in metadata_other_fields:
                    label = metadata_field_labels[field_name]
                    value = getattr(image.metadata, field_name)
                    if value is None:
                        value = ""
                    label_value_tuples.append((label, value))
                row.update(dict(label_value_tuples))

            writer.writerow(row)


def write_labelset_csv(writer, source):
    # Header row
    row = ["Label ID", "Short Code"]
    writer.writerow(row)

    if not source.labelset:
        # This shouldn't happen unless the user does URL crafting to get here
        # for some reason. Not a big deal though, we'll just return a CSV
        # with no data rows.
        return

    labels = source.labelset.get_labels().order_by('code')

    for label in labels:
        row = [
            label.global_label_id,
            label.code,
        ]
        writer.writerow(row)
