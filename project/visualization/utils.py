from functools import reduce
from io import BytesIO
import operator
import re

from PIL import Image as PILImage
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage
from django.db.models import Q
import django.db.models.fields as model_fields

from accounts.utils import get_alleviate_user, get_imported_user, get_robot_user
from images.models import Metadata

User = get_user_model()


def image_search_kwargs_to_queryset(search_kwargs, source):
    # Q objects which will be ANDed together at the end
    qs = []

    # Multi-value fields already have the search kwargs passed in
    for field_name in ['photo_date', 'last_annotated', 'last_annotator']:
        field_kwargs = search_kwargs.get(field_name, None)
        if field_kwargs:
            qs.append(Q(**field_kwargs))

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
            if isinstance(Metadata._meta.get_field(field_name),
                          model_fields.CharField):
                metadata_kwargs['metadata__' + field_name] = ''
            else:
                metadata_kwargs['metadata__' + field_name] = None
        else:
            # Filter by the given non-empty value (case insensitive)
            metadata_kwargs[f'metadata__{field_name}__iexact'] = value
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

    image_id_list = search_kwargs.get('image_id_list', '')
    if image_id_list == '':
        # Don't filter
        pass
    else:
        qs.append(Q(pk__in=image_id_list))

    image_id_range = search_kwargs.get('image_id_range', '')
    if image_id_range == '':
        # Don't filter
        pass
    else:
        min_id, max_id = image_id_range
        qs.append(Q(pk__gte=min_id, pk__lte=max_id))

    # Annotation status
    annotation_status = search_kwargs.get('annotation_status', '')
    if annotation_status == '':
        # Don't filter
        pass
    else:
        qs.append(Q(annoinfo__status=annotation_status))

    # AND all of the constraints so far, and remember to search within
    # the source
    image_results = source.image_set.filter(reduce(operator.and_, qs))

    # Sorting

    sort_method = search_kwargs.get('sort_method') or 'name'
    sort_direction = search_kwargs.get('sort_direction') or 'asc'

    # Add pk as a secondary key when needed to create an unambiguous ordering.
    # This secondary key slows down ordering, but the consistency is important
    # for things like prev/next links.
    if sort_method == 'photo_date':
        sort_fields = ['metadata__photo_date', 'pk']
    elif sort_method == 'last_annotation_date':
        sort_fields = ['annoinfo__last_annotation__annotation_date', 'pk']
    elif sort_method == 'name':
        # metadata__name is SUPPOSED to be unique for each image, but
        # occasionally it's not due to a bug (issue #251), so we also use pk.
        # TODO: Natural-sort by name.
        sort_fields = ['metadata__name', 'pk']
    else:
        # 'upload_date'
        sort_fields = ['pk']

    if sort_direction == 'asc':
        sort_keys = sort_fields
    else:
        # 'desc'
        sort_keys = ['-'+field for field in sort_fields]

    image_results = image_results.order_by(*sort_keys)

    return image_results


def get_annotation_tool_users(source):
    """
    Return a queryset of users who have made annotations using the annotation
    tool in the given source.
    """
    annotations = source.annotation_set.all()
    tool_annotations = annotations.exclude(
        user__in=[get_robot_user(), get_alleviate_user(), get_imported_user()])
    # Beware of changing this query; it's performance sensitive. Any changes
    # should be tried on a source with 100,000s of annotations.
    tool_user_pks = (
        tool_annotations.order_by('user')
        .values_list('user', flat=True)
        .distinct()
    )
    return User.objects.filter(pk__in=tool_user_pks).order_by('username')


def get_patch_path(point):
    return settings.POINT_PATCH_FILE_PATTERN.format(
        full_image_path=point.image.original_file.name,
        point_pk=point.pk,
    )


def get_patch_url(point):
    return default_storage.url(get_patch_path(point))


def generate_patch_if_doesnt_exist(point):
    """
    If this point doesn't have an image patch file yet, then
    generate one.
    :param point: Point object to generate a patch for
    :return: None
    """

    # Check if patch exists for the point
    patch_relative_path = get_patch_path(point)
    if default_storage.exists(patch_relative_path):
        return

    # Locate the image.
    image = point.image
    original_image_relative_path = image.original_file.name

    # Figure out the size to crop out of the original image. Base it on the
    # larger of the two image dimensions.
    approx_region_size = int(max(image.original_width, image.original_height)
                             * settings.LABELPATCH_SIZE_FRACTION)

    # Open the image file.
    with default_storage.open(
            original_image_relative_path) as original_image_file:

        # Load the image with Pillow.
        im = PILImage.open(original_image_file)

        # Convert to RGB, since the input may have an alpha (transparency)
        # channel, and we're saving the thumbnail as JPEG which doesn't
        # have alpha.
        im = im.convert('RGB')

    # Crop.
    # - Both CoralNet coordinates and Pillow coordinates start from 0 at the
    # top left.
    # https://pillow.readthedocs.io/en/stable/handbook/concepts.html#coordinate-system
    # - crop() includes the low bounds and excludes the high bounds, so we
    # add +1 to the high bounds so that the point ends up in the center of the
    # region, rather than a half-pixel off.
    # - The region is always odd-sized, and either equal to or 1 greater
    # than the approx_region_size.
    region = im.crop((
        point.column - (approx_region_size // 2),
        point.row - (approx_region_size // 2),
        point.column + (approx_region_size // 2) + 1,
        point.row + (approx_region_size // 2) + 1
    ))

    # Resize to the desired size for the final patch.
    region = region.resize((settings.LABELPATCH_NCOLS,
                            settings.LABELPATCH_NROWS))

    # Save the patch image.
    # First use Pillow's save() method on an IO stream
    # (so we don't have to create a temporary file).
    # Then save the image, using the path constructed earlier
    # and the contents of the stream.
    # This approach should work with both local and remote storage.
    with BytesIO() as stream:
        region.save(stream, 'JPEG')
        default_storage.save(patch_relative_path, stream)
