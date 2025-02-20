# Utility classes and functions for tests.
from io import StringIO
from unittest import mock
import urllib.parse
from urllib.parse import (
    parse_qsl, quote as url_quote, urlencode, urlsplit, urlunsplit)
from typing import Any, Callable

import bs4
from django.contrib.auth import get_user_model
from django.core import mail, management
from django.core.cache import cache
from django.conf import settings
from django.db import connections
from django.db.utils import DEFAULT_DB_ALIAS
from django.test import override_settings, TestCase
from django.test.client import Client
from django.test.runner import DiscoverRunner
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils.html import escape as html_escape
import django_huey

from sources.models import Source
from ..storage_backends import get_storage_manager
from .utils_data import DataTestMixin

User = get_user_model()


class CustomTestRunner(DiscoverRunner):

    def run_tests(self, test_labels, **kwargs):
        # Make tasks run synchronously. This is needed since the
        # huey consumer would run in a separate process, meaning it
        # wouldn't see the state of the current test's open DB-transaction.
        #
        # We specify this behavior here, because there doesn't seem to be a way
        # to use override_settings with django-huey (it doesn't work with huey
        # standalone either).
        django_huey.get_queue('realtime').immediate = True
        django_huey.get_queue('background').immediate = True

        storage_manager = get_storage_manager()

        # Create temp directories: One for file storage during tests. One
        # for saving the storage state after a setUpTestData() call, so that
        # the state can be reverted between test methods of a class.
        test_storage_dir = storage_manager.create_temp_dir()
        post_setuptestdata_state_dir = storage_manager.create_temp_dir()

        # Create settings that establish the temp dirs accordingly.
        test_storage_settings = {
            'TEST_STORAGE_DIR': test_storage_dir,
            'POST_SETUPTESTDATA_STATE_DIR': post_setuptestdata_state_dir,
        }

        # Run tests with the above storage settings applied.
        with (
            override_settings(**test_storage_settings),
            storage_manager.override_default_storage_dir(test_storage_dir)
        ):
            return_code = super().run_tests(test_labels, **kwargs)

        # Clean up the temp dirs after the tests are done.
        storage_manager.remove_temp_dir(test_storage_dir)
        storage_manager.remove_temp_dir(post_setuptestdata_state_dir)
        return return_code


class StorageDirTest(TestCase):
    """
    Ensures that the test storage directories defined in the test runner
    are used as they should be.
    """

    @classmethod
    def setUpClass(cls):
        skipped = getattr(cls, "__unittest_skip__", False)
        if skipped:
            # This test class is being skipped. Don't bother with storage dirs.
            super().setUpClass()
            return

        # Empty contents of the test storage dir.
        storage_manager = get_storage_manager()
        storage_manager.empty_temp_dir(settings.TEST_STORAGE_DIR)

        # Call the super setUpClass(), which includes the call to
        # setUpTestData().
        super().setUpClass()

        # Now that setUpTestData() is done, save the contents of the test
        # storage dir.
        storage_manager.empty_temp_dir(settings.POST_SETUPTESTDATA_STATE_DIR)
        storage_manager.copy_dir(
            settings.TEST_STORAGE_DIR, settings.POST_SETUPTESTDATA_STATE_DIR)

    def setUp(self):
        # Reset the storage dir contents to the post-setUpTestData contents,
        # thus undoing any changes from previous test methods.
        storage_manager = get_storage_manager()
        storage_manager.empty_temp_dir(settings.TEST_STORAGE_DIR)
        storage_manager.copy_dir(
            settings.POST_SETUPTESTDATA_STATE_DIR, settings.TEST_STORAGE_DIR)

        super().setUp()


class _AssertQueriesLessThanContext(CaptureQueriesContext):
    """
    Similar to Django's _AssertNumQueriesContext, but checks less-than
    instead of equality.
    """
    def __init__(self, test_case, num, connection):
        self.test_case = test_case
        self.num = num
        super().__init__(connection)

    def __exit__(self, exc_type, exc_value, traceback):
        super().__exit__(exc_type, exc_value, traceback)
        if exc_type is not None:
            return
        executed = len(self)
        queries_string = '\n'.join(
            f"{i}. {query['sql']}"
            for i, query in enumerate(self.captured_queries, start=1)
        )
        self.test_case.assertLess(
            executed,
            self.num,
            f"{executed} queries executed, less than {self.num} expected"
            f"\nCaptured queries were:"
            f"\n{queries_string}"
        )


class BaseTest(StorageDirTest):
    """
    Base automated-test class.
    """

    # Assertion errors have the raw error followed by the
    # msg argument, if present.
    longMessage = True

    def setUp(self):
        # Some site functionality uses the cache for performance, but leaving
        # the cache uncleared between cache-using tests can mess up test
        # behavior/results.
        # This includes tests involving Django REST Framework, which uses the
        # cache to track throttling stats.
        cache.clear()

        super().setUp()

    def assert_queries_less_than(
            self, num, func=None, *args, using=DEFAULT_DB_ALIAS, **kwargs):
        """
        Similar to Django's assertNumQueries(), but checks less-than
        instead of equality.
        For example, to check that we don't do O(n) queries, we might
        assert that the number of queries is less than n (which should be
        a valid test for large enough n).
        """
        conn = connections[using]

        context = _AssertQueriesLessThanContext(self, num, conn)
        if func is None:
            return context

        with context:
            func(*args, **kwargs)


class ClientTest(DataTestMixin, BaseTest):
    """
    Unit testing class that uses the test client.
    The mixin provides many convenience functions for setting up data.
    """
    PERMISSION_DENIED_TEMPLATE = 'permission_denied.html'
    NOT_FOUND_TEMPLATE = '404.html'

    client: Client

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        # Test client. Subclasses' setUpTestData() calls can use this client
        # to set up more data before running the class's test functions.
        cls.client = Client()

        # Create a superuser.
        cls.superuser = cls.create_superuser()

    def setUp(self):
        super().setUp()

        # Test client. By setting this in setUp(), we initialize this before
        # each test function, so that stuff like login status gets reset
        # between tests.
        self.client = Client()

    def assertStatusOK(self, response, msg=None):
        """Assert that an HTTP response's status is 200 OK."""
        self.assertEqual(response.status_code, 200, msg)


class BasePermissionTest(ClientTest):
    """
    Test view permissions.
    """

    # Permission levels
    SIGNED_OUT = 1
    SIGNED_IN = 2
    SOURCE_VIEW = 3
    SOURCE_EDIT = 4
    SOURCE_ADMIN = 5
    SUPERUSER = 6

    # Deny types
    PERMISSION_DENIED = 1
    NOT_FOUND = 2
    REQUIRE_LOGIN = 3

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)

        # Not a source member
        cls.user_outsider = cls.create_user()
        # View permissions
        cls.user_viewer = cls.create_user()
        cls.add_source_member(
            cls.user, cls.source,
            cls.user_viewer, Source.PermTypes.VIEW.code)
        # Edit permissions
        cls.user_editor = cls.create_user()
        cls.add_source_member(
            cls.user, cls.source,
            cls.user_editor, Source.PermTypes.EDIT.code)
        # Admin permissions
        cls.user_admin = cls.create_user()
        cls.add_source_member(
            cls.user, cls.source,
            cls.user_admin, Source.PermTypes.ADMIN.code)

    @classmethod
    def source_to_private(cls):
        cls.source.refresh_from_db()
        cls.source.visibility = Source.VisibilityTypes.PRIVATE
        cls.source.save()

    @classmethod
    def source_to_public(cls):
        cls.source.refresh_from_db()
        cls.source.visibility = Source.VisibilityTypes.PUBLIC
        cls.source.save()

    @staticmethod
    def make_url_with_params(base_url, params):
        """
        Any permission tests involving GET params should encode the GET data in
        the URL, rather than handling it the way POST data is handled (passing
        a dict).
        This way, any `assertRedirects` calls within a `assertPermissionLevel`
        call can compare against the correct URL (including the GET params).
        This is a helper method to build said URL.
        """
        return base_url + '?' + urllib.parse.urlencode(params)

    def _make_request(self, url, user, post_data):
        if user:
            self.client.force_login(user)
        else:
            # Test while logged out
            self.client.logout()

        if post_data is not None:
            response = self.client.post(url, post_data, follow=True)
        else:
            response = self.client.get(url, follow=True)

        return response

    def assertPermissionGranted(
            self, url, user=None, post_data=None, template=None,
            content_type='text/html'):
        """
        Assert that the given user is granted permission to the given URL.
        """
        response = self._make_request(url, user, post_data)

        # Response may indicate an error, but if it does, it shouldn't be
        # about permission.
        self.assertNotEqual(response.status_code, 403)
        self.assertTemplateNotUsed(response, self.PERMISSION_DENIED_TEMPLATE)

        # For non-HTML, template assertions trivially resolve to 'not used'.
        # So here, we make sure the caller is aware if the content type isn't
        # HTML. In particular, if it's JSON, the caller probably wants the
        # Ajax version of this method instead.
        self.assertIn(content_type, response['content-type'])

        # If a template is specified, ensure it's used.
        if template:
            self.assertTemplateUsed(response, template)

    def assertPermissionDenied(
            self, url, user=None, post_data=None, deny_wording=None):
        """
        Assert that the given user is denied permission to the given URL,
        using the permission-denied template.
        """
        response = self._make_request(url, user, post_data)

        # TODO: We should probably use this assertion, but a lot of our views
        # don't yet use 403 when denying access.
        # self.assertEqual(response.status_code, 403)

        # Response should use the permission-denied template, and
        # contain the deny_wording (if provided)
        self.assertTemplateUsed(response, self.PERMISSION_DENIED_TEMPLATE)
        if deny_wording:
            self.assertContains(response, html_escape(deny_wording))

    def assertRedirectsToLogin(self, url, user=None, post_data=None):
        """
        Assert that the given user is redirected to the login page when
        trying to access the given URL.
        """
        response = self._make_request(url, user, post_data)

        # The URL should escape certain characters, like ? with %3F.
        quoted_url = url_quote(url)
        self.assertRedirects(
            response, reverse(settings.LOGIN_URL)+'?next='+quoted_url)

    def assertNotFound(self, url, user=None, post_data=None):
        """
        Assert that the given user is presented a not-found response when
        trying to access the given URL.
        """
        response = self._make_request(url, user, post_data)

        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, self.NOT_FOUND_TEMPLATE)

    def assertPermissionGrantedJson(self, url, user=None, post_data=None):
        """
        JSON-response version of assertPermissionGranted.
        """
        response = self._make_request(url, user, post_data)
        response_json = response.json()

        # Response may indicate an error, but if it does, it shouldn't be
        # about permission
        self.assertNotEqual(response.status_code, 403)
        self.assertFalse(
            'error' in response_json
            and "permission" in response_json['error'])

    def assertPermissionDeniedJson(
            self, url, user=None, post_data=None, deny_wording=None):
        """
        JSON-response version of assertPermissionDenied.
        """
        response = self._make_request(url, user, post_data)
        response_json = response.json()

        # TODO: We should probably use this assertion, but a lot of our views
        # don't yet use 403 when denying access.
        # self.assertEqual(response.status_code, 403)

        # Response should include an error that contains the deny_wording
        # (if provided)
        self.assertIn('error', response_json)
        if deny_wording:
            self.assertIn(deny_wording, response_json['error'])

    def assertLoginRequiredJson(self, url, user=None, post_data=None):
        """
        JSON-response version of assertLoginRequired.
        """
        response = self._make_request(url, user, post_data)
        response_json = response.json()

        # TODO: We should probably use this assertion, but a lot of our views
        # don't yet use 403 when denying access.
        # self.assertEqual(response.status_code, 403)

        # Response should include an error that contains the words "signed in"
        self.assertIn('error', response_json)
        self.assertIn("signed in", response_json['error'])

    def assertNotFoundJson(self, url, user=None, post_data=None):
        """
        JSON-response version of assertNotFound.
        """
        response = self._make_request(url, user, post_data)
        response_json = response.json()

        # Response should be 404 and include an error
        self.assertEqual(response.status_code, 404)
        self.assertIn('error', response_json)

    def assertPermissionLevel(
            self, url, required_level, is_json=False,
            post_data=None, template=None, content_type='text/html',
            deny_type=PERMISSION_DENIED, deny_wording="permission"):
        """
        Test that a particular URL has a particular required permission level.
        This is done by testing several relevant user levels on that URL.

        For example, if required_level is SOURCE_EDIT:
        - assert permission denied for a signed-out user, a signed-in
          user who isn't a member of the source, and a source member with View
          permission.
        - assert permission granted for a source member with Edit permission,
          and a source member with Admin permission.

        And if required_level is SIGNED_IN:
        - assert permission denied for a signed-out user.
        - assert permission granted for a signed-in user, and a
          signed-in superuser.
        """
        if required_level in [self.SIGNED_OUT, self.SIGNED_IN, self.SUPERUSER]:

            # Checking permissions on a non-source-specific page. We'll test:
            # - a signed-out user
            # - a signed-in user
            # - a superuser
            users_and_levels = [
                (None, self.SIGNED_OUT),
                (self.user_outsider, self.SIGNED_IN),
                (self.superuser, self.SUPERUSER),
            ]

        elif required_level in [
                self.SOURCE_VIEW, self.SOURCE_EDIT, self.SOURCE_ADMIN]:

            # Checking permissions on a source-specific page. We'll test:
            # - a signed-out user
            # - a signed-in user who isn't a member of the source
            # - a source member with View permission
            # - a source member with Edit permission
            # - a source member with Admin permission
            users_and_levels = [
                (None, self.SIGNED_OUT),
                (self.user_outsider, self.SIGNED_IN),
                (self.user_viewer, self.SOURCE_VIEW),
                (self.user_editor, self.SOURCE_EDIT),
                (self.user_admin, self.SOURCE_ADMIN),
            ]

        else:

            raise ValueError(
                "Unsupported required_level: {}".format(required_level))

        # Do one denied/granted assertion per user level.

        for user, user_level in users_and_levels:

            if user_level >= required_level:

                # Access should be granted

                if is_json:
                    self.assertPermissionGrantedJson(
                        url, user, post_data=post_data)
                else:
                    self.assertPermissionGranted(
                        url, user, post_data=post_data,
                        template=template, content_type=content_type)

            else:

                # Access should be denied

                if deny_type == self.PERMISSION_DENIED:

                    if is_json:
                        self.assertPermissionDeniedJson(
                            url, user, post_data=post_data,
                            deny_wording=deny_wording)
                    else:
                        self.assertPermissionDenied(
                            url, user, post_data=post_data,
                            deny_wording=deny_wording)

                elif deny_type == self.NOT_FOUND:

                    if is_json:
                        self.assertNotFoundJson(url, user, post_data=post_data)
                    else:
                        self.assertNotFound(url, user, post_data=post_data)

                elif deny_type == self.REQUIRE_LOGIN:

                    if is_json:
                        self.assertLoginRequiredJson(
                            url, user, post_data=post_data)
                    else:
                        self.assertRedirectsToLogin(
                            url, user, post_data=post_data)

                else:

                    raise ValueError(
                        "Unsupported deny_type: {}".format(deny_type))


class HtmlAssertionsMixin:

    def _assert_row_values(self, row, expected_row, column_names, row_number):
        cells = row.select('td')
        cell_contents = [
            ''.join([str(item) for item in cell.contents])
            for cell in cells
        ]

        if isinstance(expected_row, dict):
            # expected_row only has dict entries for the cell values
            # that are to be checked. dict keys are the column names.
            actual_values = dict(zip(column_names, cell_contents))

            for key, expected_value in expected_row.items():
                actual_value = actual_values.get(key)
                if actual_value is None and key not in column_names:
                    raise AssertionError(f"'{key}' isn't a table column")
                self.assertHTMLEqual(
                    actual_values.get(key),
                    # Tolerate integers as expected content
                    str(expected_value),
                    msg=f"Body row {row_number}, {key} cell"
                        f" should have expected content"
                )
        else:
            # expected_row is a list of all the cells' values.
            for cell_number, actual_value, expected_value in zip(
                range(1, 1+len(cell_contents)), cell_contents, expected_row
            ):
                # Any element specified as None is considered a
                # "don't care" value which shouldn't be checked.
                if expected_value is None:
                    continue

                self.assertHTMLEqual(
                    actual_value,
                    str(expected_value),
                    msg=f"Body row {row_number}, cell {cell_number}"
                        f" should have expected content"
                )

    def assert_table_values(
        self, table_soup: bs4.element.Tag,
        expected_values: list[dict|list],
    ):
        # Get column names from the th elements in the thead.
        column_names = [th.text for th in table_soup.select('thead th')]
        # Only check body rows (from the tbody part of the table).
        body_rows = table_soup.select('tbody > tr')

        self.assertEqual(
            len(body_rows), len(expected_values),
            msg="Should have expected number of table body rows")

        for row_number, row, expected_row in zip(
            range(1, 1+len(body_rows)), body_rows, expected_values
        ):
            self._assert_row_values(
                row, expected_row, column_names, row_number)

    def assert_table_row_values(
        self, table_soup: bs4.element.Tag,
        expected_values: dict|list,
        row_number: int,
    ):
        # Get column names from the th elements in the thead.
        column_names = [th.text for th in table_soup.select('thead th')]
        body_rows = table_soup.select('tbody > tr')
        row = body_rows[row_number - 1]

        self._assert_row_values(
            row, expected_values, column_names, row_number)

    def assert_top_message(self, page_soup, expected_message):
        messages_ul_soup = page_soup.select('ul.messages')[0]
        if not messages_ul_soup:
            raise AssertionError("Page doesn't have any top messages.")
        li_texts = [li_soup.text for li_soup in messages_ul_soup.select('li')]
        self.assertIn(
            expected_message, li_texts,
            msg="Expected top-message should be in page")


class EmailAssertionsMixin(TestCase):

    def assert_no_email(self):
        """
        It's trickier to implement a 'assert no email sent with these details'
        assertion method.
        Instead we'll have this less general but simpler one: no email sent
        at all. This is still useful for many tests.
        """
        self.assertEqual(
            len(mail.outbox), 0, "Should have not sent an email")

    def assert_latest_email(
        self,
        subject: str = None,
        body_contents: list[str] = None,
        body_not_contains: list[str] = None,
        to: list[str] = None,
        cc: list[str] = None,
        bcc: list[str] = None,
    ):
        """
        Assert that the latest sent email has the given details. Specify as
        many or as few of the supported kwargs as you like.
        """
        self.assertGreaterEqual(
            len(mail.outbox), 1, "Should have at least one email")

        # Get the latest email.
        email = mail.outbox[-1]

        if subject:
            self.assertEqual(
                f"[CoralNet] {subject}",
                email.subject,
                "Email should have the expected subject")

        body_contents = body_contents or []
        # Assert that each element of body_contents is present in the body.
        for body_content in body_contents:
            self.assertIn(
                body_content,
                email.body,
                "Email body should have the expected content")

        body_not_contains = body_not_contains or []
        # Assert that each element of body_not_contains is NOT present in the
        # body.
        for body_content in body_not_contains:
            self.assertNotIn(
                body_content,
                email.body,
                "Email body should not have this content")

        if to is not None:
            self.assertSetEqual(
                set(to), set(email.to),
                "Contents of 'to' field should be as expected",
            )

        if cc is not None:
            self.assertSetEqual(
                set(cc), set(email.cc),
                "Contents of 'cc' field should be as expected",
            )

        if bcc is not None:
            self.assertSetEqual(
                set(bcc), set(email.bcc),
                "Contents of 'bcc' field should be as expected",
            )


class ManagementCommandTest(ClientTest):
    """
    Testing management commands.
    Inherits from ClientTest because the client is still useful for setting up
    data.
    """
    @classmethod
    def call_command_and_get_output(
            cls, app_name, command_name, patch_input_value='y',
            args=None, options=None):
        """
        Based loosely on: https://stackoverflow.com/questions/59382486/
        """
        args = args or []
        options = options or dict()

        # Store output here instead of printing to console.
        stdout = StringIO()
        options['stdout'] = stdout
        # tqdm output, for example, would go to stderr.
        stderr = StringIO()
        options['stderr'] = stderr

        # When input() is called, instead of prompting for user input, just
        # return a constant value.
        patch_target = '{}.management.commands.{}.input'.format(
            app_name, command_name)
        def input_without_prompt(_):
            return patch_input_value

        with (
            mock.patch(patch_target, input_without_prompt),
            # Ensure on_commit() callbacks run.
            cls.captureOnCommitCallbacks(execute=True),
        ):
            management.call_command(command_name, *args, **options)

        return stdout.getvalue().rstrip(), stderr.getvalue().rstrip()


def scrambled_run(
    items_sort_order: list[Callable[[int], Any]]
) -> tuple[list[int], dict[int, Any]]:
    """
    Utility function for testing sort-order.

    Takes a list of functions which do some kind of setup action
    for some sortable items (e.g. insert the items into the database).
    The functions' order should correspond to the expected sort order of
    the items.
    This utility function runs the given functions in a scrambled order,
    guaranteeing that the items do not start off in the expected order
    before the sorting action happens.
    Returns 1) the run order, and 2) return values of the functions
    in run order.
    """
    item_count = len(items_sort_order)
    if item_count <= 2:
        raise ValueError("Can't scramble 2 or fewer items.")

    # Example: [2, 4, 6, 7, 5, 3, 1]
    # For all item_count >= 3, this is not [1, ..., item_count] or the
    # reverse of that.
    # And for all item_count >= 4, it's not a shifted version, either.
    run_order = (
        list(range(2, item_count+1, 2))
        + list(reversed(range(1, item_count+1, 2)))
    )

    return_values = dict()
    for run_number, f in sorted(zip(run_order, items_sort_order)):
        return_values[run_number] = f(run_number)

    return run_order, return_values


def make_media_url_comparable(url):
    """
    A media URL will have URL query args if using S3 storage. Signature and
    Expires args can change each time we get a URL for the same S3
    file, making equality assertions problematic. So we replace those
    with predictable values, effectively just checking that they are
    present.
    This should be a no-op for local-storage media URLs.
    """
    query_args = parse_qsl(urlsplit(url).query)
    comparable_query_args = {
        k: (k if k in ['Signature', 'Expires'] else v)
        for k, v in query_args}
    comparable_url = urlunsplit(
        urlsplit(url)._replace(query=urlencode(comparable_query_args)))
    return comparable_url


def spy_decorator(method_to_decorate):
    """
    A way to track calls to a class's instance method, across all instances
    of the class. From:
    https://stackoverflow.com/a/41599695
    """
    mock_obj = mock.MagicMock()
    def wrapper(self, *args, **kwargs):
        mock_obj(*args, **kwargs)
        return method_to_decorate(self, *args, **kwargs)
    wrapper.mock_obj = mock_obj
    return wrapper
