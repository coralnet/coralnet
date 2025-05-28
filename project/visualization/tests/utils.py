from abc import ABC, abstractmethod
from unittest import mock

from bs4 import BeautifulSoup
from django.urls import reverse
from django.utils import timezone
from django.utils.functional import classproperty

from annotations.models import Annotation
from lib.tests.utils import ClientTest
from sources.models import Source


class BaseBrowseTest(ClientTest, ABC):

    default_search_params = dict(search='true')

    setup_image_count = 5
    # At least 2 lets us have partially annotated images.
    points_per_image = 2

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user,
            default_point_generation_method=dict(
                type='simple', points=cls.points_per_image),
        )
        cls.labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, cls.labels)

        cls.images = [
            cls.upload_image(cls.user, cls.source)
            for _ in range(cls.setup_image_count)
        ]

    @classmethod
    def update_multiple_metadatas(cls, field_name, values):
        """Update a particular metadata field on multiple images."""

        if isinstance(values[0], tuple):
            # Image-value pairs
            image_value_pairs = values
        else:
            # Just values, to be paired with the full list of images
            if len(cls.images) != len(values):
                raise AssertionError(
                    "If passing only values, number of values must equal"
                    " number of images.")
            image_value_pairs = zip(cls.images, values)

        for image, value in image_value_pairs:
            setattr(image.metadata, field_name, value)
            image.metadata.save()

    def set_last_annotation(self, image, dt=None, annotator=None):
        """
        Update the image's last annotation. This simply assigns the desired
        annotation field values to the image's first point.
        """
        if not dt:
            dt = timezone.now()
        if not annotator:
            annotator = self.user

        first_point = image.point_set.get(point_number=1)
        try:
            # If the first point has an annotation, delete it.
            first_point.annotation.delete()
        except Annotation.DoesNotExist:
            pass

        # Add a new annotation to the first point.
        annotation = Annotation(
            source=image.source, image=image, point=first_point,
            user=annotator, label=self.labels.get(default_code='A'))
        # Fake the current date when saving the annotation, in order to
        # set the annotation_date field to what we want.
        # https://devblog.kogan.com/blog/testing-auto-now-datetime-fields-in-django/
        with mock.patch('django.utils.timezone.now') as mock_now:
            mock_now.return_value = dt
            annotation.save()

        image.annoinfo.last_annotation = annotation
        image.annoinfo.save()


class BaseBrowsePageTest(BaseBrowseTest, ABC):

    url_name: str

    @classproperty
    def url(cls) -> str:
        try:
            cls.url_name
        except AttributeError:
            raise AttributeError(
                "This test subclass must define a url_name attribute.")
        return reverse(cls.url_name, args=[cls.source.pk])

    def get_browse(self, user='self', **request_params):
        """
        GET the browse view with the given request params,
        and return the response.
        """
        if user == 'self':
            user = self.user

        if user is None:
            self.client.logout()
        else:
            self.client.force_login(user)
        return self.client.get(self.url, request_params)

    @abstractmethod
    def assert_browse_results(self, response, expected_results):
        """
        Assert that the given browse-view response contains the given
        expected result-objects, in the same order.
        """
        raise NotImplementedError

    @abstractmethod
    def assert_no_results(self, response):
        raise NotImplementedError

    @staticmethod
    def get_search_form_error(response, field_name):
        return response.context['image_search_form'].errors[field_name][0]

    def assert_invalid_params(
        self, response, error_field_name, expected_error
    ):
        self.assertContains(
            response, "Search parameters were invalid.",
            msg_prefix="Should have the message saying"
                       " search params were invalid",
        )
        self.assert_no_results(response)

        self.assertEqual(
            self.get_search_form_error(response, error_field_name),
            expected_error,
            msg="Error reason should be as expected (we prefer to sanity"
                " check this even if the reason's not shown to the user)",
        )

    def assert_not_invalid_params(self, response):
        self.assertNotContains(
            response, "Search parameters were invalid.",
            msg_prefix="Should not have the message saying"
                       " search params were invalid",
        )

    @staticmethod
    def get_search_form_field(response, field_name):
        response_soup = BeautifulSoup(response.content, 'html.parser')
        search_form_soup = response_soup.find('form', id='search-form')
        for tag in ['input', 'select']:
            if field_soup := search_form_soup.find(
                tag, attrs=dict(name=field_name)
            ):
                return field_soup
        return None

    @staticmethod
    def get_hidden_field_container(response):
        response_soup = BeautifulSoup(response.content, 'html.parser')
        return response_soup.find(
            'div', id='previous-image-form-fields')

    def assert_no_hidden_fields(self, response):
        container = self.get_hidden_field_container(response)
        self.assertEqual(
            len(container.find_all('input')), 0,
            msg="Hidden fields should be absent",
        )

    def assert_has_hidden_fields(self, response):
        container = self.get_hidden_field_container(response)
        self.assertGreaterEqual(
            len(container.find_all('input')), 1,
            msg="Hidden fields should be present",
        )

    @classmethod
    def get_hidden_field(cls, response, field_name):
        hidden_field_container_soup = cls.get_hidden_field_container(response)
        return hidden_field_container_soup.find(
            'input', attrs=dict(name=field_name))

    @staticmethod
    def get_field_value(field_soup):
        if field_soup.name == 'input':
            value = field_soup.attrs.get('value')
        elif field_soup.name == 'select':
            selected_option = field_soup.find('option', selected=True)
            value = selected_option.attrs.get('value')
        else:
            raise AssertionError("Don't know how to get field value")

        # At this point, an empty value is either '' for text inputs, or
        # None otherwise. None doesn't seem completely safe for assertEqual
        # (because None is supposed to be compared with `is`, not `==`), so
        # we favor ''.
        if value is None:
            return ''
        else:
            return value

    def assert_search_field_choices(
        self, response, field_name, expected_choices
    ):
        field_soup = self.get_search_form_field(response, field_name)
        if field_soup is None:
            raise AssertionError(f"Can't find `{field_name}` field")
        if field_soup.name != 'select':
            raise AssertionError(
                f"Don't know how to find choices of `{field_name}` field,"
                f" whose tag is `{field_soup.name}`")

        if len(expected_choices[0]) == 2:
            # Checking values and labels
            choices = [
                (option_soup.attrs.get('value'), option_soup.text)
                for option_soup in field_soup.find_all('option')]
        else:
            # Checking just values
            choices = [
                option_soup.attrs.get('value')
                for option_soup in field_soup.find_all('option')]

        self.assertListEqual(
            choices, expected_choices,
            msg=f"{field_name} choices should be as expected")

    def assert_page_results(
        self, response,
        expected_count, expected_summary=None, expected_page_status=None,
    ):
        self.assertEqual(
            response.context['page_results'].paginator.count, expected_count,
            msg="Result count should be as expected")

        # html=True is used so that extra whitespace is ignored.
        # There is a tradeoff though: The element name (span) and attributes
        # (none here) must be matched as well.

        if expected_summary is not None:
            self.assertContains(
                response, f"<span>{expected_summary}</span>", html=True,
                msg_prefix="Page results summary should be as expected")

        if expected_page_status is not None:
            self.assertContains(
                response, f"<span>{expected_page_status}</span>", html=True,
                msg_prefix="Page status text should be as expected")

    def assert_page_links(
        self, response, expected_prev_href, expected_next_href
    ):
        """
        We don't need to test everything about pagination link markup
        here, as that's the job of the app that implements such links.
        However, we do want to test that the query string, which
        originates from Browse's app, is as expected.

        We assume both previous and next page links are present,
        for simplicity.
        """
        response_soup = BeautifulSoup(response.content, 'html.parser')
        page_links_soup = response_soup.findAll(
            'a', class_='prev-next-page')

        self.assertEqual(
            page_links_soup[0].attrs.get('href'),
            expected_prev_href,
            msg="Previous page link is as expected")
        self.assertEqual(
            page_links_soup[1].attrs.get('href'),
            expected_next_href,
            msg="Next page link is as expected")


class BaseBrowseActionTest(BaseBrowseTest, ABC):

    def submit_action(self, **post_data):
        self.client.force_login(self.user)
        return self.client.post(self.url, post_data)


class BrowseActionsFormTest(ClientTest, ABC):
    """
    Testing states of the Browse Images action forms.
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
        cls.default_search_params = dict(search='true')

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
