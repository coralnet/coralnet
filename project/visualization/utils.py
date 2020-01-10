from io import BytesIO
import operator
import re
import numpy as np

from django.conf import settings
from django.core.files.storage import get_storage_class
from django.db.models import Q
import django.db.models.fields as model_fields
from PIL import Image as PILImage
from images.models import Point, Image, Metadata


def image_search_kwargs_to_queryset(search_kwargs, source):
    # Q objects which will be ANDed together at the end
    qs = []

    # Date
    date_filter_kwargs = search_kwargs.get('date_filter', None)
    if date_filter_kwargs:
        qs.append(Q(**date_filter_kwargs))

    # Metadata fields
    metadata_kwargs = dict()
    metadata_field_names = [
        'aux1', 'aux2', 'aux3', 'aux4', 'aux5',
        'height_in_cm', 'latitude', 'longitude', 'depth',
        'camera', 'photographer', 'water_quality',
        'strobes', 'framing', 'balance',
    ]
    for field_name in metadata_field_names:
        value = search_kwargs.get(field_name, '')
        if value == '':
            # Don't filter by this field
            pass
        elif value == '(none)':
            # Get images with an empty value for this field
            if isinstance(
              Metadata._meta.get_field(field_name), model_fields.CharField):
                metadata_kwargs['metadata__' + field_name] = ''
            else:
                metadata_kwargs['metadata__' + field_name] = None
        else:
            # Filter by the given non-empty value
            metadata_kwargs['metadata__' + field_name] = value
    qs.append(Q(**metadata_kwargs))

    # Image-name search field; all punctuation is allowed
    search_value = search_kwargs.get('image_name', '')
    # Strip whitespace from both ends
    search_value = search_value.strip()
    # Replace multi-spaces with one space
    search_value = re.sub(r'\s{2,}', ' ', search_value)
    # Get space-separated tokens
    search_tokens = search_value.split(' ')
    # Discard blank tokens
    search_tokens = [t for t in search_tokens if t != '']
    # Require all tokens to be found
    for token in search_tokens:
        qs.append(Q(metadata__name__icontains=token))

    # Annotation status
    annotation_status = search_kwargs.get('annotation_status', '')
    if annotation_status == '':
        # Don't filter
        pass
    elif annotation_status == 'confirmed':
        qs.append(Q(confirmed=True))
    elif annotation_status == 'unconfirmed':
        qs.append(Q(confirmed=False))
        qs.append(Q(features__classified=True))
    elif annotation_status == 'unclassified':
        qs.append(Q(confirmed=False))
        qs.append(Q(features__classified=False))

    # AND all of the constraints so far, and remember to search within
    # the source
    image_results = Image.objects.filter(
        reduce(operator.and_, qs), source=source)

    return image_results


def get_patch_path(point_id):
    point = Point.objects.get(pk=point_id)

    return settings.POINT_PATCH_FILE_PATTERN.format(
        full_image_path=point.image.original_file.name,
        point_pk=point.pk,
    )


def get_patch_url(point_id):
    return get_storage_class()().url(get_patch_path(point_id))


def generate_patch_if_doesnt_exist(point_id):
    """
    If this point doesn't have an image patch file yet, then
    generate one.
    :param point_id: Primary key to point object to generate a patch for
    :return: None
    """

    # Get the storage class, then get an instance of it.
    storage = get_storage_class()()

    # Check if patch exists for the point
    patch_relative_path = get_patch_path(point_id)
    if storage.exists(patch_relative_path):
        return

    # Load image and convert to numpy array.
    point = Point.objects.get(pk=point_id)
    original_image_relative_path = point.image.original_file.name
    original_image_file = storage.open(original_image_relative_path)

    # Figure out the patch size to crop, and which to resize to.
    patch_size = int(max(point.image.original_width, point.image.original_height)
                     * settings.LABELPATCH_SIZE_FRACTION)

    # Load the image convert to RGB
    im = PILImage.open(original_image_file)
    im = im.convert('RGB')

    # Crop
    region = im.crop((
        point.column - patch_size // 2,
        point.row - patch_size // 2,
        point.column + patch_size // 2,
        point.row + patch_size // 2
    ))

    region = region.resize((settings.LABELPATCH_NCOLS,
                            settings.LABELPATCH_NROWS))

    # Save the image.
    # First use Pillow's save() method on an IO stream (so we don't have to create a temporary file).
    # Then save the image, using the path constructed earlier and the contents of the stream.
    # This approach should work with both local and remote storage.
    with BytesIO() as stream:
        region.save(stream, 'JPEG')
        storage.save(patch_relative_path, stream)
