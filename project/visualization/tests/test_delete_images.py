import datetime
import time

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.select import Select
from selenium.webdriver.support.ui import WebDriverWait
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from images.models import Image, Metadata
from lib.tests.utils import BasePermissionTest
from sources.models import Source
from vision_backend.models import Features
from .utils import (
    BaseBrowseActionTest, BaseBrowseSeleniumTest, BrowseActionsFormTest)


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

        form_soup = self.get_form_soup(response)
        field_soup = form_soup.find(
            'input', attrs=dict(name='result_count')
        )
        self.assertIsNone(
            field_soup, msg="result_count field should be absent")

    def test_after_search(self):
        self.client.force_login(self.user)
        response = self.client.get(
            self.browse_url, self.default_search_params)
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
            self.default_search_params | dict(result_count=5),
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
            dict(aux1='Site3', result_count=2),
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
            dict(annotation_status='confirmed', result_count=2),
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
        self.add_annotations(self.user, self.img1, {1: 'A', 2: 'B'})

        user2 = self.create_user()
        self.add_source_member(
            self.user, self.source, user2, Source.PermTypes.EDIT.code)
        self.add_annotations(user2, self.img2, {1: 'A', 2: 'B'})

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
            # Note how result_count isn't checked for correctness
            # when using image_id_list.
            # It does still need to be present, though (because there's no
            # reason for it to not be present, and conditionally requiring it
            # takes effort).
            dict(
                image_id_list=f'{self.img2.pk}_{self.img3.pk}_{self.img5.pk}',
                result_count=0,
            ),
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
        response = self.submit_action(
            **self.default_search_params, result_count=2)
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
            image_id_list=f'{self.s1_image1.pk}_{self.s2_image2.pk}',
            result_count=0,
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

    def test_search_field_error(self):
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

    def test_missing_result_count(self):
        response = self.submit_action(search='true')

        self.assertDictEqual(response.json(), dict(
            error=(
                "Error: Number of Browse image results:"
                " This field is required. - Nothing was deleted."
            )
        ))

        self.assert_image_not_deleted(self.img1.pk, "img1")
        self.assert_image_not_deleted(self.img2.pk, "img2")
        self.assert_image_not_deleted(self.img3.pk, "img3")

    def test_invalid_result_count(self):
        response = self.submit_action(search='true', result_count=-1)

        self.assertDictEqual(response.json(), dict(
            error=(
                "Error: Number of Browse image results: Ensure this value"
                " is greater than or equal to 0. - Nothing was deleted."
            )
        ))

        self.assert_image_not_deleted(self.img1.pk, "img1")
        self.assert_image_not_deleted(self.img2.pk, "img2")
        self.assert_image_not_deleted(self.img3.pk, "img3")

    def test_wrong_result_count(self):
        response = self.submit_action(search='true', result_count=2)

        self.assertDictEqual(response.json(), dict(
            error=(
                "The deletions were attempted, but the number of deletions"
                " (3) didn't match the number expected"
                " (2). So as a safety measure, the"
                " deletions were rolled back."
                " Make sure there isn't any ongoing activity in this source"
                " which would change the number of image results. Then,"
                " redo your search and try again."
            )
        ))

        self.assert_image_not_deleted(self.img1.pk, "img1")
        self.assert_image_not_deleted(self.img2.pk, "img2")
        self.assert_image_not_deleted(self.img3.pk, "img3")


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

    def select_delete_option(self):
        browse_action_dropdown = self.selenium.find_element(
            By.CSS_SELECTOR, 'select[name="browse_action"]')
        Select(browse_action_dropdown).select_by_value('delete_images')

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
            By.CSS_SELECTOR, '#delete-images-ajax-form button.submit').click()

        self.do_confirmation_prompt(
            old_page, alert_text, alert_accept, expect_submit)

        # For whatever reason, this makes the tests more stable, at least
        # on Chrome (maybe because it's faster than Firefox?).
        # Otherwise there may be some point where the DB doesn't get
        # properly rolled back before starting the next test.
        time.sleep(self.TIMEOUT_DB_CONSISTENCY)

    def assert_image_deleted(self, image_id):
        self.assertRaises(
            Image.DoesNotExist, Image.objects.get, pk=image_id)

    @staticmethod
    def assert_image_not_deleted(image_id):
        try:
            Image.objects.get(pk=image_id)
        except Image.DoesNotExist:
            raise AssertionError(f"Image id={image_id} should not be deleted")

    def assert_deletion_set(self, expected_deleted_ids: list[int]):
        expected_not_deleted_ids = [
            image.pk for image in self.images
            if image.pk not in expected_deleted_ids
        ]

        for image_id in expected_deleted_ids:
            self.assert_image_deleted(image_id)
        for image_id in expected_not_deleted_ids:
            self.assert_image_not_deleted(image_id)

    # Tests start here

    def test_delete_form_not_visible_if_not_searched(self):
        self.login_and_navigate_to_browse()
        self.wait_for_javascript_init()
        self.select_delete_option()

        # Delete form's button should not be visible
        WebDriverWait(self.selenium, self.TIMEOUT_MEDIUM).until(
            EC.invisibility_of_element_located(
                (By.CSS_SELECTOR, '#delete-images-ajax-form button.submit')))

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
                (By.CSS_SELECTOR, '#delete-images-ajax-form button.submit')))

    def test_only_delete_form_visible_after_selecting_delete(self):
        self.login_and_navigate_to_browse()
        self.submit_search()
        self.wait_for_javascript_init()
        self.select_delete_option()

        # Delete form's button should be visible
        WebDriverWait(self.selenium, self.TIMEOUT_MEDIUM).until(
            EC.visibility_of_element_located(
                (By.CSS_SELECTOR, '#delete-images-ajax-form button.submit')))
        # Some other form's button should not be visible
        WebDriverWait(self.selenium, self.TIMEOUT_MEDIUM).until(
            EC.invisibility_of_element_located(
                (By.CSS_SELECTOR, '#export-metadata-form button.submit')))

    def test_delete_all(self):
        """Delete all images in the source."""
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
        """Delete selected images only."""
        self.delete_parametrized(
            image_select_type='selected',
            alert_text='delete',
            alert_accept=True,
            expect_submit=True)
        # 1st page (3 per page) should be deleted
        self.assert_deletion_set([
            self.img1_pk, self.img2_pk, self.img3_pk])

    def test_delete_current_search_all(self):
        """Delete all images in the current search."""
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
        """Delete just selected images in the current search."""
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
