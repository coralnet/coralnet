import time

from selenium.webdriver.common.alert import Alert
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.select import Select
from selenium.webdriver.support.ui import WebDriverWait
from django.test import override_settings
from django.urls import reverse

from images.models import Image
from lib.tests.utils import (
    BrowserTest, EC_alert_is_not_present, EC_javascript_global_var_value)


# Make it easy to get multiple pages of results.
@override_settings(BROWSE_DEFAULT_THUMBNAILS_PER_PAGE=3)
class DeleteTest(BrowserTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user(username='userA', password='DeleteTest')
        cls.source = cls.create_source(
            cls.user,
            default_point_generation_method=dict(type='simple', points=2),
        )
        labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, labels)

        cls.browse_url = reverse('browse_images', args=[cls.source.pk])

        # Enough images to span multiple Browse pages
        cls.img1 = cls.upload_image(cls.user, cls.source)
        cls.img2 = cls.upload_image(cls.user, cls.source)
        cls.img3 = cls.upload_image(cls.user, cls.source)
        cls.img4 = cls.upload_image(cls.user, cls.source)
        cls.img5 = cls.upload_image(cls.user, cls.source)

        # Be able to test a filtered Browse page.
        # When filtered by aux1='X', should still bring up multiple pages,
        # with the first page being different from an unfiltered first page.
        cls.img1.metadata.aux1 = 'X'
        cls.img1.metadata.save()
        cls.img2.metadata.aux1 = 'X'
        cls.img2.metadata.save()
        cls.img3.metadata.aux1 = 'Y'
        cls.img3.metadata.save()
        cls.img4.metadata.aux1 = 'X'
        cls.img4.metadata.save()
        cls.img5.metadata.aux1 = 'X'
        cls.img5.metadata.save()

    def login_and_navigate_to_browse(self):
        self.login('userA', 'DeleteTest')
        self.get_url(self.browse_url)

    def select_search_filter(self, name, value):
        # Only the search filter names actually used in the tests are covered
        # here. Add more as needed.
        if name in ['aux1']:
            dropdown = self.selenium.find_element_by_id('id_{}'.format(name))
            Select(dropdown).select_by_value(value)

    def submit_search(self):
        with self.wait_for_page_load():
            self.selenium.find_element_by_id('search-form').submit()

    def select_delete_option(self):
        browse_action_dropdown = \
            self.selenium \
            .find_element_by_css_selector('select[name="browse_action"]')
        Select(browse_action_dropdown).select_by_value('delete')

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
        # Ensure the init JS runs.
        WebDriverWait(self.selenium, self.TIMEOUT_MEDIUM).until(
            EC_javascript_global_var_value('seleniumDebugInitRan', 'true'))

        self.select_delete_option()

        # Image select type
        image_select_type_dropdown = \
            self.selenium \
            .find_element_by_css_selector(
                'select[name="image_select_type"]')
        Select(image_select_type_dropdown).select_by_value(image_select_type)

        # Grab the page's root element in advance. We'll want to check for
        # staleness of it, but Selenium can't grab the element if an alert
        # is up.
        old_page = self.selenium.find_element_by_tag_name('html')

        # Click Go
        self.selenium \
            .find_element_by_css_selector('#delete-form button.submit') \
            .click()

        # Wait for an alert and type in its text box
        WebDriverWait(self.selenium, self.TIMEOUT_MEDIUM).until(
            EC.alert_is_present())
        alert = Alert(self.selenium)
        alert.send_keys(alert_text)

        if expect_submit:
            # Close the alert and wait for page load before returning.
            with self.wait_for_page_load(old_element=old_page):
                if alert_accept:
                    # OK
                    alert.accept()
                else:
                    # Cancel
                    alert.dismiss()
                # Before checking if the page loaded, wait for the alert to
                # close. Otherwise, checking page load could get an unexpected
                # alert exception.
                WebDriverWait(self.selenium, self.TIMEOUT_MEDIUM).until(
                    EC_alert_is_not_present())
        else:
            # Expecting that closing the alert will not trigger an ajax
            # delete or load
            if alert_accept:
                alert.accept()
            else:
                alert.dismiss()
            # Wait a moment for the JS to run. We are going to assert the
            # LACK of a change, so we can't check for an expected condition.
            # We just sleep before asserting.
            time.sleep(self.TIMEOUT_SHORT)

            # Check the debug JS variable to ensure the delete did not trigger
            delete_triggered = self.selenium.execute_script(
                'return Boolean(window.seleniumDebugDeleteTriggered)')
            self.assertFalse(delete_triggered)

        # For whatever reason, this makes the tests more stable, at least
        # on Chrome (maybe because it's faster than Firefox?).
        # Otherwise there may be some point where the DB doesn't get
        # properly rolled back before starting the next test.
        time.sleep(self.TIMEOUT_DB_CONSISTENCY)

    # Tests start here

    def test_only_delete_form_visible_after_selecting_delete(self):
        self.login_and_navigate_to_browse()
        self.select_delete_option()
        # Delete form's button should be visible

        WebDriverWait(self.selenium, self.TIMEOUT_MEDIUM).until(
            EC.visibility_of_element_located(
                [By.CSS_SELECTOR, '#delete-form button.submit']))
        # Some other form's button should not be visible
        WebDriverWait(self.selenium, self.TIMEOUT_MEDIUM).until(
            EC.invisibility_of_element_located(
                [By.CSS_SELECTOR, '#export-metadata-form button.submit']))

    def test_delete_all(self):
        """Delete all images in the source."""
        self.delete_parametrized(
            image_select_type='all',
            alert_text='delete',
            alert_accept=True,
            expect_submit=True)
        self.assertRaises(
            Image.DoesNotExist, Image.objects.get, pk=self.img1.pk)
        self.assertRaises(
            Image.DoesNotExist, Image.objects.get, pk=self.img2.pk)
        self.assertRaises(
            Image.DoesNotExist, Image.objects.get, pk=self.img3.pk)
        self.assertRaises(
            Image.DoesNotExist, Image.objects.get, pk=self.img4.pk)
        self.assertRaises(
            Image.DoesNotExist, Image.objects.get, pk=self.img5.pk)

    def test_delete_selected(self):
        """Delete selected images only."""
        self.delete_parametrized(
            image_select_type='selected',
            alert_text='delete',
            alert_accept=True,
            expect_submit=True)
        # 1st page (3 per page) should be deleted
        self.assertRaises(
            Image.DoesNotExist, Image.objects.get, pk=self.img1.pk)
        self.assertRaises(
            Image.DoesNotExist, Image.objects.get, pk=self.img2.pk)
        self.assertRaises(
            Image.DoesNotExist, Image.objects.get, pk=self.img3.pk)
        Image.objects.get(pk=self.img4.pk)
        Image.objects.get(pk=self.img5.pk)

    def test_delete_current_search_all(self):
        """Delete all images in the current search."""
        self.delete_parametrized(
            image_select_type='all',
            alert_text='delete',
            alert_accept=True,
            expect_submit=True,
            search_filters=[('aux1', 'X')])
        # Images 1, 2, 4, and 5 had aux1 of X
        self.assertRaises(
            Image.DoesNotExist, Image.objects.get, pk=self.img1.pk)
        self.assertRaises(
            Image.DoesNotExist, Image.objects.get, pk=self.img2.pk)
        Image.objects.get(pk=self.img3.pk)
        self.assertRaises(
            Image.DoesNotExist, Image.objects.get, pk=self.img4.pk)
        self.assertRaises(
            Image.DoesNotExist, Image.objects.get, pk=self.img5.pk)

    def test_delete_current_search_selected(self):
        """Delete just selected images in the current search."""
        self.delete_parametrized(
            image_select_type='selected',
            alert_text='delete',
            alert_accept=True,
            expect_submit=True,
            search_filters=[('aux1', 'X')])
        # 1st page of results had 1, 2, 4
        self.assertRaises(
            Image.DoesNotExist, Image.objects.get, pk=self.img1.pk)
        self.assertRaises(
            Image.DoesNotExist, Image.objects.get, pk=self.img2.pk)
        Image.objects.get(pk=self.img3.pk)
        self.assertRaises(
            Image.DoesNotExist, Image.objects.get, pk=self.img4.pk)
        Image.objects.get(pk=self.img5.pk)

    def test_delete_clicked_cancel(self):
        """Cancel on the prompt should result in no deletion."""
        self.delete_parametrized(
            image_select_type='all',
            alert_text='',
            alert_accept=False,
            expect_submit=False)
        Image.objects.get(pk=self.img1.pk)
        Image.objects.get(pk=self.img2.pk)
        Image.objects.get(pk=self.img3.pk)
        Image.objects.get(pk=self.img4.pk)
        Image.objects.get(pk=self.img5.pk)

    def test_delete_confirmation_not_typed_clicked_ok(self):
        """OK on prompt, but no confirmation text -> no deletion."""
        self.delete_parametrized(
            image_select_type='all',
            alert_text='',
            alert_accept=True,
            expect_submit=False)
        Image.objects.get(pk=self.img1.pk)
        Image.objects.get(pk=self.img2.pk)
        Image.objects.get(pk=self.img3.pk)
        Image.objects.get(pk=self.img4.pk)
        Image.objects.get(pk=self.img5.pk)

    def test_delete_confirmation_mistyped_clicked_ok(self):
        """OK on prompt, but wrong confirmation text -> no deletion."""
        self.delete_parametrized(
            image_select_type='all',
            alert_text='sometext',
            alert_accept=True,
            expect_submit=False)
        Image.objects.get(pk=self.img1.pk)
        Image.objects.get(pk=self.img2.pk)
        Image.objects.get(pk=self.img3.pk)
        Image.objects.get(pk=self.img4.pk)
        Image.objects.get(pk=self.img5.pk)

    def test_delete_confirmation_typed_clicked_cancel(self):
        """Correct confirmation text, but clicked Cancel -> no deletion."""
        self.delete_parametrized(
            image_select_type='all',
            alert_text='delete',
            alert_accept=False,
            expect_submit=False)
        Image.objects.get(pk=self.img1.pk)
        Image.objects.get(pk=self.img2.pk)
        Image.objects.get(pk=self.img3.pk)
        Image.objects.get(pk=self.img4.pk)
        Image.objects.get(pk=self.img5.pk)
