import datetime
import time
from unittest import skipIf
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
import urllib.request

from django.conf import settings
from django.core.cache import cache
from django.core.files.storage import default_storage
from django.test import override_settings
from easy_thumbnails.files import get_thumbnailer
# `from easy_thumbnails.storage import <something>` seems to have potential
# for issues with import timing/ordering, because that module calls
# get_storage() at the global level. So we import this way instead.
import easy_thumbnails.storage

from jobs.models import Job
from jobs.utils import full_job
from ..middleware import ViewScopedCacheMiddleware
from ..storage_backends import StorageManagerLocal
from ..utils import (
    CacheableValue,
    context_scoped_cache,
    scoped_cache_context_var,
)
from .utils import BaseTest, ClientTest
from .utils_data import sample_image_as_file


class TestSettingsStorageTest(BaseTest):
    """
    Test the file storage settings logic used during unit tests.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.thumbnail_storage = \
            easy_thumbnails.storage.thumbnail_default_storage

        default_storage.save('1.png', sample_image_as_file('1.png'))
        default_storage.save('2.png', sample_image_as_file('2.png'))

        cls.generate_thumbnail('1.png')
        cls.generate_thumbnail('2.png')

    @staticmethod
    def generate_thumbnail(original_filepath):
        get_thumbnailer(original_filepath).get_thumbnail(
            dict(size=(40, 40)), generate=True)

    def test_storage_locations(self):
        # Should be using a temporary directory.
        self.assertTrue(
            'tmp' in default_storage.location
            or 'temp' in default_storage.location)

        # Same for easy-thumbnails storage.
        self.assertTrue(
            'tmp' in self.thumbnail_storage.location
            or 'temp' in self.thumbnail_storage.location)

        # And they should be the same. Same location + both local or both S3.
        self.assertEqual(
            default_storage.location, self.thumbnail_storage.location)
        self.assertEqual(
            default_storage.__class__, self.thumbnail_storage.__class__)

    def test_add_file(self):
        default_storage.save('3.png', sample_image_as_file('3.png'))

        # Files added from setUpTestData(), plus the file added just now,
        # should all be present.
        # And if test_delete_file() ran before this, that shouldn't affect
        # the result.
        self.assertTrue(default_storage.exists('1.png'))
        self.assertTrue(default_storage.exists('2.png'))
        self.assertTrue(default_storage.exists('3.png'))

    def test_add_file_check_thumbnail(self):
        """
        Thumbnail-storage equivalent of test_add_file().
        """
        default_storage.save('3.png', sample_image_as_file('3.png'))
        self.generate_thumbnail('3.png')

        self.assertTrue(
            self.thumbnail_storage.exists('1.png.40x40_q85.jpg'))
        self.assertTrue(
            self.thumbnail_storage.exists('2.png.40x40_q85.jpg'))
        self.assertTrue(
            self.thumbnail_storage.exists('3.png.40x40_q85.jpg'))

    def test_delete_file(self):
        default_storage.delete('1.png')

        # Files added from setUpTestData(), except the file deleted just now,
        # should be present.
        # And if test_add_file() ran before this, that shouldn't affect
        # the result.
        self.assertFalse(default_storage.exists('1.png'))
        self.assertTrue(default_storage.exists('2.png'))
        self.assertFalse(default_storage.exists('3.png'))

    def test_delete_thumbnail(self):
        """
        Thumbnail-storage equivalent of test_delete_file().
        """
        self.thumbnail_storage.delete('1.png.40x40_q85.jpg')

        self.assertFalse(
            self.thumbnail_storage.exists('1.png.40x40_q85.jpg'))
        self.assertTrue(
            self.thumbnail_storage.exists('2.png.40x40_q85.jpg'))
        self.assertFalse(
            self.thumbnail_storage.exists('3.png.40x40_q85.jpg'))


@skipIf(
    not settings.STORAGES['default']['BACKEND']
        == 'lib.storage_backends.MediaStorageS3',
    "Requires S3 storage")
class S3UrlAccessTest(ClientTest):
    """
    Test accessing uploaded S3 objects by URL.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)

        # Upload an image using django-storages + boto.
        cls.img = cls.upload_image(
            cls.user, cls.source, image_options=dict(filename='1.png'))

    def assert_forbidden(self, url, msg):
        with self.assertRaises(HTTPError) as cm:
            urllib.request.urlopen(url)
        self.assertEqual(cm.exception.code, 403, msg)

    def test_image_url_query_args(self):
        url = self.img.original_file.url
        current_timestamp = datetime.datetime.now().timestamp()
        query_string = urlsplit(url).query
        query_args = parse_qs(query_string)

        self.assertIn('AWSAccessKeyId', query_args, "Should have an access key")
        self.assertIn('Expires', query_args, "Should have an expire time")
        self.assertIn('Signature', query_args, "Should have a signature")

        expire_timestamp = int(query_args['Expires'][0])
        self.assertGreaterEqual(
            expire_timestamp, current_timestamp + 3300,
            "Expire time should be about 1 hour into the future")
        self.assertLessEqual(
            expire_timestamp, current_timestamp + 3900,
            "Expire time should be about 1 hour into the future")

    def test_image_url_allowed_access(self):
        url = self.img.original_file.url
        base_url = urlunsplit(urlsplit(url)._replace(query=''))
        query_string = urlsplit(url).query
        query_args = parse_qs(query_string)

        response = urllib.request.urlopen(url)
        self.assertEqual(
            response.status, 200, "Getting the URL should work")
        self.assertEqual(
            response.headers['Content-Type'], 'image/png',
            "URL response should have the expected content type")

        alt_query_args = query_args.copy()
        alt_query_args.pop('AWSAccessKeyId')
        self.assert_forbidden(
            base_url + '?' + urlencode(alt_query_args),
            "Getting the URL without the access key shouldn't work")

        alt_query_args = query_args.copy()
        alt_query_args.pop('Expires')
        self.assert_forbidden(
            base_url + '?' + urlencode(alt_query_args),
            "Getting the URL without the expire time shouldn't work")

        alt_query_args = query_args.copy()
        alt_query_args.pop('Signature')
        self.assert_forbidden(
            base_url + '?' + urlencode(alt_query_args),
            "Getting the URL without the signature shouldn't work")

        self.assert_forbidden(
            base_url,
            "Getting the URL without any query args shouldn't work")

        alt_query_args = query_args.copy()
        alt_query_args['AWSAccessKeyId'][0] = \
            alt_query_args['AWSAccessKeyId'][0].replace(
                alt_query_args['AWSAccessKeyId'][0][5], 'X')
        self.assert_forbidden(
            base_url + '?' + urlencode(alt_query_args),
            "Getting the URL with a modified access key shouldn't work")

        alt_query_args = query_args.copy()
        alt_query_args['Expires'][0] = \
            alt_query_args['Expires'][0].replace(
                alt_query_args['Expires'][0][5], '0')
        self.assert_forbidden(
            base_url + '?' + urlencode(alt_query_args),
            "Getting the URL with a modified expire time shouldn't work")

        alt_query_args = query_args.copy()
        alt_query_args['Signature'][0] = \
            alt_query_args['Signature'][0].replace(
                alt_query_args['Signature'][0][5], 'X')
        self.assert_forbidden(
            base_url + '?' + urlencode(alt_query_args),
            "Getting the URL with a modified signature shouldn't work")


class CacheTest(BaseTest):

    def test_cull_expired_items_on_set(self):
        """
        Unlike Django's FileBasedCache, DiskCache should cull expired cache
        entries (in the same shard) when any other entry is set.
        """
        storage_manager = StorageManagerLocal()
        cache_dir = storage_manager.create_temp_dir()

        with override_settings(CACHES={
            'default': {
                'BACKEND': 'diskcache.DjangoCache',
                'LOCATION': cache_dir,
                # No partitioning of data so that eviction logic is easy to
                # reason about.
                'SHARDS': 1,
                'DATABASE_TIMEOUT': 0.5,
            }
        }):
            # Set a key that expires in 1 second.
            cache.set(key='key1', value='1', timeout=1)
            # Wait 2 seconds.
            time.sleep(2)
            # Setting any value should make the DiskCache backend look for
            # expired entries to cull (within the same shard).
            cache.set(key='key2', value='2', timeout=1000)

            # expire() is part of the DiskCache backend. It removes expired
            # items from the cache, and returns the number of items removed.
            num_items_removed = cache.expire()
            self.assertEqual(
                num_items_removed, 0,
                msg=f"{num_items_removed} item(s) removed. This shouldn't"
                    f" remove any items, because key1 should already"
                    f" have been evicted when setting key2",
            )

        storage_manager.remove_temp_dir(cache_dir)


class ContextScopedCacheTest(ClientTest):

    def test_scope_not_active(self):
        self.assertIsNone(
            scoped_cache_context_var.get(),
            msg="Cache is not initialized,"
                " but access should return None instead of crashing")

    def test_middleware_active(self):
        def view(_request):
            self.assertIsNotNone(
                scoped_cache_context_var.get(),
                msg="Cache should be initialized")
            return 'response'
        ViewScopedCacheMiddleware(view)('request')

    def test_task_active(self):
        @full_job()
        def job_example():
            self.assertIsNotNone(
                scoped_cache_context_var.get(),
                msg="Cache should be initialized")
            return "Result message"

        job_example()

        job = Job.objects.latest('pk')
        self.assertEqual(
            job.result_message, "Result message", msg="Job shouldn't crash")

    def test_decorator_active(self):
        @context_scoped_cache()
        def func():
            self.assertIsNotNone(
                scoped_cache_context_var.get(),
                msg="Cache should be initialized")

        func()

    def test_cache_usage(self):
        computed_value = 1

        def compute():
            return computed_value

        cacheable_value = CacheableValue(
            cache_key='key',
            compute_function=compute,
            cache_update_interval=60*60,
            cache_timeout_interval=60*60,
            use_context_scoped_cache=True,
        )

        def view(_request):
            self.assertEqual(cacheable_value.get(), 1)
            return 'response'
        ViewScopedCacheMiddleware(view)('request')

        computed_value = 2
        self.assertEqual(compute(), 2, "This var scoping should work")

        def view(_request):
            # Django cache and view-scoped cache still have the old value
            self.assertEqual(cache.get(cacheable_value.cache_key), 1)
            self.assertEqual(cacheable_value.get(), 1)

            # Django cache is updated; view-scoped cache still has old value
            cache.set(cacheable_value.cache_key, compute())
            self.assertEqual(cache.get(cacheable_value.cache_key), 2)
            self.assertEqual(cacheable_value.get(), 1)

            # Both caches are updated
            cacheable_value.update()
            self.assertEqual(cache.get(cacheable_value.cache_key), 2)
            self.assertEqual(cacheable_value.get(), 2)

            return 'response'
        ViewScopedCacheMiddleware(view)('request')

    def test_value_not_cached_in_next_view(self):
        computed_value = 1

        def compute():
            return computed_value

        cacheable_value = CacheableValue(
            cache_key='key',
            compute_function=compute,
            cache_update_interval=60*60,
            cache_timeout_interval=60*60,
            use_context_scoped_cache=True,
        )
        with context_scoped_cache():
            cacheable_value.update()

        computed_value = 2

        def view(_request):
            # Django cache and view-scoped cache still have the old value
            self.assertEqual(cache.get(cacheable_value.cache_key), 1)
            self.assertEqual(cacheable_value.get(), 1)

            # Django cache is updated; view-scoped cache still has old value
            cache.set(cacheable_value.cache_key, compute())
            self.assertEqual(cache.get(cacheable_value.cache_key), 2)
            self.assertEqual(cacheable_value.get(), 1)

            return 'response'
        ViewScopedCacheMiddleware(view)('request')

        def view(_request):
            # View-scoped cache is updated because a new view has started
            self.assertEqual(cache.get(cacheable_value.cache_key), 2)
            self.assertEqual(cacheable_value.get(), 2)

            return 'response'
        ViewScopedCacheMiddleware(view)('request')
