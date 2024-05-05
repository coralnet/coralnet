from bs4 import BeautifulSoup
from django.urls import reverse

from jobs.tasks import run_scheduled_jobs_until_empty
from lib.tests.utils import BasePermissionTest, ClientTest
from vision_backend.tests.tasks.utils import (
    BaseTaskTest, do_collect_spacer_jobs)


class PermissionTest(BasePermissionTest):
    """
    Test view permissions.
    """
    def test_batch_delete_annotations_ajax(self):
        url = reverse('batch_delete_annotations_ajax', args=[self.source.pk])

        self.source_to_private()
        self.assertPermissionLevel(
            url, self.SOURCE_EDIT, is_json=True, post_data={})
        self.source_to_public()
        self.assertPermissionLevel(
            url, self.SOURCE_EDIT, is_json=True, post_data={})


default_search_params = dict(
    image_form_type='search',
    aux1='', aux2='', aux3='', aux4='', aux5='',
    height_in_cm='', latitude='', longitude='', depth='',
    photographer='', framing='', balance='',
    photo_date_0='', photo_date_1='', photo_date_2='',
    photo_date_3='', photo_date_4='',
    image_name='', annotation_status='',
    last_annotated_0='', last_annotated_1='', last_annotated_2='',
    last_annotated_3='', last_annotated_4='',
    last_annotator_0='', last_annotator_1='',
    sort_method='name', sort_direction='asc',
)


class BaseDeleteTest(ClientTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user,
            default_point_generation_method=dict(type='simple', points=2))
        cls.labels = cls.create_labels(cls.user, ['A', 'B'], "Group1")
        cls.create_labelset(cls.user, cls.source, cls.labels)

        cls.url = reverse(
            'batch_delete_annotations_ajax', args=[cls.source.pk])

    def assert_annotations_deleted(self, image):
        self.assertFalse(
            image.annotation_set.exists(),
            f"Image {image.metadata.name}'s annotations should be deleted")
        self.assertFalse(
            image.annoinfo.confirmed,
            f"Image {image.metadata.name} should not be confirmed anymore")

    def assert_annotations_not_deleted(self, image):
        self.assertEqual(
            image.annotation_set.count(), 2,
            f"Image {image.metadata.name} should still have its annotations")
        self.assertTrue(
            image.annoinfo.confirmed,
            f"Image {image.metadata.name} should still be confirmed")

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
            f"The {count} selected images have had their annotations deleted.")


class FormAvailabilityTest(BaseDeleteTest):
    """
    This form's submit button shouldn't be available in Browse if no search
    was submitted.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.img1 = cls.upload_image(
            cls.user, cls.source, dict(filename='1.png'))
        cls.browse_url = reverse('browse_images', args=[cls.source.pk])

    def assert_form_availability(self, response, expected_available):
        response_soup = BeautifulSoup(response.content, 'html.parser')
        form_soup = response_soup.find(
            'form', id='delete-annotations-ajax-form')
        submit_button_soup = form_soup.find('button', class_='submit')
        if expected_available:
            self.assertIsNotNone(submit_button_soup)
        else:
            self.assertIsNone(submit_button_soup)

    def test_no_search(self):
        self.client.force_login(self.user)
        response = self.client.post(self.browse_url, dict())
        self.assert_form_availability(response, False)

    def test_after_search(self):
        self.client.force_login(self.user)
        response = self.client.post(self.browse_url, default_search_params)
        self.assert_form_availability(response, True)


class SuccessTest(BaseDeleteTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.img1 = cls.upload_image(
            cls.user, cls.source, dict(filename='1.png'))
        cls.img2 = cls.upload_image(
            cls.user, cls.source, dict(filename='2.png'))
        cls.img3 = cls.upload_image(
            cls.user, cls.source, dict(filename='3.png'))

    def setUp(self):
        super().setUp()

        for image in [self.img1, self.img2, self.img3]:
            image.refresh_from_db()
            self.add_annotations(self.user, image, {1: 'A', 2: 'B'})

    def test_delete_for_all_images(self):
        """
        Delete annotations for all images in the source.
        """
        self.client.force_login(self.user)
        response = self.client.post(self.url, default_search_params)
        self.assertDictEqual(response.json(), dict(success=True))

        for image in [self.img1, self.img2, self.img3]:
            self.assert_annotations_deleted(image)

        self.assert_confirmation_message(count=3)

    def test_delete_by_aux_meta(self):
        """
        Delete when filtering images by auxiliary metadata.
        """
        self.img1.metadata.aux1 = 'SiteA'
        self.img1.metadata.save()

        post_data = default_search_params.copy()
        post_data['aux1'] = 'SiteA'

        self.client.force_login(self.user)
        response = self.client.post(self.url, post_data)
        self.assertDictEqual(response.json(), dict(success=True))

        self.assert_annotations_deleted(self.img1)
        self.assert_annotations_not_deleted(self.img2)
        self.assert_annotations_not_deleted(self.img3)

        self.assert_confirmation_message(count=1)

    def test_delete_by_image_ids(self):
        """
        Delete when filtering images by image ids.
        """
        post_data = dict(
            image_form_type='ids',
            ids=','.join([str(self.img1.pk), str(self.img3.pk)])
        )

        self.client.force_login(self.user)
        response = self.client.post(self.url, post_data)
        self.assertDictEqual(response.json(), dict(success=True))

        self.assert_annotations_deleted(self.img1)
        self.assert_annotations_not_deleted(self.img2)
        self.assert_annotations_deleted(self.img3)

        self.assert_confirmation_message(count=2)


class NotFullyAnnotatedTest(BaseDeleteTest):
    """
    Should work fine when some images aren't fully annotated.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.img1 = cls.upload_image(
            cls.user, cls.source, dict(filename='1.png'))
        cls.add_annotations(cls.user, cls.img1, {1: 'A', 2: 'B'})
        # One annotation, two points
        cls.img2 = cls.upload_image(
            cls.user, cls.source, dict(filename='2.png'))
        cls.add_annotations(cls.user, cls.img2, {1: 'A'})
        # No annotations
        cls.img3 = cls.upload_image(
            cls.user, cls.source, dict(filename='3.png'))

    def test(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url, default_search_params)
        self.assertDictEqual(response.json(), dict(success=True))

        for image in [self.img1, self.img2, self.img3]:
            self.assert_annotations_deleted(image)


class ClassifyAfterDeleteTest(BaseTaskTest):
    """
    Should machine-classify the images after annotation deletion,
    assuming there's a classifier available.
    """
    def test(self):
        # Set up confirmed images + classifier
        self.upload_data_and_train_classifier()

        # Set up one unconfirmed image; we want to check that the unconfirmed
        # annotations can get re-added after being deleted.
        unconfirmed_image = self.upload_image(
            self.user, self.source,
            image_options=dict(filename='unconfirmed.png'))
        # Extract features
        run_scheduled_jobs_until_empty()
        do_collect_spacer_jobs()
        # Classify
        run_scheduled_jobs_until_empty()

        unconfirmed_image.refresh_from_db()
        self.assertEqual(
            unconfirmed_image.annotation_set.unconfirmed().count(), 5,
            f"Image {unconfirmed_image.metadata.name} should have"
            f" unconfirmed annotations")

        # Delete annotations, ensuring the on-commit callback runs
        self.client.force_login(self.user)
        url = reverse('batch_delete_annotations_ajax', args=[self.source.pk])
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url, default_search_params)
        self.assertDictEqual(response.json(), dict(success=True))

        self.source.refresh_from_db()
        self.assertFalse(
            self.source.annotation_set.exists(),
            f"Source should have no annotations")

        # Classify
        run_scheduled_jobs_until_empty()

        for image in self.source.image_set.all():
            self.assertFalse(
                image.annotation_set.confirmed().exists(),
                f"Image {image.metadata.name} should have"
                f" no confirmed annotations")
            self.assertEqual(
                image.annotation_set.unconfirmed().count(), 5,
                f"Image {image.metadata.name} should have"
                f" unconfirmed annotations")
            self.assertEqual(
                image.annoinfo.status,
                'unconfirmed',
                f"Image {image.metadata.name} should be unconfirmed")


class OtherSourceTest(BaseDeleteTest):
    """
    Ensure that the view doesn't allow deleting other sources' annotations.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.img1 = cls.upload_image(
            cls.user, cls.source, dict(filename='1.png'))
        cls.img2 = cls.upload_image(
            cls.user, cls.source, dict(filename='2.png'))

        source2 = cls.create_source(
            cls.user,
            default_point_generation_method=dict(type='simple', points=2))
        cls.create_labelset(cls.user, source2, cls.labels)
        cls.img21 = cls.upload_image(
            cls.user, source2, dict(filename='21.png'))
        cls.img22 = cls.upload_image(
            cls.user, source2, dict(filename='22.png'))

    def setUp(self):
        super().setUp()

        for image in [self.img1, self.img2, self.img21, self.img22]:
            image.refresh_from_db()
            self.add_annotations(self.user, image, {1: 'A', 2: 'B'})

    def test_dont_delete_from_other_sources_via_search_form(self):
        """
        Sanity check that the search form only picks up images in the current
        source.
        """
        self.client.force_login(self.user)
        response = self.client.post(self.url, default_search_params)
        self.assertDictEqual(response.json(), dict(success=True))

        self.assert_annotations_deleted(self.img1)
        self.assert_annotations_deleted(self.img2)

        self.assert_annotations_not_deleted(self.img21)
        self.assert_annotations_not_deleted(self.img22)

    def test_dont_delete_from_other_sources_via_ids(self):
        """
        Sanity check that specifying by IDs only accepts images in the current
        source.
        """
        post_data = dict(
            image_form_type='ids',
            ids=','.join([str(self.img1.pk), str(self.img22.pk)])
        )

        self.client.force_login(self.user)
        response = self.client.post(self.url, post_data)
        self.assertDictEqual(response.json(), dict(success=True))

        self.assert_annotations_deleted(self.img1)
        self.assert_annotations_not_deleted(self.img22)


class ErrorTest(BaseDeleteTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.img1 = cls.upload_image(
            cls.user, cls.source, dict(filename='1.png'))
        cls.img2 = cls.upload_image(
            cls.user, cls.source, dict(filename='2.png'))
        cls.img3 = cls.upload_image(
            cls.user, cls.source, dict(filename='3.png'))

    def setUp(self):
        super().setUp()

        for image in [self.img1, self.img2, self.img3]:
            image.refresh_from_db()
            self.add_annotations(self.user, image, {1: 'A', 2: 'B'})

    def test_no_search_form(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url, dict())
        self.assertDictEqual(response.json(), dict(
            error=(
                "You must first use the search form or select images on the"
                " page to use the delete function. If you really want to"
                " delete all images' annotations, first click 'Search' without"
                " changing any of the search fields."
            )
        ))

        for image in [self.img1, self.img2, self.img3]:
            self.assert_annotations_not_deleted(image)

    def test_form_error(self):
        post_data = default_search_params.copy()
        post_data['annotation_status'] = 'invalid_value'

        self.client.force_login(self.user)
        response = self.client.post(self.url, post_data)
        self.assertDictEqual(response.json(), dict(
            error=(
                "There was an error with the form."
                " Nothing was deleted."
            )
        ))

        for image in [self.img1, self.img2, self.img3]:
            self.assert_annotations_not_deleted(image)
