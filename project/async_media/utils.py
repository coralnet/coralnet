import abc
import uuid

from django.conf import settings
from django.core.cache import cache
from django.core.files.storage import get_storage_class
from django.templatetags.static import static as to_static_path
from easy_thumbnails.files import get_thumbnailer

from jobs.models import Job
from jobs.utils import get_or_create_job, start_job
from visualization.utils import get_patch_path, get_patch_url
from .exceptions import MediaRequestDenied


class AsyncMediaItem(abc.ABC):
    """
    A requested media file, derived from an original file, set up to be
    generated asynchronously if it doesn't exist yet.
    These media can include image thumbnails and point patches.
    """

    @property
    def width(self):
        raise NotImplementedError

    @property
    def height(self):
        raise NotImplementedError

    @property
    def media_key(self):
        """
        Identifier for the media item. This should contain all the necessary
        info to identify the method of generation and the final filepath.
        """
        raise NotImplementedError

    @property
    def job_name(self):
        raise NotImplementedError

    @property
    def job_args(self):
        raise NotImplementedError

    def get_url(self):
        raise NotImplementedError

    @classmethod
    def from_media_key(cls, media_key):
        raise NotImplementedError


class AsyncThumbnail(AsyncMediaItem):

    def __init__(self, filepath, size):
        self.filepath = filepath
        self._width, self._height = size

    @property
    def width(self):
        return self._width

    @property
    def height(self):
        return self._height

    @property
    def media_key(self):
        return f'thumb:{self.filepath}:{self.width}:{self.height}'

    @property
    def job_name(self):
        return 'generate_thumbnail'

    @property
    def job_args(self):
        return self.filepath, self.width, self.height

    def get_url(self):
        # generate=False turns off synchronous (blocking) generation.
        thumbnail = get_thumbnailer(self.filepath).get_thumbnail(
            dict(size=(self.width, self.height)), generate=False)
        if thumbnail:
            return thumbnail.url
        else:
            return None

    @classmethod
    def from_media_key(cls, media_key):
        first_token, filepath, width, height = media_key.split(':')
        if first_token != 'thumb':
            raise ValueError("Not the expected first token.")
        return cls(filepath, (width, height))


class AsyncPatch(AsyncMediaItem):

    def __init__(self, point_id):
        self.point_id = point_id

    @property
    def width(self):
        return settings.LABELPATCH_NCOLS

    @property
    def height(self):
        return settings.LABELPATCH_NROWS

    @property
    def media_key(self):
        return f'point:{self.point_id}'

    @property
    def job_name(self):
        return 'generate_patch'

    @property
    def job_args(self):
        return (self.point_id,)

    def get_url(self):
        # Get the storage class, then get an instance of it.
        storage = get_storage_class()()
        # Check if patch exists for the point.
        patch_relative_path = get_patch_path(self.point_id)
        if storage.exists(patch_relative_path):
            return get_patch_url(self.point_id)
        else:
            return None

    @classmethod
    def from_media_key(cls, media_key):
        first_token, point_id = media_key.split(':')
        if first_token != 'point':
            raise ValueError("Not the expected first token.")
        return cls(point_id)


def async_media_factory(media_key):
    for media_item_cls in [AsyncThumbnail, AsyncPatch]:
        try:
            return media_item_cls.from_media_key(media_key)
        except ValueError:
            pass
    raise ValueError("Media key is not valid for any async media type.")


class AsyncMediaBatch:
    """
    A batch of async media items which was requested on a single page.

    We use the cache to track ongoing media requests.
    We don't use sessions so that anonymous users with cookies off are also
    supported.
    """

    # Considerations for this expiration time:
    # - Definitely be long enough to accommodate any reasonable page of
    #   async media.
    # - Be at least reasonably short so that there's still room for other types
    #   of cache entries.
    CACHE_EXPIRATION_SECONDS = 10*60

    def __init__(self, key):
        """
        Instead of calling this constructor directly, use create()
        or get_existing().
        """
        self.key = key

    @property
    def cache_key(self):
        return f'media_batch_{self.key}'

    @property
    def cache_entry(self):
        entry = cache.get(self.cache_key)
        if entry is None:
            # Expired, or a randomly guessed key
            raise MediaRequestDenied("Couldn't get cache entry.")
        return entry

    @property
    def media(self):
        """
        This is a dict from media keys to Job IDs (or None if no Job yet).
        """
        return self.cache_entry['media']

    def update_cache_entry(self, updated_entry):
        cache.set(
            self.cache_key,
            updated_entry,
            self.CACHE_EXPIRATION_SECONDS,
        )

    def update_media(self, updated_media):
        self.update_cache_entry(
            self.cache_entry | dict(media=updated_media))

    def add_media(self, media_item):
        self.update_media(self.media | {media_item.media_key: None})

    def start_media_generation(self, user):
        updated_media = dict()

        for media_key in self.media.keys():
            media_item = async_media_factory(media_key)

            job, created = get_or_create_job(
                media_item.job_name,
                *media_item.job_args,
                user=user,
            )
            if created:
                start_job(job)
            # Else, someone else happened to just request the same media.
            # So we'll just keep tabs on that existing job.

            updated_media[media_key] = job.pk

        self.update_media(updated_media)

    def check_media_jobs(self):
        job_ids = list(self.media.values())
        jobs = (
            Job.objects
            .filter(
                pk__in=job_ids,
                # Make sure this can't grab results of other job types.
                job_name__in=['generate_thumbnail', 'generate_patch'],
            )
            .values('pk', 'user_id', 'status', 'result_message')
        )
        jobs_by_id = {job['pk']: job for job in jobs}

        results = dict()

        for media_key, job_id in self.media.items():

            media_item = async_media_factory(media_key)

            not_found_result = to_static_path(
                f'img/placeholders/'
                f'media-image-not-found__'
                f'{media_item.width}x{media_item.height}.png')

            if job_id not in jobs_by_id:
                results[media_key] = not_found_result
                continue

            job = jobs_by_id[job_id]

            if job['status'] == Job.Status.FAILURE:
                results[media_key] = not_found_result
            elif job['status'] == Job.Status.SUCCESS:
                # result_message is the URL of the generated media.
                results[media_key] = job['result_message']
            # Else, not finished yet, so don't add to results.

        # Remove finished media from the media dict.
        self.update_media({
            k: v for k, v in self.media.items() if k not in results
        })

        return results

    @classmethod
    def create(cls, request):
        instance = cls(uuid.uuid4().hex)
        user_id = request.user.pk if request.user.is_authenticated else None
        instance.update_cache_entry(
            dict(user_id=user_id, media=dict()))
        return instance

    @classmethod
    def get_existing(cls, key, request):
        instance = cls(key)
        user_id = request.user.pk if request.user.is_authenticated else None
        if user_id != instance.cache_entry['user_id']:
            raise MediaRequestDenied("Wrong user.")
        return instance
