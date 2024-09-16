from collections import defaultdict
import os
from unittest import skipIf
import warnings

from bs4 import BeautifulSoup
from django.conf import settings
from django.core.files.storage import default_storage
from django.test import override_settings
from django.urls import reverse
from easy_thumbnails.files import get_thumbnailer

from images.models import Point
from jobs.models import Job
from lib.tests.utils import BasePermissionTest, ClientTest
from visualization.utils import generate_patch_if_doesnt_exist, get_patch_url


class PermissionTest(BasePermissionTest):

    def test_start_media_generation_ajax(self):
        url = reverse('async_media:start_media_generation_ajax')

        self.assertPermissionLevel(
            url, self.SIGNED_OUT, is_json=True, post_data={})

    def test_media_poll_ajax(self):
        url = reverse('async_media:media_poll_ajax')

        self.assertPermissionLevel(
            url, self.SIGNED_OUT, is_json=True)


class AsyncMediaTest(ClientTest):

    browse_url: str

    def load_browse_and_get_media_keys(self) -> list[tuple[str, list[str]]]:
        thumb_images = self.load_browse_and_get_media()

        # This should mirror the keys that the Javascript code would
        # pick up, which means excluding blank ones.
        media_keys = defaultdict(list)
        for thumb_image in thumb_images:
            batch_key = thumb_image.attrs.get('data-media-batch-key')
            media_key = thumb_image.attrs.get('data-media-key')
            if media_key == '':
                continue
            media_keys[batch_key].append(media_key)
        return list(media_keys.items())

    def start_generation(self, batch_key):
        with self.captureOnCommitCallbacks(execute=True):
            data = dict(media_batch_key=batch_key)
            response = self.client.post(
                reverse('async_media:start_media_generation_ajax'), data=data)

        self.assertDictEqual(response.json(), dict(code='success'))

        return response


@skipIf(
    os.name == 'nt'
    and settings.STORAGES['default']['BACKEND']
        == 'lib.storage_backends.MediaStorageS3',
    "Fetching existing thumbnails doesn't work with Windows + S3, because"
    " easy-thumbnails uses os.path for storage path separators")
class ThumbnailsTest(AsyncMediaTest):
    """
    Test the thumbnail functionality in Browse Images.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.user_2 = cls.create_user()
        cls.source = cls.create_source(cls.user)
        cls.browse_url = reverse('browse_images', args=[cls.source.pk])

    def load_browse_and_get_media(self):
        response = self.client.get(self.browse_url)
        response_soup = BeautifulSoup(response.content, 'html.parser')
        return response_soup.find_all('img', class_='thumb')

    def assert_poll_results(self, batch_key, expected_media):
        # Retrieve generated thumbnails
        data = dict(media_batch_key=batch_key)
        response = self.client.get(
            reverse('async_media:media_poll_ajax'), data=data)

        # Determine expected JSON response
        media_results = dict()
        for media_key, image in expected_media:
            thumbnail = (
                get_thumbnailer(image.original_file)
                .get_thumbnail(dict(size=(150, 150)), generate=False)
            )
            self.assertIsNotNone(
                thumbnail, msg=f"Thumbnail for {image} should exist")
            media_results[media_key] = thumbnail.url
        expected_json = dict(mediaResults=media_results)

        self.assertDictEqual(
            response.json(),
            expected_json,
            msg="Expected poll results should have been retrieved")

    def test_load_existing_thumbnail(self):
        img = self.upload_image(self.user, self.source)

        # Generate thumbnail before loading browse page
        thumbnail = get_thumbnailer(img.original_file).get_thumbnail(
            dict(size=(150, 150)), generate=True)

        thumb_image = self.load_browse_and_get_media()[0]

        self.assertEqual(
            thumbnail.url, thumb_image.attrs.get('src'),
            msg="Existing thumbnail should be loaded on the browse page")
        self.assertEqual(
            '',
            thumb_image.attrs.get('data-media-key'),
            msg="Media key attribute should be blank")

    @override_settings(STATIC_URL='/static/')
    def test_generate_and_retrieve_thumbnail(self):
        img = self.upload_image(self.user, self.source)

        thumb_image = self.load_browse_and_get_media()[0]

        batch_key = thumb_image.attrs.get('data-media-batch-key')
        media_key = thumb_image.attrs.get('data-media-key')
        self.assertEqual(
            '/static/img/placeholders/media-loading__150x150.png',
            thumb_image.attrs.get('src'),
            msg="Browse page should show 'loading' thumbnail")
        self.assertNotEqual(
            '',
            media_key,
            msg="Media key attribute should not be blank")

        self.start_generation(batch_key)
        self.assert_poll_results(
            batch_key,
            [(media_key, img)],
        )

    def test_generate_multiple_thumbnails(self):
        img1 = self.upload_image(self.user, self.source)
        img2 = self.upload_image(self.user, self.source)

        batch_key, media_keys = self.load_browse_and_get_media_keys()[0]

        self.start_generation(batch_key)
        self.assert_poll_results(
            batch_key,
            zip(media_keys, [img1, img2]),
        )

    def test_generate_over_multiple_polls(self):
        img1 = self.upload_image(self.user, self.source)
        img2 = self.upload_image(self.user, self.source)
        img3 = self.upload_image(self.user, self.source)
        img4 = self.upload_image(self.user, self.source)

        # img1, img2, img4: generated on first poll; we'll fake img3's thumb
        # being not generated by reverting the Job status to in-progress.
        batch_key, media_keys = self.load_browse_and_get_media_keys()[0]
        self.start_generation(batch_key)
        img3_job = Job.objects.get(
            job_name='generate_thumbnail',
            arg_identifier=Job.args_to_identifier(
                [img3.original_file.name, 150, 150]))
        img3_job.status = Job.Status.IN_PROGRESS
        img3_job.save()

        self.assert_poll_results(
            batch_key,
            [(media_keys[0], img1),
             (media_keys[1], img2),
             (media_keys[3], img4)],
        )

        # img3: generated on second poll
        img3_job.status = Job.Status.SUCCESS
        img3_job.save()

        self.assert_poll_results(
            batch_key,
            [(media_keys[2], img3)],
        )

    def test_subset_already_generated(self):
        img1 = self.upload_image(self.user, self.source)
        img2 = self.upload_image(self.user, self.source)
        img3 = self.upload_image(self.user, self.source)

        # img1, img3: already generated before loading browse page
        get_thumbnailer(img1.original_file).get_thumbnail(
            dict(size=(150, 150)), generate=True)
        get_thumbnailer(img3.original_file).get_thumbnail(
            dict(size=(150, 150)), generate=True)

        batch_key, media_keys = self.load_browse_and_get_media_keys()[0]

        self.start_generation(batch_key)
        self.assert_poll_results(
            batch_key,
            zip(media_keys, [img2]),
        )

    def test_already_started_generating(self):
        img = self.upload_image(self.user, self.source)

        self.client.force_login(self.user_2)
        batch_key, media_keys = self.load_browse_and_get_media_keys()[0]

        # Start generation
        self.start_generation(batch_key)
        thumbnail = (
            get_thumbnailer(img.original_file)
            .get_thumbnail(dict(size=(150, 150)), generate=False)
        )

        # Try to start again
        data = dict(media_batch_key=batch_key)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse('async_media:start_media_generation_ajax'), data=data)
        self.assertDictEqual(
            response.json(),
            dict(
                code='already_started_generating',
                mediaResults={},
            ),
            msg="Shouldn't return any results since they weren't collected by"
                " a poll yet",
        )

        # Poll
        self.assert_poll_results(
            batch_key,
            zip(media_keys, [img]),
        )

        # Try to start again
        data = dict(media_batch_key=batch_key)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse('async_media:start_media_generation_ajax'), data=data)
        self.assertDictEqual(
            response.json(),
            dict(
                code='already_started_generating',
                mediaResults={media_keys[0]: thumbnail.url},
            ),
            msg="Should have results after the poll",
        )

    def test_logged_in_user_ok(self):
        """
        Most of these tests have been done logged out. Ensure logged in
        works too.
        """
        img = self.upload_image(self.user, self.source)

        self.client.force_login(self.user)
        batch_key, media_keys = self.load_browse_and_get_media_keys()[0]

        self.client.force_login(self.user)
        self.start_generation(batch_key)
        self.client.force_login(self.user)
        self.assert_poll_results(
            batch_key,
            zip(media_keys, [img]),
        )

    @override_settings(STATIC_URL='/static/')
    def test_original_image_not_found(self):
        img = self.upload_image(self.user, self.source)

        # Delete the original image file
        default_storage.delete(img.original_file.name)

        batch_key, media_keys = self.load_browse_and_get_media_keys()[0]

        # During the attempt at thumbnail generation, it'll get
        # `UserWarning: Could not import VIL for SVG image support: No
        # module named 'reportlab'.`
        with warnings.catch_warnings():
            # Ignore unpickling warnings from sklearn.
            warnings.filterwarnings(
                'ignore',
                category=UserWarning,
                message="Could not import VIL for SVG image support:"
                        " No module named 'reportlab'.",
            )
            self.start_generation(batch_key)

        # Retrieve generated thumbnails
        data = dict(media_batch_key=batch_key)
        response = self.client.get(
            reverse('async_media:media_poll_ajax'), data=data)

        expected_json = dict(mediaResults={
            media_keys[0]:
                '/static/img/placeholders/media-image-not-found__150x150.png',
        })
        self.assertDictEqual(
            response.json(),
            expected_json,
            msg="Not found image should result in the expected thumbnail")

    def test_batch_key_not_given(self):
        self.upload_image(self.user, self.source)

        self.load_browse_and_get_media()

        data = dict()
        response = self.client.post(
            reverse('async_media:start_media_generation_ajax'), data=data)
        self.assertDictEqual(
            response.json(), dict(error="No media batch key provided."))

    def test_nonexistent_batch_key(self):
        self.upload_image(self.user, self.source)

        self.load_browse_and_get_media()

        # This is guaranteed to not be an actual key because
        # generated keys are UUIDs.
        data = dict(media_batch_key='a_nonexistent_key')
        response = self.client.post(
            reverse('async_media:start_media_generation_ajax'), data=data)
        self.assertDictEqual(
            response.json(),
            dict(error="Media request denied: Couldn't get cache entry."))

    def test_start_generation_wrong_user(self):
        self.upload_image(self.user, self.source)

        self.client.force_login(self.user_2)
        batch_key, media_keys = self.load_browse_and_get_media_keys()[0]

        # Different user from the one who loaded browse
        self.client.force_login(self.user)
        data = dict(media_batch_key=batch_key)
        response = self.client.post(
            reverse('async_media:start_media_generation_ajax'), data=data)
        self.assertDictEqual(
            response.json(),
            dict(error="Media request denied: Wrong user."))

    def test_start_generation_anon_vs_registered(self):
        """
        Make sure that the user check doesn't break down with logged-out
        users for whatever reason.
        """
        self.upload_image(self.user, self.source)

        self.client.force_login(self.user)
        batch_key, media_keys = self.load_browse_and_get_media_keys()[0]

        self.client.logout()
        data = dict(media_batch_key=batch_key)
        response = self.client.post(
            reverse('async_media:start_media_generation_ajax'), data=data)
        self.assertDictEqual(
            response.json(),
            dict(error="Media request denied: Wrong user."))

    def test_job_doesnt_exist(self):
        img = self.upload_image(self.user, self.source)

        batch_key, media_keys = self.load_browse_and_get_media_keys()[0]
        self.start_generation(batch_key)

        job = Job.objects.get(
            job_name='generate_thumbnail',
            arg_identifier=Job.args_to_identifier(
                [img.original_file.name, 150, 150]))
        job.delete()

        data = dict(media_batch_key=batch_key)
        response = self.client.get(
            reverse('async_media:media_poll_ajax'), data=data)

        expected_json = dict(mediaResults={
            media_keys[0]:
                '/static/img/placeholders/media-image-not-found__150x150.png',
        })
        self.assertDictEqual(
            response.json(),
            expected_json,
            msg="Nonexistent job should result in not found thumbnail")

    def test_wrong_job_type(self):
        img = self.upload_image(self.user, self.source)

        batch_key, media_keys = self.load_browse_and_get_media_keys()[0]
        self.start_generation(batch_key)

        job = Job.objects.get(
            job_name='generate_thumbnail',
            arg_identifier=Job.args_to_identifier(
                [img.original_file.name, 150, 150]))
        job.job_name = 'other_job_name'
        job.save()

        data = dict(media_batch_key=batch_key)
        response = self.client.get(
            reverse('async_media:media_poll_ajax'), data=data)

        expected_json = dict(mediaResults={
            media_keys[0]:
                '/static/img/placeholders/media-image-not-found__150x150.png',
        })
        self.assertDictEqual(
            response.json(),
            expected_json,
            msg="Mismatched job type should result in not found thumbnail")

    def test_poll_wrong_user(self):
        self.upload_image(self.user, self.source)

        self.client.force_login(self.user_2)
        batch_key, media_keys = self.load_browse_and_get_media_keys()[0]
        self.client.force_login(self.user_2)
        self.start_generation(batch_key)

        # Different user
        self.client.force_login(self.user)
        data = dict(media_batch_key=batch_key)
        response = self.client.get(
            reverse('async_media:media_poll_ajax'), data=data)
        self.assertDictEqual(
            response.json(),
            dict(error="Media request denied: Wrong user."))

    def test_poll_anon_vs_registered(self):
        """
        Make sure that the user check doesn't break down with logged-out
        users for whatever reason.
        """
        self.upload_image(self.user, self.source)

        self.client.force_login(self.user)
        batch_key, media_keys = self.load_browse_and_get_media_keys()[0]
        self.client.force_login(self.user)
        self.start_generation(batch_key)

        self.client.logout()
        data = dict(media_batch_key=batch_key)
        response = self.client.get(
            reverse('async_media:media_poll_ajax'), data=data)
        self.assertDictEqual(
            response.json(),
            dict(error="Media request denied: Wrong user."))


class PatchesTest(AsyncMediaTest):
    """
    Test the thumbnail functionality in Browse Patches.
    """
    search_params = dict(
        image_form_type='search',
        aux1='', aux2='', aux3='', aux4='', aux5='',
        height_in_cm='', latitude='', longitude='', depth='',
        photographer='', framing='', balance='',
        photo_date_0='', photo_date_1='', photo_date_2='',
        photo_date_3='', photo_date_4='',
        image_name='',
        patch_annotation_status='', patch_label='',
        patch_annotation_date_0='', patch_annotation_date_1='',
        patch_annotation_date_2='', patch_annotation_date_3='',
        patch_annotation_date_4='',
        patch_annotator_0='', patch_annotator_1='',
    )

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.user_2 = cls.create_user()
        cls.source = cls.create_source(cls.user)
        labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, labels)
        cls.browse_url = reverse('browse_patches', args=[cls.source.pk])

    def load_browse_and_get_media(self):
        response = self.client.get(self.browse_url, data=self.search_params)
        response_soup = BeautifulSoup(response.content, 'html.parser')
        return response_soup.find_all('img', class_='thumb')

    def assert_poll_results(self, batch_key, expected_media):
        # Retrieve generated patches
        data = dict(media_batch_key=batch_key)
        response = self.client.get(
            reverse('async_media:media_poll_ajax'), data=data)

        # Determine expected JSON response
        media_results = dict()
        for media_key, point_number in expected_media:
            # This assumes there is only one annotated image in the test
            point = Point.objects.get(point_number=point_number)
            media_results[media_key] = get_patch_url(point.pk)
        expected_json = dict(mediaResults=media_results)

        self.assertDictEqual(
            response.json(),
            expected_json,
            msg="Expected poll results should have been retrieved")

    def test_load_existing_patch(self):
        img = self.upload_image(self.user, self.source)
        self.add_annotations(self.user, img, {1: 'A'})
        point_id = img.point_set.get(point_number=1).pk

        # Generate patch before loading browse page
        generate_patch_if_doesnt_exist(point_id)
        patch_url = get_patch_url(point_id)

        patch_image = self.load_browse_and_get_media()[0]

        self.assertEqual(
            patch_url, patch_image.attrs.get('src'),
            msg="Existing patch should be loaded on the browse page")
        self.assertEqual(
            '',
            patch_image.attrs.get('data-media-key'),
            msg="Media key attribute should be blank")

    @override_settings(STATIC_URL='/static/')
    def test_generate_and_retrieve_patch(self):
        img = self.upload_image(self.user, self.source)
        self.add_annotations(self.user, img, {1: 'A'})

        thumb_image = self.load_browse_and_get_media()[0]

        batch_key = thumb_image.attrs.get('data-media-batch-key')
        media_key = thumb_image.attrs.get('data-media-key')
        self.assertEqual(
            '/static/img/placeholders/media-loading__150x150.png',
            thumb_image.attrs.get('src'),
            msg="Browse page should show 'loading' thumbnail")
        self.assertNotEqual(
            '',
            media_key,
            msg="Media key attribute should not be blank")

        self.start_generation(batch_key)
        self.assert_poll_results(
            batch_key,
            [(media_key, 1)],
        )

    def test_generate_multiple_patches(self):
        img = self.upload_image(self.user, self.source)
        self.add_annotations(self.user, img, {1: 'A', 2: 'B'})

        batch_key, media_keys = self.load_browse_and_get_media_keys()[0]
        # Browse-patches ordering of patches is random. We'll sort them
        # by point number to make comparison easier.
        # Keys should be formatted as `point:<point pk>`, and point pks
        # should be in order of point number. So sorting by keys'
        # string content should sort by point number.
        media_keys.sort()

        self.start_generation(batch_key)
        self.assert_poll_results(
            batch_key,
            zip(media_keys, [1, 2]),
        )

    def test_generate_over_multiple_polls(self):
        img = self.upload_image(self.user, self.source)
        self.add_annotations(self.user, img, {1: 'A', 2: 'B', 3: 'B', 4: 'A'})

        # 1st, 2nd and 4th points (by the order they're listed in browse)
        # generated on first poll; we'll fake the 3rd's patch not being
        # generated by reverting the Job status to in-progress.
        batch_key, media_keys = self.load_browse_and_get_media_keys()[0]
        media_keys.sort()
        self.start_generation(batch_key)

        third_job = Job.objects.get(
            job_name='generate_patch',
            arg_identifier=Job.args_to_identifier([
                Point.objects.get(point_number=3).pk]),
        )
        third_job.status = Job.Status.IN_PROGRESS
        third_job.save()

        self.assert_poll_results(
            batch_key,
            [(media_keys[0], 1),
             (media_keys[1], 2),
             (media_keys[3], 4)],
        )

        # 3rd patch: generated on second poll
        third_job.status = Job.Status.SUCCESS
        third_job.save()

        self.assert_poll_results(
            batch_key,
            [(media_keys[2], 3)],
        )

    def test_subset_already_generated(self):
        img = self.upload_image(self.user, self.source)
        self.add_annotations(self.user, img, {1: 'A', 2: 'B', 3: 'B'})

        # Point numbers 1 and 3: already generated before loading browse page
        generate_patch_if_doesnt_exist(
            Point.objects.get(point_number=1).pk)
        generate_patch_if_doesnt_exist(
            Point.objects.get(point_number=3).pk)

        batch_key, media_keys = self.load_browse_and_get_media_keys()[0]

        self.start_generation(batch_key)
        self.assert_poll_results(
            batch_key,
            [(media_keys[0], 2)],
        )

    def test_logged_in_user_ok(self):
        img = self.upload_image(self.user, self.source)
        self.add_annotations(self.user, img, {1: 'A'})

        self.client.force_login(self.user)
        batch_key, media_keys = self.load_browse_and_get_media_keys()[0]

        self.client.force_login(self.user)
        self.start_generation(batch_key)
        self.client.force_login(self.user)
        self.assert_poll_results(
            batch_key,
            [(media_keys[0], 1)],
        )

    # Patch generation doesn't have a check for the original image not
    # being found.

    # Skipping missing / nonexistent batch key tests out of laziness/brevity.

    def test_start_generation_wrong_user(self):
        img = self.upload_image(self.user, self.source)
        self.add_annotations(self.user, img, {1: 'A'})

        self.client.force_login(self.user_2)
        batch_key, media_keys = self.load_browse_and_get_media_keys()[0]

        # Different user from the one who loaded browse
        self.client.force_login(self.user)
        data = dict(media_batch_key=batch_key)
        response = self.client.post(
            reverse('async_media:start_media_generation_ajax'), data=data)
        self.assertDictEqual(
            response.json(), dict(error="Media request denied: Wrong user."))

    # Skipping the anon vs. registered user test out of laziness/brevity.

    def test_job_doesnt_exist(self):
        img = self.upload_image(self.user, self.source)
        self.add_annotations(self.user, img, {1: 'A'})

        batch_key, media_keys = self.load_browse_and_get_media_keys()[0]
        self.start_generation(batch_key)

        job = Job.objects.get(
            job_name='generate_patch',
            arg_identifier=Job.args_to_identifier(
                [Point.objects.get(point_number=1).pk]))
        job.delete()

        data = dict(media_batch_key=batch_key)
        response = self.client.get(
            reverse('async_media:media_poll_ajax'), data=data)

        expected_json = dict(mediaResults={
            media_keys[0]:
                '/static/img/placeholders/media-image-not-found__150x150.png',
        })
        self.assertDictEqual(
            response.json(),
            expected_json,
            msg="Nonexistent job should result in not found thumbnail")

    def test_wrong_job_type(self):
        img = self.upload_image(self.user, self.source)
        self.add_annotations(self.user, img, {1: 'A'})

        batch_key, media_keys = self.load_browse_and_get_media_keys()[0]
        self.start_generation(batch_key)

        job = Job.objects.get(
            job_name='generate_patch',
            arg_identifier=Job.args_to_identifier(
                [Point.objects.get(point_number=1).pk]))
        job.job_name = 'other_job_name'
        job.save()

        data = dict(media_batch_key=batch_key)
        response = self.client.get(
            reverse('async_media:media_poll_ajax'), data=data)

        expected_json = dict(mediaResults={
            media_keys[0]:
                '/static/img/placeholders/media-image-not-found__150x150.png',
        })
        self.assertDictEqual(
            response.json(),
            expected_json,
            msg="Nonexistent job should result in not found thumbnail")

    def test_poll_wrong_user(self):
        img = self.upload_image(self.user, self.source)
        self.add_annotations(self.user, img, {1: 'A'})

        self.client.force_login(self.user_2)
        batch_key, media_keys = self.load_browse_and_get_media_keys()[0]
        self.client.force_login(self.user_2)
        self.start_generation(batch_key)

        # Different user
        self.client.force_login(self.user)
        data = dict(media_batch_key=batch_key)
        response = self.client.get(
            reverse('async_media:media_poll_ajax'), data=data)
        self.assertDictEqual(
            response.json(),
            dict(error="Media request denied: Wrong user."))

    # Skipping the anon vs. registered user test out of laziness/brevity.
