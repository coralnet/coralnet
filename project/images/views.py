from django.contrib import messages
from django.http import HttpResponseRedirect
from django.shortcuts import render, get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_POST

from annotations.model_utils import image_annotation_verbose_status_label
from annotations.models import Annotation
from annotations.utils import (
    image_annotation_area_is_editable,
    image_has_any_confirmed_annotations,
)
from labels.models import LabelGroup
from lib.decorators import (
    image_annotation_area_must_be_editable,
    image_permission_required,
    image_visibility_required,
)
from sources.models import Source
from vision_backend.utils import reset_features
from . import utils
from .forms import MetadataFormForDetailEdit
from .models import Image, Metadata


@image_visibility_required('image_id')
def image_detail(request, image_id):
    """
    View for seeing an image's full size and details/metadata.
    """
    image = get_object_or_404(Image, id=image_id)
    source = image.source
    metadata = image.metadata

    other_fields = [
        dict(
            name=field_name,
            # Field's verbose name in title case (name -> Name)
            label=Metadata._meta.get_field(field_name).verbose_name.title(),
            value=getattr(metadata, field_name),
        )
        for field_name in [
            'height_in_cm', 'latitude', 'longitude', 'depth',
            'camera', 'photographer', 'water_quality', 'strobes',
            'framing', 'balance', 'comments',
        ]
    ]

    # Feel free to change this constant according to the page layout.
    MAX_SCALED_WIDTH = 800
    if image.original_width > MAX_SCALED_WIDTH:
        # Parameters into the easy_thumbnails template tag:
        # (specific width, height that keeps the aspect ratio)
        thumbnail_dimensions = (MAX_SCALED_WIDTH, 0)
    else:
        # No thumbnail needed
        thumbnail_dimensions = False

    # Next and previous image links.
    # Ensure the ordering is unambiguous.
    source_images = source.image_set.order_by('metadata__name', 'pk')
    next_image = utils.get_next_image(image, source_images, wrap=False)
    prev_image = utils.get_prev_image(image, source_images, wrap=False)

    return render(request, 'images/image_detail.html', {
        'source': source,
        'image': image,
        'next_image': next_image,
        'prev_image': prev_image,
        'metadata': metadata,
        'image_meta_table': utils.get_date_and_aux_metadata_table(image),
        'other_fields': other_fields,
        'has_thumbnail': bool(thumbnail_dimensions),
        'thumbnail_dimensions': thumbnail_dimensions,
        'annotation_status': image_annotation_verbose_status_label(image),
        # The boolean flags below determine what actions can be performed
        # on the image.
        'annotation_area_editable':
            image_annotation_area_is_editable(image),
        'has_any_confirmed_annotations':
            image_has_any_confirmed_annotations(image),
        'point_gen_method_synced':
            image.point_generation_method
            == source.default_point_generation_method,
        'annotation_area_synced':
            image.metadata.annotation_area == source.image_annotation_area,
    })


@image_permission_required('image_id', perm=Source.PermTypes.EDIT.code)
def image_detail_edit(request, image_id):
    """
    Edit image details.
    """

    image = get_object_or_404(Image, id=image_id)
    source = image.source
    metadata = image.metadata

    if request.method == 'POST':

        # Cancel
        cancel = request.POST.get('cancel', None)
        if cancel:
            messages.success(request, 'Edit cancelled.')
            return HttpResponseRedirect(reverse('image_detail', args=[image.id]))

        # Submit
        metadata_form = MetadataFormForDetailEdit(
            request.POST, instance=metadata, source=source)

        if metadata_form.is_valid():
            editedMetadata = metadata_form.instance
            editedMetadata.save()
            messages.success(request, 'Image successfully edited.')
            return HttpResponseRedirect(reverse('image_detail', args=[image.id]))
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        # Just reached this form page
        metadata_form = MetadataFormForDetailEdit(
            instance=metadata, source=source)

    return render(request, 'images/image_detail_edit.html', {
        'source': source,
        'image': image,
        'metadata_form': metadata_form,
    })


@image_permission_required('image_id', perm=Source.PermTypes.EDIT.code)
@require_POST
def image_delete(request, image_id):
    """
    Delete a single image.
    """
    image = get_object_or_404(Image, id=image_id)

    image_name = image.metadata.name
    source_id = image.source_id
    utils.delete_image(image)

    messages.success(request, 'Successfully deleted image ' + image_name + '.')
    return HttpResponseRedirect(reverse('source_main', args=[source_id]))


@image_permission_required('image_id', perm=Source.PermTypes.EDIT.code)
@require_POST
def image_delete_annotations(request, image_id):
    """
    Delete an image's annotations.
    """
    image = get_object_or_404(Image, id=image_id)

    Annotation.objects.filter(image=image).delete()

    messages.success(
        request, 'Successfully removed all annotations from this image.')
    return HttpResponseRedirect(reverse('image_detail', args=[image_id]))


@image_permission_required('image_id', perm=Source.PermTypes.EDIT.code)
@image_annotation_area_must_be_editable('image_id')
@require_POST
def image_regenerate_points(request, image_id):
    """
    Regenerate an image's point locations, using the image's current
    point generation method and annotation area.
    """
    image = get_object_or_404(Image, id=image_id)

    utils.generate_points(image, usesourcemethod=False)

    reset_features(image)

    messages.success(request, 'Successfully regenerated point locations.')
    return HttpResponseRedirect(reverse('image_detail', args=[image_id]))


@image_permission_required('image_id', perm=Source.PermTypes.EDIT.code)
@image_annotation_area_must_be_editable('image_id')
@require_POST
def image_reset_point_generation_method(request, image_id):
    """
    Reset an image's point generation method to the source's default.
    This regenerates the image's points as well.
    """
    image = get_object_or_404(Image, id=image_id)

    image.point_generation_method = \
        image.source.default_point_generation_method
    image.save()
    utils.generate_points(image, usesourcemethod=False)

    reset_features(image)

    messages.success(
        request, 'Reset image point generation method to source default.')
    return HttpResponseRedirect(reverse('image_detail', args=[image_id]))


@image_permission_required('image_id', perm=Source.PermTypes.EDIT.code)
@image_annotation_area_must_be_editable('image_id')
@require_POST
def image_reset_annotation_area(request, image_id):
    """
    Reset an image's annotation area to the source's default.
    This regenerates the image's points as well.
    """
    image = get_object_or_404(Image, id=image_id)

    image.metadata.annotation_area = image.source.image_annotation_area
    image.metadata.save()
    utils.generate_points(image, usesourcemethod=False)

    reset_features(image)

    messages.success(request, 'Reset annotation area to source default.')
    return HttpResponseRedirect(reverse('image_detail', args=[image_id]))


def import_groups(request, fileLocation):
    """
    Create label groups through a text file.
    NOTE: This method might be obsolete.
    """
    file = open(fileLocation, 'r') #opens the file for reading
    for line in file:
        line = line.replace("; ", ';')
        words = line.split(';')

        #creates a label object and stores it in the database
        group = LabelGroup(name=words[0], code=words[1])
        group.save()
    file.close()
