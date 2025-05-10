from bs4 import BeautifulSoup
from django.urls import reverse

from lib.tests.utils import ClientTest
from sources.models import Source


class BrowseActionsFormTest(ClientTest):
    """
    Testing states of the Browse page's action forms.
    """
    form_id: str

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)
        cls.user_viewer = cls.create_user()
        cls.add_source_member(
            cls.user, cls.source, cls.user_viewer,
            Source.PermTypes.VIEW.code)

        # Actions are trivially unavailable when there are no images.
        # We're generally interested in testing under the assumption
        # that there's at least one image.
        cls.img = cls.upload_image(cls.user, cls.source)

        # We'll have labels, but whether we have a labelset is up to the
        # specific test.
        cls.labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')

        cls.browse_url = reverse('browse_images', args=[cls.source.pk])
        cls.default_search_params = dict(submit='search')

    @classmethod
    def get_form_soup(cls, response):
        response_soup = BeautifulSoup(response.content, 'html.parser')
        return response_soup.find('form', id=cls.form_id)

    @classmethod
    def get_submit_button_soup(cls, response):
        form_soup = cls.get_form_soup(response)
        return form_soup.find('button', class_='submit')

    def assert_form_available(self, response):
        submit_button_soup = self.get_submit_button_soup(response)
        self.assertIsNotNone(
            submit_button_soup, msg="Submit button should be present")

    def assert_form_placeholdered(self, response, expected_message):
        submit_button_soup = self.get_submit_button_soup(response)
        self.assertIsNone(
            submit_button_soup, msg="Submit button should be absent")
        form_soup = self.get_form_soup(response)
        self.assertIn(
            expected_message, str(form_soup),
            msg="Expected placeholder message should be present")

    def assert_form_absent(self, response):
        form_soup = self.get_form_soup(response)
        self.assertIsNone(
            form_soup, msg="Form should be absent")
