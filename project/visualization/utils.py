from io import BytesIO

from PIL import Image as PILImage
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.storage import default_storage

from sources.models import Source

User = get_user_model()


def get_annotator_dropdown_choices(source):
    """
    Return a queryset of users who are admins/editors in the source.

    This may not necessarily include all who have made annotations using
    the annotation tool in the given source; there may be former members.
    However, it may be too expensive to do that lookup.
    TODO: Ensure that, if one really wanted to search for annotations of a
     former member, it'd still be possible by entering that user's ID in the
     URL query arg manually, instead of using this dropdown. The issue is
     that the validation on this field would currently make the whole form
     get an error if one tried that.
    """
    likely_annotator_ids = []
    for member in source.get_members():
        if member.has_perm(Source.PermTypes.EDIT.code, source):
            likely_annotator_ids.append(member.pk)
    return User.objects.filter(
        pk__in=likely_annotator_ids).order_by('username')


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
