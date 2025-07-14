import datetime
import time
from unittest import mock

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.select import Select
from selenium.webdriver.support.ui import WebDriverWait
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import timezone

from jobs.tasks import run_scheduled_jobs_until_empty
from lib.tests.utils import BasePermissionTest, spy_decorator
from sources.models import Source
from vision_backend.tests.tasks.utils import TaskTestMixin
from visualization.tests.utils import (
    BaseBrowseActionTest, BaseBrowseSeleniumTest, BrowseActionsFormTest)
from ..managers import AnnotationQuerySet


tz = timezone.get_current_timezone()


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


class BaseDeleteTest(BaseBrowseActionTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.url = reverse(
            'batch_delete_annotations_ajax', args=[cls.source.pk])

    def assert_annotations_deleted(self, image):
        self.assertFalse(
            # `.all()` seems to ensure the underlying query is run anew.
            image.annotation_set.all().exists(),
            f"Image {image.metadata.name}'s annotations should be deleted")

        image.annoinfo.refresh_from_db()
        self.assertFalse(
            image.annoinfo.confirmed,
            f"Image {image.metadata.name} should not be confirmed anymore")

    def assert_annotations_not_deleted(
        self, image, expected_count=2, expect_confirmed=True,
    ):
        image.refresh_from_db()
        self.assertEqual(
            image.annotation_set.all().count(), expected_count,
            f"Image {image.metadata.name} should still have its annotations")

        if expect_confirmed:
            image.annoinfo.refresh_from_db()
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

    def submit_and_assert_deletion(
        self, post_data: dict,
        expected_deleted: list = None,
    ):
        """
        - Submits the given post data to the delete view.
        - Asserts that the given images had their annotations deleted.
        - Asserts that all members of self.images *besides* the given
          ones did *not* have their annotations deleted. (Assumes they
          all had annotations to begin with)
        - Asserts that the expected confirmation message is present
          on the next page load.
        - Returns the response so the caller can do further checks.
        """
        if expected_deleted is None:
            expected_deleted = []
        expected_deleted_ids = [image.pk for image in expected_deleted]

        expected_not_deleted = [
            image for image in self.images
            if image.pk not in expected_deleted_ids
        ]

        response = self.submit_action(**post_data)

        for image in expected_deleted:
            self.assert_annotations_deleted(image)
        for image in expected_not_deleted:
            self.assert_annotations_not_deleted(image)

        self.assert_confirmation_message(count=len(expected_deleted))

        return response


class FormAvailabilityTest(BrowseActionsFormTest):
    form_id = 'delete-annotations-ajax-form'

    def test_no_search(self):
        self.client.force_login(self.user)
        response = self.client.get(self.browse_url)
        self.assert_form_placeholdered(
            response,
            "You must first submit the Search form before you can batch-delete annotations. (This is a safety check to reduce the chances of accidentally deleting all your annotations. If you really want to delete all annotations, just click Search without changing any of the search fields.)",
        )

        form_soup = self.get_form_soup(response)
        field_soup = form_soup.find(
            'input', attrs=dict(name='result_count')
        )
        self.assertIsNone(
            field_soup, msg="result_count field should be absent")

    def test_after_search(self):
        self.client.force_login(self.user)
        response = self.client.get(self.browse_url, self.default_search_params)
        self.assert_form_available(response)

        form_soup = self.get_form_soup(response)
        field_soup = form_soup.find(
            'input', attrs=dict(name='result_count')
        )
        self.assertEqual(
            field_soup.attrs.get('value'), '1',
            msg="result_count field should be present with correct value",
        )

    def test_view_perms_only(self):
        self.client.force_login(self.user_viewer)
        response = self.client.get(self.browse_url, self.default_search_params)
        self.assert_form_absent(response)


class SuccessTest(BaseDeleteTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.img1, cls.img2, cls.img3, cls.img4, cls.img5 = cls.images

        # Allow assertion messages to refer to the images by name.
        cls.update_multiple_metadatas(
            'name',
            ['img1', 'img2', 'img3', 'img4', 'img5'],
        )

    def setUp(self):
        super().setUp()

        for image in self.images:
            image.refresh_from_db()
            self.add_annotations(self.user, image, {1: 'A', 2: 'B'})

    def test_delete_for_all_images(self):
        """
        Delete annotations for all images in the source.
        """
        response = self.submit_and_assert_deletion(
            self.default_search_params | dict(result_count=5),
            self.images,
        )
        self.assertDictEqual(response.json(), dict(success=True))

    # Specific filters - besides annotation status, which is tested in
    # its own class later on.
    #
    # The filters here should already be tested more thoroughly in
    # test_browse_images.py or test_edit_metadata.py.

    def test_filter_by_aux1(self):
        self.update_multiple_metadatas(
            'aux1',
            [(self.img1, 'Site1'),
             (self.img2, 'Site3'),
             (self.img3, 'Site3')])

        response = self.submit_and_assert_deletion(
            dict(aux1='Site3', result_count=2),
            [self.img2, self.img3],
        )
        self.assertDictEqual(response.json(), dict(success=True))

    def test_filter_by_photo_date_year(self):
        self.update_multiple_metadatas(
            'photo_date',
            [(self.img1, datetime.date(2011, 12, 28)),
             (self.img2, datetime.date(2012, 1, 13)),
             (self.img3, datetime.date(2012, 8, 4))])

        response = self.submit_and_assert_deletion(
            dict(photo_date_0='year', photo_date_1=2012, result_count=2),
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
                result_count=3,
            ),
            [self.img2, self.img3, self.img4],
        )
        self.assertDictEqual(response.json(), dict(success=True))

    def test_filter_by_annotator_tool_specific_user(self):

        user2 = self.create_user()
        self.add_source_member(
            self.user, self.source, user2, Source.PermTypes.EDIT.code)
        # self.user already added annotations for all images in setUp().
        # To ensure user2 is credited for annotations, they must specify
        # different label codes from what self.user added.
        self.add_annotations(user2, self.img2, {1: 'B', 2: 'A'})

        response = self.submit_and_assert_deletion(
            dict(
                last_annotator_0='annotation_tool',
                last_annotator_1=user2.pk,
                result_count=1,
            ),
            [self.img2],
        )
        self.assertDictEqual(response.json(), dict(success=True))

    def test_filter_by_image_id_list(self):
        response = self.submit_and_assert_deletion(
            dict(
                image_id_list=f'{self.img2.pk}_{self.img3.pk}'
                               f'_{self.img5.pk}',
                result_count=3,
            ),
            [self.img2, self.img3, self.img5],
        )
        self.assertDictEqual(response.json(), dict(success=True))

    @override_settings(QUERYSET_CHUNK_SIZE=4)
    def test_chunks(self):
        # Add a couple more annotated images (5 -> 7) so the chunk-math
        # instills a bit more confidence.
        for _ in range(2):
            image = self.upload_image(self.user, self.source)
            self.add_annotations(self.user, image)
        self.assertEqual(
            self.source.annotation_set.count(), 14,
            msg="Should have 2*7 = 14 annotations"
        )

        # Delete for all images, while tracking how many chunks are used
        # when deleting.
        annotation_delete = spy_decorator(AnnotationQuerySet.delete)
        with mock.patch.object(AnnotationQuerySet, 'delete', annotation_delete):
            self.client.force_login(self.user)
            self.client.post(
                self.url, self.default_search_params | dict(result_count=7))

        self.assertEqual(
            annotation_delete.mock_obj.call_count, 4,
            msg="Should require 4 chunks of 4 to delete 14 annotations"
        )


class AnnotationStatusTest(BaseDeleteTest):
    """
    Test with annotation status filters, and with images that aren't
    fully annotated.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.img1, cls.img2, cls.img3, cls.img4, cls.img5 = cls.images

        robot = cls.create_robot(cls.source)
        # 2 points per image
        # confirmed, confirmed, unconfirmed, partial, unannotated
        cls.add_annotations(cls.user, cls.img1, {1: 'A', 2: 'B'})
        cls.add_annotations(cls.user, cls.img2, {1: 'B', 2: 'A'})
        cls.add_robot_annotations(robot, cls.img3)
        cls.add_annotations(cls.user, cls.img4, {1: 'B'})

    def test_delete_all(self):
        response = self.submit_action(
            **self.default_search_params, result_count=5)
        self.assertDictEqual(response.json(), dict(success=True))

        for image in self.images:
            self.assert_annotations_deleted(image)
        self.assert_confirmation_message(count=5)

    def test_filter_by_annotation_status_confirmed(self):
        response = self.submit_action(
            annotation_status='confirmed', result_count=2)
        self.assertDictEqual(response.json(), dict(success=True))

        self.assert_annotations_deleted(self.img1)
        self.assert_annotations_deleted(self.img2)
        self.assert_annotations_not_deleted(
            self.img3, expect_confirmed=False)
        self.assert_annotations_not_deleted(
            self.img4, expected_count=1, expect_confirmed=False)
        self.assert_confirmation_message(count=2)

    def test_filter_by_annotation_status_unconfirmed(self):
        response = self.submit_action(
            annotation_status='unconfirmed', result_count=1)
        self.assertDictEqual(response.json(), dict(success=True))

        self.assert_annotations_not_deleted(self.img1)
        self.assert_annotations_not_deleted(self.img2)
        self.assert_annotations_deleted(self.img3)
        self.assert_annotations_not_deleted(
            self.img4, expected_count=1, expect_confirmed=False)
        self.assert_confirmation_message(count=1)

    def test_filter_by_annotation_status_unclassified(self):
        response = self.submit_action(
            annotation_status='unclassified', result_count=2)
        self.assertDictEqual(response.json(), dict(success=True))

        self.assert_annotations_not_deleted(self.img1)
        self.assert_annotations_not_deleted(self.img2)
        self.assert_annotations_not_deleted(
            self.img3, expect_confirmed=False)
        self.assert_annotations_deleted(self.img4)
        self.assert_confirmation_message(count=2)


@override_settings(ENABLE_PERIODIC_JOBS=False)
class ClassifyAfterDeleteTest(BaseDeleteTest, TaskTestMixin):
    """
    Should machine-classify the images after annotation deletion,
    assuming there's a classifier available.
    """
    setup_image_count = 0
    points_per_image = 2

    def test(self):
        # Set up confirmed images + classifier.
        self.upload_data_and_train_classifier()

        # One more image to check that unconfirmed
        # annotations can get re-added after being deleted.
        unconfirmed_image = self.upload_image(
            self.user, self.source)

        # Extract features from the last image.
        run_scheduled_jobs_until_empty()
        self.do_collect_spacer_jobs()
        # Classify the last image.
        run_scheduled_jobs_until_empty()

        self.assertEqual(
            unconfirmed_image.annotation_set.unconfirmed().count(),
            self.points_per_image,
            msg="Last image should have unconfirmed annotations")

        # Delete annotations for unconfirmed images, ensuring the
        # on-commit callback runs to schedule another source check.
        with self.captureOnCommitCallbacks(execute=True):
            response = self.submit_action(
                annotation_status='unconfirmed', result_count=1)
        self.assertDictEqual(response.json(), dict(success=True))

        self.assert_annotations_deleted(unconfirmed_image)

        # Re-classify.
        run_scheduled_jobs_until_empty()

        self.assert_annotations_not_deleted(
            unconfirmed_image, expect_confirmed=False)


class OtherSourceTest(BaseDeleteTest):
    """
    Ensure that the view doesn't allow deleting other sources' annotations.
    """
    setup_image_count = 2

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.s1_image1 = cls.images[0]
        cls.s1_image2 = cls.images[1]

        source2 = cls.create_source(
            cls.user,
            default_point_generation_method=dict(type='simple', points=2))
        cls.create_labelset(cls.user, source2, cls.labels)
        cls.s2_image1 = cls.upload_image(cls.user, source2)
        cls.s2_image2 = cls.upload_image(cls.user, source2)

        cls.update_multiple_metadatas(
            'name',
            [(cls.s1_image1, 's1_image1.png'),
             (cls.s1_image2, 's1_image2.png'),
             (cls.s2_image1, 's2_image1.png'),
             (cls.s2_image2, 's2_image2.png')]
        )

    def setUp(self):
        super().setUp()

        for image in [
            self.s1_image1, self.s1_image2, self.s2_image1, self.s2_image2,
        ]:
            image.refresh_from_db()
            self.add_annotations(self.user, image, {1: 'A', 2: 'B'})

    def test_dont_delete_from_other_sources_via_search_form(self):
        """
        Sanity check that the search form only picks up images in the current
        source.
        """
        response = self.submit_action(
            **self.default_search_params, result_count=2)
        self.assertDictEqual(response.json(), dict(success=True))

        self.assert_annotations_deleted(self.s1_image1)
        self.assert_annotations_deleted(self.s1_image2)

        self.assert_annotations_not_deleted(self.s2_image1)
        self.assert_annotations_not_deleted(self.s2_image2)

    def test_dont_delete_from_other_sources_via_ids(self):
        """
        Sanity check that specifying by IDs only accepts images in the current
        source.
        """
        response = self.submit_action(
            image_id_list=f'{self.s1_image1.pk}_{self.s2_image2.pk}',
            result_count=0,
        )
        self.assertDictEqual(response.json(), dict(success=True))

        self.assert_annotations_deleted(self.s1_image1)
        self.assert_annotations_not_deleted(self.s2_image2)


class ErrorTest(BaseDeleteTest):

    setup_image_count = 3

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.update_multiple_metadatas(
            'name',
            ['img1', 'img2', 'img3'],
        )

    def setUp(self):
        super().setUp()

        for image in self.images:
            image.refresh_from_db()
            self.add_annotations(self.user, image, {1: 'A', 2: 'B'})

    def test_no_search_form(self):
        response = self.submit_action()
        self.assertDictEqual(response.json(), dict(
            error=(
                "You must first use the search form or select images on the"
                " page to use the delete function. If you really want to"
                " delete all images' annotations, first click 'Search' without"
                " changing any of the search fields."
            )
        ))

        for image in self.images:
            self.assert_annotations_not_deleted(image)

    def test_form_error(self):
        response = self.submit_action(annotation_status='invalid_value')

        self.assertDictEqual(response.json(), dict(
            error=(
                "There was an error with the form."
                " Nothing was deleted."
            )
        ))

        for image in self.images:
            self.assert_annotations_not_deleted(image)

    def test_missing_result_count(self):
        response = self.submit_action(search='true')

        self.assertDictEqual(response.json(), dict(
            error=(
                "Error: Number of Browse image results:"
                " This field is required. - Nothing was deleted."
            )
        ))

        for image in self.images:
            self.assert_annotations_not_deleted(image)

    def test_invalid_result_count(self):
        response = self.submit_action(search='true', result_count=-1)

        self.assertDictEqual(response.json(), dict(
            error=(
                "Error: Number of Browse image results: Ensure this value"
                " is greater than or equal to 0. - Nothing was deleted."
            )
        ))

        for image in self.images:
            self.assert_annotations_not_deleted(image)

    def test_wrong_result_count(self):
        response = self.submit_action(search='true', result_count=2)

        self.assertDictEqual(response.json(), dict(
            error=(
                "The number of image results just before deletion"
                " (3) differs from the number shown in the search"
                " (2). So as a safety measure,"
                " no annotations were deleted."
                " Make sure there isn't any ongoing activity in this source"
                " which would change the number of image results. Then,"
                " redo your search and try again."
            )
        ))

        for image in self.images:
            self.assert_annotations_not_deleted(image)


# Make it easy to get multiple pages of results.
@override_settings(BROWSE_DEFAULT_THUMBNAILS_PER_PAGE=3)
class SeleniumTest(BaseBrowseSeleniumTest):

    setup_image_count = 5

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        # Be able to test a filtered Browse page.
        # When filtered by aux1='X', should still bring up multiple pages,
        # with the first page being different from an unfiltered first page.
        cls.update_multiple_metadatas('aux1', ['X', 'X', 'Y', 'X', 'X'])

        cls.img1_pk, cls.img2_pk, cls.img3_pk, cls.img4_pk, cls.img5_pk = [
            img.pk for img in cls.images]

    def setUp(self):
        super().setUp()

        for image in self.images:
            image.refresh_from_db()
            self.add_annotations(self.user, image)

    def select_delete_option(self):
        browse_action_dropdown = self.selenium.find_element(
            By.CSS_SELECTOR, 'select[name="browse_action"]')
        Select(browse_action_dropdown).select_by_value('delete_annotations')

    def delete_parametrized(
            self, image_select_type, alert_text, alert_accept,
            expect_submit, search_filters=None):

        self.login_and_navigate_to_browse()
        if search_filters:
            for name, value in search_filters:
                self.select_search_filter(name, value)
        # Whether or not there are search filters, submit the search form
        # in order for deletion to be possible. (It's designed this way to
        # prevent bugs that could omit the search fields and accidentally
        # delete everything.)
        self.submit_search()

        self.wait_for_javascript_init()

        self.select_delete_option()

        # Image select type
        image_select_type_dropdown = self.selenium.find_element(
            By.CSS_SELECTOR, 'select[name="image_select_type"]')
        Select(image_select_type_dropdown).select_by_value(image_select_type)

        # Grab the page's root element in advance. We'll want to check for
        # staleness of it, but Selenium can't grab the element if an alert
        # is up.
        old_page = self.selenium.find_element(By.TAG_NAME, 'html')

        # Click Go
        self.selenium.find_element(
            By.CSS_SELECTOR, '#delete-annotations-ajax-form button.submit').click()

        self.do_confirmation_prompt(
            old_page, alert_text, alert_accept, expect_submit)

        # For whatever reason, this makes the tests more stable, at least
        # on Chrome (maybe because it's faster than Firefox?).
        # Otherwise there may be some point where the DB doesn't get
        # properly rolled back before starting the next test.
        time.sleep(self.TIMEOUT_DB_CONSISTENCY)

    def assert_annotations_deleted(self, image):
        self.assertFalse(
            # `.all()` seems to ensure the underlying query is run anew.
            image.annotation_set.all().exists(),
            f"Image {image.metadata.name}'s annotations should be deleted")

        image.annoinfo.refresh_from_db()
        self.assertFalse(
            image.annoinfo.confirmed,
            f"Image {image.metadata.name} should not be confirmed anymore")

    def assert_annotations_not_deleted(
        self, image, expected_count=2, expect_confirmed=True,
    ):
        image.refresh_from_db()
        self.assertEqual(
            image.annotation_set.all().count(), expected_count,
            f"Image {image.metadata.name} should still have its annotations")

        if expect_confirmed:
            image.annoinfo.refresh_from_db()
            self.assertTrue(
                image.annoinfo.confirmed,
                f"Image {image.metadata.name} should still be confirmed")

    def assert_deletion_set(self, expected_deleted_ids: list[int]):
        expected_deleted_images = [
            image for image in self.images
            if image.pk in expected_deleted_ids
        ]
        expected_not_deleted_images = [
            image for image in self.images
            if image.pk not in expected_deleted_ids
        ]

        for image in expected_deleted_images:
            self.assert_annotations_deleted(image)
        for image in expected_not_deleted_images:
            self.assert_annotations_not_deleted(image)

    # Tests start here

    def test_delete_form_not_visible_if_not_searched(self):
        self.login_and_navigate_to_browse()
        self.wait_for_javascript_init()
        self.select_delete_option()

        # Delete form's button should not be visible
        WebDriverWait(self.selenium, self.TIMEOUT_MEDIUM).until(
            EC.invisibility_of_element_located(
                (By.CSS_SELECTOR, '#delete-annotations-ajax-form button.submit')))

    def test_delete_form_not_visible_at_non_search_page_2(self):
        self.login_and_navigate_to_browse()

        next_page_link = self.selenium.find_element(
            By.CSS_SELECTOR, 'a[title="Next page"]')
        with self.wait_for_page_load():
            next_page_link.click()

        self.wait_for_javascript_init()
        self.select_delete_option()

        # Delete form's button should not be visible
        WebDriverWait(self.selenium, self.TIMEOUT_MEDIUM).until(
            EC.invisibility_of_element_located(
                (By.CSS_SELECTOR, '#delete-annotations-ajax-form button.submit')))

    def test_only_delete_form_visible_after_selecting_delete(self):
        self.login_and_navigate_to_browse()
        self.submit_search()
        self.wait_for_javascript_init()
        self.select_delete_option()

        # Delete form's button should be visible
        WebDriverWait(self.selenium, self.TIMEOUT_MEDIUM).until(
            EC.visibility_of_element_located(
                (By.CSS_SELECTOR, '#delete-annotations-ajax-form button.submit')))
        # Some other form's button should not be visible
        WebDriverWait(self.selenium, self.TIMEOUT_MEDIUM).until(
            EC.invisibility_of_element_located(
                (By.CSS_SELECTOR, '#export-metadata-form button.submit')))

    def test_delete_all(self):
        """Delete for all images in the source."""
        self.delete_parametrized(
            image_select_type='all',
            alert_text='delete',
            alert_accept=True,
            expect_submit=True)
        self.assert_deletion_set([
            self.img1_pk, self.img2_pk, self.img3_pk, self.img4_pk,
            self.img5_pk,
        ])

    def test_delete_selected(self):
        """Delete for selected images only."""
        self.delete_parametrized(
            image_select_type='selected',
            alert_text='delete',
            alert_accept=True,
            expect_submit=True)
        # 1st page (3 per page) should be deleted
        self.assert_deletion_set([
            self.img1_pk, self.img2_pk, self.img3_pk])

    def test_delete_current_search_all(self):
        """Delete for all images in the current search."""
        self.delete_parametrized(
            image_select_type='all',
            alert_text='delete',
            alert_accept=True,
            expect_submit=True,
            search_filters=[('aux1', 'X')])
        # Images 1, 2, 4, and 5 had aux1 of X
        self.assert_deletion_set([
            self.img1_pk, self.img2_pk, self.img4_pk, self.img5_pk])

    def test_delete_current_search_selected(self):
        """Delete for just selected images in the current search."""
        self.delete_parametrized(
            image_select_type='selected',
            alert_text='delete',
            alert_accept=True,
            expect_submit=True,
            search_filters=[('aux1', 'X')])
        # 1st page of results had 1, 2, 4
        self.assert_deletion_set([
            self.img1_pk, self.img2_pk, self.img4_pk])

    def test_delete_clicked_cancel(self):
        """Cancel on the prompt should result in no deletion."""
        self.delete_parametrized(
            image_select_type='all',
            alert_text='',
            alert_accept=False,
            expect_submit=False)
        self.assert_deletion_set([])

    def test_delete_confirmation_not_typed_clicked_ok(self):
        """OK on prompt, but no confirmation text -> no deletion."""
        self.delete_parametrized(
            image_select_type='all',
            alert_text='',
            alert_accept=True,
            expect_submit=False)
        self.assert_deletion_set([])

    def test_delete_confirmation_mistyped_clicked_ok(self):
        """OK on prompt, but wrong confirmation text -> no deletion."""
        self.delete_parametrized(
            image_select_type='all',
            alert_text='sometext',
            alert_accept=True,
            expect_submit=False)
        self.assert_deletion_set([])

    def test_delete_confirmation_typed_clicked_cancel(self):
        """Correct confirmation text, but clicked Cancel -> no deletion."""
        self.delete_parametrized(
            image_select_type='all',
            alert_text='delete',
            alert_accept=False,
            expect_submit=False)
        self.assert_deletion_set([])
