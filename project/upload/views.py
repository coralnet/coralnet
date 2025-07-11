import json

from django.conf import settings
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from annotations.model_utils import AnnotationArea
from images.forms import MetadataForm
from images.model_utils import PointGen
from images.models import Metadata
from images.utils import find_dupe_image, get_aux_labels, metadata_obj_to_dict
from lib.decorators import source_permission_required
from lib.exceptions import FileProcessError
from lib.forms import get_one_form_error
from lib.utils import filesize_display
from sources.models import Source
from sources.utils import metadata_field_names_to_labels
from vision_backend.utils import schedule_source_check_on_commit
from .forms import (
    CSVImportForm, ImageUploadForm, ImageUploadFrontendForm)
from .utils import (
    metadata_csv_to_dict, metadata_preview, upload_image_process)


@source_permission_required('source_id', perm=Source.PermTypes.EDIT.code)
def upload_portal(request, source_id):
    """
    Page which points to the pages for the three different upload types.
    """
    if request.method == 'POST':
        if request.POST.get('images'):
            return HttpResponseRedirect(
                reverse('upload_images', args=[source_id]))
        if request.POST.get('metadata'):
            return HttpResponseRedirect(
                reverse('upload_metadata', args=[source_id]))
        if request.POST.get('annotations_cpc'):
            return HttpResponseRedirect(
                reverse('cpce:upload_page', args=[source_id]))
        if request.POST.get('annotations_csv'):
            return HttpResponseRedirect(
                reverse('annotations_upload_page', args=[source_id]))

    source = get_object_or_404(Source, id=source_id)
    return render(request, 'upload/upload_portal.html', {
        'source': source,
    })


@source_permission_required('source_id', perm=Source.PermTypes.EDIT.code)
def upload_images(request, source_id):
    """
    Upload images to a source.
    This view is for the non-Ajax frontend.
    """
    source = get_object_or_404(Source, id=source_id)

    images_form = ImageUploadFrontendForm()

    auto_generate_points_message = (
        "We will generate points for the images you upload.\n"
        "Your Source's point generation settings: {point_gen}\n"
        "Your Source's annotation area settings: {anno_area}").format(
            point_gen=PointGen.from_db_value(
                source.default_point_generation_method),
            anno_area=AnnotationArea.from_db_value(
                source.image_annotation_area),
        )

    return render(request, 'upload/upload_images.html', {
        'source': source,
        'images_form': images_form,
        'auto_generate_points_message': auto_generate_points_message,
        'image_upload_max_file_size': filesize_display(
            settings.IMAGE_UPLOAD_MAX_FILE_SIZE),
    })


@require_POST
@source_permission_required(
    'source_id', perm=Source.PermTypes.EDIT.code, ajax=True)
def upload_images_preview_ajax(request, source_id):
    """
    Preview the images that are about to be uploaded.
    Check to see if there's any problems with the filenames or file sizes.
    """
    source = get_object_or_404(Source, id=source_id)

    file_info_list = json.loads(request.POST.get('file_info'))

    statuses = []

    for file_info in file_info_list:

        dupe_image = find_dupe_image(source, file_info['filename'])
        if dupe_image:
            statuses.append(dict(
                error="Image with this name already exists",
                url=reverse('image_detail', args=[dupe_image.id]),
            ))
        elif file_info['size'] > settings.IMAGE_UPLOAD_MAX_FILE_SIZE:
            statuses.append(dict(
                error="Exceeds size limit of {limit}".format(
                    limit=filesize_display(
                        settings.IMAGE_UPLOAD_MAX_FILE_SIZE))
            ))
        else:
            statuses.append(dict(
                ok=True,
            ))

    return JsonResponse(dict(
        statuses=statuses,
    ))


@require_POST
@source_permission_required(
    'source_id', perm=Source.PermTypes.EDIT.code, ajax=True)
def upload_images_ajax(request, source_id):
    """
    After the "Start upload" button is clicked, this view is entered once
    for each image file. This view saves the image to the database
    and media storage.
    """
    source = get_object_or_404(Source, id=source_id)

    # Retrieve image related fields
    image_form = ImageUploadForm(request.POST, request.FILES)

    # Check for validity of the file (filetype and non-corruptness) and
    # the options forms.
    if not image_form.is_valid():
        # Examples of errors: filetype is not an image,
        # file is corrupt, file is empty, etc.
        return JsonResponse(dict(
            error=get_one_form_error(image_form),
        ))

    # Check for dupe name
    image_name = image_form.cleaned_data['name']
    if find_dupe_image(source, image_name):
        # Dupe.
        # Note: if there's a race condition that makes a dupe slip through
        # this check, it'll still get caught, but it'll be a DB-level
        # IntegrityError (resulting in 500) instead of this error.
        return JsonResponse(dict(
            error="Image with this name already exists.",
        ))

    img = upload_image_process(
        image_file=image_form.cleaned_data['file'],
        image_name=image_name,
        source=source,
        current_user=request.user,
    )

    # The uploaded images should be ready for feature extraction.
    schedule_source_check_on_commit(source_id)

    return JsonResponse(dict(
        success=True,
        link=reverse('image_detail', args=[img.id]),
        image_id=img.id,
    ))


@source_permission_required('source_id', perm=Source.PermTypes.EDIT.code)
def upload_metadata(request, source_id):
    """
    Set image metadata by uploading a CSV file containing the metadata.
    This view is for the non-Ajax frontend.
    """
    source = get_object_or_404(Source, id=source_id)

    csv_import_form = CSVImportForm()

    return render(request, 'upload/upload_metadata.html', {
        'source': source,
        'csv_import_form': csv_import_form,
        'field_labels': metadata_field_names_to_labels(source).values(),
        'aux_field_labels': get_aux_labels(source),
    })


@require_POST
@source_permission_required(
    'source_id', perm=Source.PermTypes.EDIT.code, ajax=True)
def upload_metadata_preview_ajax(request, source_id):
    """
    Set image metadata by uploading a CSV file containing the metadata.

    This view takes the CSV file, processes it, saves the processed metadata
    to the session, and returns a preview table of the metadata to be saved.
    """
    source = get_object_or_404(Source, id=source_id)

    csv_import_form = CSVImportForm(request.POST, request.FILES)
    if not csv_import_form.is_valid():
        return JsonResponse(dict(
            error=csv_import_form.errors['csv_file'][0],
        ))

    try:
        # Dict of (metadata ids -> dicts of (column name -> value))
        csv_metadata = metadata_csv_to_dict(
            csv_import_form.get_csv_stream(), source)
    except FileProcessError as error:
        return JsonResponse(dict(
            error=str(error),
         ))

    preview_table, preview_details = \
        metadata_preview(csv_metadata, source)

    request.session['csv_metadata'] = csv_metadata

    return JsonResponse(dict(
        success=True,
        previewTable=preview_table,
        previewDetails=preview_details,
    ))


@require_POST
@source_permission_required(
    'source_id', perm=Source.PermTypes.EDIT.code, ajax=True)
def upload_metadata_ajax(request, source_id):
    """
    Set image metadata by uploading a CSV file containing the metadata.

    This view gets the metadata that was previously saved to the session
    by the upload-preview view. Then it saves the metadata to the database.
    """
    source = get_object_or_404(Source, id=source_id)

    csv_metadata = request.session.pop('csv_metadata', None)
    if not csv_metadata:
        return JsonResponse(dict(
            error=(
                "We couldn't find the expected data in your session."
                " Please try loading this page again. If the problem persists,"
                " let us know on the forum."
            ),
        ))

    for metadata_id, csv_metadata_for_image in csv_metadata.items():

        metadata = Metadata.objects.get(pk=metadata_id, image__source=source)
        new_metadata_dict = metadata_obj_to_dict(metadata)
        new_metadata_dict.update(csv_metadata_for_image)

        metadata_form = MetadataForm(
            new_metadata_dict, instance=metadata, source=source)

        # We already validated previously, so this SHOULD be valid.
        if not metadata_form.is_valid():
            raise ValueError("Metadata became invalid for some reason.")

        metadata_form.save()

    return JsonResponse(dict(
        success=True,
    ))
