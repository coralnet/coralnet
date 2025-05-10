import base64
from zipfile import ZipFile

from django.core.exceptions import ValidationError
from django.http import HttpResponse

from visualization.forms import ImageSearchForm


def get_request_images(request, source):
    image_form = ImageSearchForm(request.POST or request.GET, source=source)

    if image_form.is_valid():
        image_set = image_form.get_images()
    else:
        # This is an unusual error case where the current image search
        # worked for the Browse-images page load, but not for the
        # subsequent export.
        raise ValidationError("Image-search parameters were invalid.")
    applied_search_display = image_form.get_applied_search_display()
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


def file_to_session_data(filename, io_stream, is_binary):
    if is_binary:
        # Session data is encoded as JSON, and bytes instances can't
        # be encoded as JSON. So we convert to a base64 string.
        content = base64.b64encode(io_stream.getvalue()).decode()
    else:
        content = io_stream.getvalue()
    return dict(
        filename=filename,
        content=content,
        is_binary=is_binary,
    )


def session_data_to_file(session_data):
    if session_data['is_binary']:
        content = base64.b64decode(session_data['content'])
    else:
        content = session_data['content']
    return session_data['filename'], content
