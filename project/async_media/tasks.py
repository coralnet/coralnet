import easy_thumbnails.exceptions as easy_thumbnails_exceptions
from easy_thumbnails.files import get_thumbnailer

from images.models import Point
from jobs.exceptions import JobError
from jobs.utils import job_runner
from visualization.utils import generate_patch_if_doesnt_exist, get_patch_url


@job_runner(task_queue_name='realtime')
def generate_thumbnail(original_filepath: str, width: int, height: int):
    """
    Generate an alternate-size version of a media image.
    """
    try:
        # Generate the thumbnail.
        thumbnail = get_thumbnailer(original_filepath).get_thumbnail(
            dict(size=(width, height)), generate=True)
    except easy_thumbnails_exceptions.InvalidImageFormatError:
        raise JobError(
            f"Couldn't load the original image. It may be not found, not a"
            f" supported format, or corrupt.")

    return thumbnail.url


@job_runner(task_queue_name='realtime')
def generate_patch(point_id: int):
    """
    Generate an image patch centered around an annotation point.
    """
    try:
        point = Point.objects.get(pk=point_id)
    except Point.DoesNotExist:
        raise JobError(f"Point {point_id} doesn't exist anymore.")

    generate_patch_if_doesnt_exist(point)
    return get_patch_url(point)
