import datetime

from django.urls import reverse
from django.utils import timezone

from images.models import Image, Metadata
from lib.tests.utils import BasePermissionTest
from sources.models import Source
from vision_backend.models import Features
from .utils import BaseBrowseActionTest, BrowseActionsFormTest


tz = timezone.get_current_timezone()


class PermissionTest(BasePermissionTest):
    """
    Test view permissions.
    """
    def test_browse_delete_ajax(self):
        url = reverse('browse_delete_ajax', args=[self.source.pk])

        self.source_to_private()
        self.assertPermissionLevel(
            url, self.SOURCE_EDIT, is_json=True, post_data={})
        self.source_to_public()
        self.assertPermissionLevel(
            url, self.SOURCE_EDIT, is_json=True, post_data={})


class BaseDeleteTest(BaseBrowseActionTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.url = reverse('browse_delete_ajax', args=[cls.source.pk])

    def assert_image_deleted(self, image_id, name):
        msg = f"Image {name} should be deleted"
        with self.assertRaises(Image.DoesNotExist, msg=msg):
            Image.objects.get(pk=image_id)

    @staticmethod
    def assert_image_not_deleted(image_id, name):
        try:
            Image.objects.get(pk=image_id)
        except Image.DoesNotExist:
            raise AssertionError(f"Image {name} should not be deleted")

    def assert_metadata_deleted(self, metadata_id, name):
        with self.assertRaises(
            Metadata.DoesNotExist,
            msg=f"Should have deleted metadata for {name}",
        ):
            Metadata.objects.get(pk=metadata_id)

    @staticmethod
    def assert_metadata_not_deleted(metadata_id, name):
        try:
            Metadata.objects.get(pk=metadata_id)
        except Metadata.DoesNotExist:
            raise AssertionError(
                f"Should not have deleted metadata for {name}")

    def assert_features_deleted(self, features_id, name):
        with self.assertRaises(
            Features.DoesNotExist,
            msg=f"Should have deleted features for {name}",
        ):
            Features.objects.get(pk=features_id)

    @staticmethod
    def assert_features_not_deleted(features_id, name):
        try:
            Features.objects.get(pk=features_id)
        except Features.DoesNotExist:
            raise AssertionError(
                f"Should not have deleted features for {name}")

    def assert_confirmation_message(self, count):
        """
        Call this after a successful deletion to check the top-of-page
        confirmation message.
        """
        browse_url = reverse('browse_images', args=[self.source.pk])
        self.client.force_login(self.user)
        response = self.client.get(browse_url)
        self.assertContains(
            response,
            f"The {count} selected images have been deleted.")

    def submit_and_assert_deletion(
        self, post_data: dict,
        expected_deleted: list = None,
    ):
        """
        - Submits the given post data to the delete view.
        - Asserts that the given images were deleted. (And their
          associated Metadata and Features)
        - Asserts that all members of self.images *besides* the given
          ones were *not* deleted. (Same with associated Metadata and
          Features)
        - Asserts that the expected confirmation message is present
          on the next page load.
        - Returns the response so the caller can do further checks.
        """
        if expected_deleted is None:
            expected_deleted = []
        expected_deleted = [
            dict(
                image_id=image.pk,
                name=image.metadata.name,
                metadata_id=image.metadata.pk,
                features_id=image.features.pk,
            )
            for image in expected_deleted
        ]
        expected_deleted_ids = [d['image_id'] for d in expected_deleted]

        expected_not_deleted = [
            image for image in self.images
            if image.pk not in expected_deleted_ids
        ]
        expected_not_deleted = [
            dict(
                image_id=image.pk,
                name=image.metadata.name,
                metadata_id=image.metadata.pk,
                features_id=image.features.pk,
            )
            for image in expected_not_deleted
        ]

        response = self.submit_action(**post_data)

        for d in expected_deleted:
            self.assert_image_deleted(d['image_id'], d['name'])
            self.assert_metadata_deleted(d['metadata_id'], d['name'])
            self.assert_features_deleted(d['features_id'], d['name'])

        for d in expected_not_deleted:
            self.assert_image_not_deleted(d['image_id'], d['name'])
            self.assert_metadata_not_deleted(d['metadata_id'], d['name'])
            self.assert_features_not_deleted(d['features_id'], d['name'])

        self.assert_confirmation_message(count=len(expected_deleted))

        return response


class FormAvailabilityTest(BrowseActionsFormTest):
    form_id = 'delete-images-ajax-form'

    def test_no_search(self):
        self.client.force_login(self.user)
        response = self.client.get(self.browse_url)
        self.assert_form_placeholdered(
            response,
            "You must first submit the Search form before you can batch-delete images. (This is a safety check to reduce the chances of accidentally deleting all your images. If you really want to delete all images, just click Search without changing any of the search fields.)",
        )

    def test_after_search(self):
        self.client.force_login(self.user)
        response = self.client.get(
            self.browse_url, self.default_search_params)
        self.assert_form_available(response)

    def test_view_perms_only(self):
        self.client.force_login(self.user_viewer)
        response = self.client.get(
            self.browse_url, self.default_search_params)
        self.assert_form_absent(response)


class SuccessTest(BaseDeleteTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.img1, cls.img2, cls.img3, cls.img4, cls.img5 = cls.images

        # Allow assertion messages to refer to the images by name.
        cls.update_multiple_metadatas(
            'name',
            ['img1', 'img2', 'img3', 'img4', 'img5']
        )

    def test_delete_all_images(self):
        """
        Delete all images in the source.
        """
        response = self.submit_and_assert_deletion(
            self.default_search_params,
            self.images,
        )
        self.assertDictEqual(response.json(), dict(success=True))

    # Specific filters.
    # These filters should already be tested more thoroughly in
    # test_browse_images.py or test_edit_metadata.py.

    def test_filter_by_aux1(self):
        self.update_multiple_metadatas(
            'aux1',
            [(self.img1, 'Site1'),
             (self.img2, 'Site3'),
             (self.img3, 'Site3')])

        response = self.submit_and_assert_deletion(
            dict(aux1='Site3'),
            [self.img2, self.img3],
        )
        self.assertDictEqual(response.json(), dict(success=True))

    def test_filter_by_annotation_status_confirmed(self):
        robot = self.create_robot(self.source)
        # 2 points per image
        # confirmed, confirmed, unconfirmed, partial
        self.add_annotations(self.user, self.img1, {1: 'A', 2: 'B'})
        self.add_annotations(self.user, self.img2, {1: 'B', 2: 'A'})
        self.add_robot_annotations(robot, self.img3)
        self.add_annotations(self.user, self.img4, {1: 'B'})

        response = self.submit_and_assert_deletion(
            dict(annotation_status='confirmed'),
            [self.img1, self.img2],
        )
        self.assertDictEqual(response.json(), dict(success=True))

    def test_filter_by_photo_date_year(self):
        self.update_multiple_metadatas(
            'photo_date',
            [(self.img1, datetime.date(2011, 12, 28)),
             (self.img2, datetime.date(2012, 1, 13)),
             (self.img3, datetime.date(2012, 8, 4))])

        response = self.submit_and_assert_deletion(
            dict(photo_date_0='year', photo_date_1=2012),
            [self.img2, self.img3],
        )
        self.assertDictEqual(response.json(), dict(success=True))

    def test_filter_by_annotation_date_range(self):
        # The given range should be included from day 1 00:00 to day n+1 00:00.
        self.set_last_annotation(
            self.img1, dt=datetime.datetime(2012, 3, 9, 23, 59, tzinfo=tz))
        self.set_last_annotation(
            self.img2, dt=datetime.datetime(2012, 3, 10, 0, 0, tzinfo=tz))
        self.set_last_annotation(
            self.img3, dt=datetime.datetime(2012, 3, 15, 12, 34, tzinfo=tz))
        self.set_last_annotation(
            self.img4, dt=datetime.datetime(2012, 3, 20, 23, 59, tzinfo=tz))
        self.set_last_annotation(
            self.img5, dt=datetime.datetime(2012, 3, 21, 0, 1, tzinfo=tz))

        response = self.submit_and_assert_deletion(
            dict(
                last_annotated_0='date_range',
                last_annotated_3=datetime.date(2012, 3, 10),
                last_annotated_4=datetime.date(2012, 3, 20),
            ),
            [self.img2, self.img3, self.img4],
        )
        self.assertDictEqual(response.json(), dict(success=True))

    def test_filter_by_annotator_tool_specific_user(self):
        self.add_annotations(self.user, self.img1, {1: 'A', 2: 'B'})

        user2 = self.create_user()
        self.add_source_member(
            self.user, self.source, user2, Source.PermTypes.EDIT.code)
        self.add_annotations(user2, self.img2, {1: 'A', 2: 'B'})

        response = self.submit_and_assert_deletion(
            dict(
                last_annotator_0='annotation_tool',
                last_annotator_1=user2.pk,
            ),
            [self.img2],
        )
        self.assertDictEqual(response.json(), dict(success=True))

    def test_filter_by_image_id_list(self):
        response = self.submit_and_assert_deletion(
            dict(image_id_list=f'{self.img2.pk}_{self.img3.pk}'
                               f'_{self.img5.pk}'),
            [self.img2, self.img3, self.img5],
        )
        self.assertDictEqual(response.json(), dict(success=True))


class OtherSourceTest(BaseDeleteTest):
    """
    Ensure that the view doesn't allow deleting other sources' images.

    These tests are a bit more verbose/explicit since there aren't
    many cases to test, and since having correct logic here is
    especially important.
    """
    setup_image_count = 2

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.s1_image1 = cls.images[0]
        cls.s1_image2 = cls.images[1]
        source2 = cls.create_source(cls.user)
        cls.s2_image1 = cls.upload_image(cls.user, source2)
        cls.s2_image2 = cls.upload_image(cls.user, source2)

    def test_dont_delete_other_sources_images_via_search_form(self):
        """
        Sanity check that the search form only picks up images in the current
        source.
        """
        response = self.submit_action(**self.default_search_params)
        self.assertDictEqual(response.json(), dict(success=True))

        self.assert_image_deleted(self.s1_image1.pk, "s1_image1")
        self.assert_image_deleted(self.s1_image2.pk, "s1_image2")

        self.assert_image_not_deleted(self.s2_image1.pk, "s2_image1")
        self.assert_image_not_deleted(self.s2_image2.pk, "s2_image2")
        self.assert_metadata_not_deleted(
            self.s2_image1.metadata.pk, "s2_image1")
        self.assert_metadata_not_deleted(
            self.s2_image2.metadata.pk, "s2_image2")
        self.assert_features_not_deleted(
            self.s2_image1.features.pk, "s2_image1")
        self.assert_features_not_deleted(
            self.s2_image2.features.pk, "s2_image2")

    def test_dont_delete_other_sources_images_via_ids(self):
        """
        Sanity check that specifying by IDs only accepts images in the current
        source.
        """
        response = self.submit_action(
            image_id_list='_'.join([str(self.s1_image1.pk), str(self.s2_image2.pk)])
        )
        self.assertDictEqual(response.json(), dict(success=True))

        self.assert_image_deleted(self.s1_image1.pk, "s1_image1")

        self.assert_image_not_deleted(self.s2_image2.pk, "s2_image2")
        self.assert_metadata_not_deleted(
            self.s2_image2.metadata.pk, "s2_image2")
        self.assert_features_not_deleted(
            self.s2_image2.features.pk, "s2_image2")


class ErrorTest(BaseDeleteTest):

    setup_image_count = 3

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.img1, cls.img2, cls.img3 = cls.images

    def test_no_search_form(self):
        response = self.submit_action()
        self.assertDictEqual(response.json(), dict(
            error=(
                "You must first use the search form or select images on the"
                " page to use the delete function. If you really want to"
                " delete all images, first click 'Search' without"
                " changing any of the search fields."
            )
        ))

        self.assert_image_not_deleted(self.img1.pk, "img1")
        self.assert_image_not_deleted(self.img2.pk, "img2")
        self.assert_image_not_deleted(self.img3.pk, "img3")

    def test_form_error(self):
        response = self.submit_action(annotation_status='invalid_value')

        self.assertDictEqual(response.json(), dict(
            error=(
                "There was an error with the form."
                " Nothing was deleted."
            )
        ))

        self.assert_image_not_deleted(self.img1.pk, "img1")
        self.assert_image_not_deleted(self.img2.pk, "img2")
        self.assert_image_not_deleted(self.img3.pk, "img3")
