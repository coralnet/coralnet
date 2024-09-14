# Utility classes and functions for tests.
from abc import ABCMeta
from contextlib import contextmanager
from io import BytesIO, StringIO
import json
import math
import posixpath
import random
from unittest import mock
import urllib.parse
from urllib.parse import quote as url_quote
from typing import Any, Callable

import bs4
from PIL import Image as PILImage
from selenium import webdriver
from selenium.common.exceptions import NoAlertPresentException
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core import mail, management
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.conf import settings
from django.test import (
    override_settings, skipIfDBFeature, tag, TestCase)
from django.test.client import Client
from django.test.runner import DiscoverRunner
from django.urls import reverse
from django.utils.html import escape as html_escape
import django_huey
from spacer.messages import ClassifyReturnMsg

from annotations.model_utils import AnnotationArea
from images.model_utils import PointGen
from images.models import Image, Point
from labels.models import LabelGroup, Label
from sources.models import Source
from vision_backend.common import Extractors
from vision_backend.models import Classifier
import vision_backend.task_helpers as backend_task_helpers
from ..storage_backends import get_storage_manager

User = get_user_model()


# Settings to override in all of our unit tests.
test_settings = dict()

# For most tests, use a local memory cache instead of a filesystem cache,
# because there's no reason to persist the cache after a particular test is
# over. And having to clean up those files after each test is slower +
# more issue-prone than just using memory.
#
# Note that the Django docs have a warning on overriding the CACHES setting.
# For example, tests that use cached sessions may need some extra care.
# https://docs.djangoproject.com/en/dev/topics/testing/tools/#overriding-settings
test_settings['CACHES'] = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'test',
    }
}

# Force spacer jobs to use the dummy extractor.
# Otherwise tests will run slow.
test_settings['FORCE_DUMMY_EXTRACTOR'] = True
# Speed up training setup by requiring as few images as possible.
test_settings['TRAINING_MIN_IMAGES'] = 3
# Validation sets vs. training sets should be completely predictable in
# unit tests.
test_settings['VALSET_SELECTION_METHOD'] = 'name'


# Abstract class
class ClientUtilsMixin(object, metaclass=ABCMeta):
    """
    Utility-function mixin for tests that use a test client.

    This has to be a mixin because our test classes are descendants of two
    different built-in test classes: TestCase and LiveServerTestCase.
    """
    PERMISSION_DENIED_TEMPLATE = 'permission_denied.html'
    NOT_FOUND_TEMPLATE = '404.html'

    client: Client

    def assertStatusOK(self, response, msg=None):
        """Assert that an HTTP response's status is 200 OK."""
        self.assertEqual(response.status_code, 200, msg)

    user_count = 0

    @classmethod
    def create_user(
            cls, username=None, password='SamplePassword', email=None,
            activate=True):
        """
        Create a user.
        :param username: New user's username. 'user<number>' if not given.
        :param password: New user's password.
        :param email: New user's email. '<username>@example.com' if not given.
        :param activate: Whether to activate the user or not.
        :return: The new user.
        """
        cls.user_count += 1
        if not username:
            # Generate a username. If some tests check for string matching
            # of usernames, then having both 'user1' and 'user10' could be
            # problematic; so we add leading zeroes to the number suffix, like
            # 'user0001'.
            username = 'user{n:04d}'.format(n=cls.user_count)
        if not email:
            email = '{username}@example.com'.format(username=username)

        cls.client.post(reverse('django_registration_register'), dict(
            username=username, email=email,
            password1=password, password2=password,
            first_name="-", last_name="-",
            affiliation="-",
            reason_for_registering="-",
            project_description="-",
            how_did_you_hear_about_us="-",
            agree_to_data_policy=True,
        ))

        if activate:
            activation_email = mail.outbox[-1]
            activation_link = None
            for word in activation_email.body.split():
                if '://' in word:
                    activation_link = word
                    break
            cls.client.get(activation_link)

        return User.objects.get(username=username)

    @classmethod
    def create_superuser(cls):
        # There is a createsuperuser management command included in Django,
        # but it doesn't create a password or user profile for the new
        # superuser. Those are handy to have for some tests, so we'll instead
        # create the superuser like any regular user.
        user = cls.create_user(username='superuser')

        user.is_superuser = True
        # We don't particularly care about separating superusers/staff.
        # We'll just give this superuser everything, including staff perms.
        user.is_staff = True
        user.save()

        return user

    source_count = 0
    source_defaults = dict(
        name=None,
        visibility=Source.VisibilityTypes.PUBLIC,
        description="Description",
        affiliation="Affiliation",
        key1="Aux1",
        key2="Aux2",
        key3="Aux3",
        key4="Aux4",
        key5="Aux5",
        # X 0-100%, Y 0-100%
        image_annotation_area_0=0,
        image_annotation_area_1=100,
        image_annotation_area_2=0,
        image_annotation_area_3=100,
        # Simple random, 5 points
        default_point_generation_method_0=PointGen.Types.SIMPLE.value,
        default_point_generation_method_1=5,
        trains_own_classifiers=True,
        confidence_threshold=100,
        feature_extractor_setting=Extractors.EFFICIENTNET.value,
        latitude='0.0',
        longitude='0.0',
    )

    @classmethod
    def create_source(
        cls, user, name=None,
        image_annotation_area: dict = None,
        default_point_generation_method: dict = None,
        **options
    ):
        """
        Create a source.
        :param user: User who is creating this source.
        :param name: Source name. "Source <number>" if not given.
        :param image_annotation_area: Shortcut for specifying this
          source option as one concise dict (min_x, max_x, min_y, max_y)
          instead of 4 verbose kwargs.
        :param default_point_generation_method: Shortcut for specifying
          this source option as one concise dict instead of 2-4 verbose
          kwargs.
        :param options: Other params to POST into the new source form.
        :return: The new source.
        """
        cls.source_count += 1
        if not name:
            name = f'Source {cls.source_count:04d}'

        post_dict = dict()
        post_dict.update(cls.source_defaults)
        post_dict.update(options)
        post_dict['name'] = name

        if image_annotation_area:
            area = AnnotationArea(
                type=AnnotationArea.TYPE_PERCENTAGES, **image_annotation_area)
            post_dict |= area.source_form_kwargs
        if default_point_generation_method:
            post_dict |= PointGen(
                **default_point_generation_method).source_form_kwargs

        cls.client.force_login(user)
        # Create source.
        cls.client.post(reverse('source_new'), post_dict)
        source = Source.objects.get(name=name)
        # Edit source; confidence_threshold is only reachable from source_edit.
        cls.client.post(reverse('source_edit', args=[source.pk]), post_dict)
        source.refresh_from_db()
        cls.client.logout()

        return source

    @classmethod
    def add_source_member(cls, admin, source, member, perm):
        """
        Add member to source, with permission level perm.
        Use admin to send the invite.
        """
        # Send invite as source admin
        cls.client.force_login(admin)
        cls.client.post(
            reverse('source_admin', kwargs={'source_id': source.pk}),
            dict(
                sendInvite='sendInvite',
                recipient=member.username,
                source_perm=perm,
            )
        )
        # Accept invite as prospective source member
        cls.client.force_login(member)
        cls.client.post(
            reverse('invites_manage'),
            dict(
                accept='accept',
                sender=admin.pk,
                source=source.pk,
            )
        )

        cls.client.logout()

    @classmethod
    def create_labels(cls, user, label_names, group_name, default_codes=None):
        """
        Create labels.
        :param user: User who is creating these labels.
        :param label_names: Names for the new labels.
        :param group_name: Name for the label group to put the labels in;
          this label group is assumed to not exist yet.
        :param default_codes: Default short codes for the labels, as a list of
          the same length as label_names. If not specified, the first 10
          letters of the label names are used.
        :return: The new labels, as a queryset.
        """
        group = LabelGroup(name=group_name, code=group_name[:10])
        group.save()

        if default_codes is None:
            default_codes = [name[:10] for name in label_names]

        cls.client.force_login(user)
        for name, code in zip(label_names, default_codes):
            cls.client.post(
                reverse('label_new_ajax'),
                dict(
                    name=name,
                    default_code=code,
                    group=group.id,
                    description="Description",
                    # A new filename will be generated, and the uploaded
                    # filename will be discarded, so it doesn't matter.
                    thumbnail=sample_image_as_file('_.png'),
                )
            )
        cls.client.logout()

        return Label.objects.filter(name__in=label_names)

    @classmethod
    def create_labelset(cls, user, source, labels):
        """
        Create a labelset (or redefine entries in an existing one).
        :param user: User to create the labelset as.
        :param source: The source which this labelset will belong to
        :param labels: The labels this labelset will have, as a queryset
        :return: The new labelset
        """
        cls.client.force_login(user)
        cls.client.post(
            reverse('labelset_add', kwargs=dict(source_id=source.id)),
            dict(
                label_ids=','.join(
                    str(pk) for pk in labels.values_list('pk', flat=True)),
            ),
        )
        cls.client.logout()
        source.refresh_from_db()
        return source.labelset

    image_count = 0

    @classmethod
    def upload_image(cls, user, source, image_options=None, image_file=None):
        """
        Upload a data image.
        :param user: User to upload as.
        :param source: Source to upload to.
        :param image_options: Dict of options for the image file.
            Accepted keys: filetype, and whatever create_sample_image() takes.
        :param image_file: If present, this is an open file to use as the
            image file. Takes precedence over image_options.
        :return: The new image.
        """
        cls.image_count += 1

        post_dict = dict()

        # Get an image file
        if image_file:
            post_dict['file'] = image_file
            post_dict['name'] = image_file.name
        else:
            image_options = image_options or dict()
            filetype = image_options.pop('filetype', 'PNG')
            default_filename = "file_{count:04d}.{filetype}".format(
                count=cls.image_count, filetype=filetype.lower())
            filename = image_options.pop('filename', default_filename)
            post_dict['file'] = sample_image_as_file(
                filename, filetype, image_options)
            post_dict['name'] = filename

        # Send the upload form.
        # Ensure the on_commit() callback runs, which should schedule a
        # source check.
        cls.client.force_login(user)
        with cls.captureOnCommitCallbacks(execute=True):
            response = cls.client.post(
                reverse('upload_images_ajax', kwargs={'source_id': source.id}),
                post_dict,
            )
        cls.client.logout()

        response_json = response.json()
        image_id = response_json['image_id']
        image = Image.objects.get(pk=image_id)
        return image

    @classmethod
    def add_annotations(cls, user, image, annotations=None):
        """
        Add human annotations to an image.
        :param user: Which user to annotate as.
        :param image: Image to add annotations for.
        :param annotations: Annotations to add, as a dict of point
            numbers to label codes, e.g.: {1: 'labelA', 2: 'labelB'}
            If not specified, adds random annotations for all points.
        :return: None.
        """
        if not annotations:
            annotations = random_annotations(image)

        num_points = Point.objects.filter(image=image).count()

        post_dict = dict()
        for point_num in range(1, num_points+1):
            post_dict['label_'+str(point_num)] = annotations.get(point_num, '')
            post_dict['robot_'+str(point_num)] = json.dumps(False)

        cls.client.force_login(user)
        cls.client.post(
            reverse('save_annotations_ajax', kwargs=dict(image_id=image.id)),
            post_dict,
        )
        cls.client.logout()

    @staticmethod
    def create_robot(source, set_as_deployed=True):
        """
        Add a robot to a source.
        """
        return create_robot(source, set_as_deployed=set_as_deployed)

    @staticmethod
    def add_robot_annotations(robot, image, annotations=None):
        """
        Add robot annotations to an image.
        """
        add_robot_annotations(robot, image, annotations=annotations)


class CustomTestRunner(DiscoverRunner):

    def run_tests(self, test_labels, extra_tests=None, **kwargs):
        """
        extra_tests can be removed from the signature of this method
        once PyCharm stops using it:
        https://youtrack.jetbrains.com/issue/PY-53355/Warning-when-running-Django-tests-RemovedInDjango50Warning-The-extratests-argument-is-deprecated
        """
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


@override_settings(**test_settings)
class BaseTest(TestCase):
    """
    Base automated-test class.

    Ensures that the test storage directories defined in the test runner
    are used as they should be.
    """

    # Assertion errors have the raw error followed by the
    # msg argument, if present.
    longMessage = True

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

        # Some site functionality uses the cache for performance, but leaving
        # the cache uncleared between cache-using tests can mess up test
        # results.
        cache.clear()

        super().setUp()


class ClientTest(ClientUtilsMixin, BaseTest):
    """
    Unit testing class that uses the test client.
    The mixin provides many convenience functions, mostly for setting up data.
    """
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


class EC_alert_is_not_present(object):
    """Selenium expected condition: An alert is NOT present.
    Based on the built-in alert_is_present."""
    def __init__(self):
        pass

    def __call__(self, driver):
        try:
            alert = driver.switch_to.alert
            # Accessing the alert text could throw a NoAlertPresentException
            _ = alert.text
            return False
        except NoAlertPresentException:
            return True


class EC_javascript_global_var_value(object):
    """Selenium expected condition: A global Javascript variable
    has a particular value."""
    def __init__(self, var_name, expected_value):
        self.var_name = var_name
        self.expected_value = expected_value

    def __call__(self, driver):
        return driver.execute_script(
            'return (window.{} === {})'.format(
                self.var_name, self.expected_value))


@tag('selenium')
@skipIfDBFeature('test_db_allows_multiple_connections')
class BrowserTest(StaticLiveServerTestCase, ClientTest):
    """
    Unit testing class for running tests in the browser with Selenium.
    Selenium reference: https://selenium-python.readthedocs.io/api.html

    You can skip these tests like `manage.py test --exclude-tag selenium`.

    Explanation of the inheritance scheme and
    @skipIfDBFeature('test_db_allows_multiple_connections'):
    This class inherits StaticLiveServerTestCase for the live-server
    functionality, and (a subclass of) TestCase to achieve test-function
    isolation using uncommitted transactions.
    StaticLiveServerTestCase does not have the latter feature. The reason is
    that live server tests use separate threads, which may use separate
    DB connections, which may end up in inconsistent states. To avoid
    this, it inherits from TransactionTestCase, which makes each connection
    commit all their transactions.
    But if there is only one DB connection possible, like with SQLite
    (which is in-memory for Django tests), then this inconsistency concern
    is not present, and we can use TestCase's feature. Hence the decorator:
    @skipIfDBFeature('test_db_allows_multiple_connections')
    Which ensures that these tests are skipped for PostgreSQL, MySQL, etc.,
    but are run if the DB backend setting is SQLite.
    Finally, we really want TestCase because:
    1) Our migrations have initial data in them, such as Robot and Alleviate
    users, and for some reason this data might get erased (and not re-created)
    between tests if TestCase is not used.
    2) The ClientUtilsMixin's utility methods are all classmethods which are
    supposed to be called in setUpTestData(). TestCase is what provides the
    setUpTestData() hook.
    Related discussions:
    https://code.djangoproject.com/ticket/23640
    https://stackoverflow.com/questions/29378328/
    """
    selenium = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Selenium driver.
        # TODO: Look into running tests with multiple browsers. Right now it
        # just runs the first specified browser in SELENIUM_BROWSERS.
        # Test parametrization idea 1:
        # https://docs.pytest.org/en/latest/parametrize.html
        # https://twitter.com/audreyr/status/702540511425396736
        # Test parametrization idea 2: https://stackoverflow.com/a/40982410/
        # Decorator idea: https://stackoverflow.com/a/26821662/
        for browser in settings.SELENIUM_BROWSERS:
            browser_name_lower = browser['name'].lower()

            if browser_name_lower == 'firefox':
                options = FirefoxOptions()
                for option in browser.get('options', []):
                    options.add_argument(option)
                cls.selenium = webdriver.Firefox(
                    firefox_binary=browser.get('browser_binary', None),
                    executable_path=browser.get('webdriver', 'geckodriver'),
                    firefox_options=options,
                )
                break

            if browser_name_lower == 'chrome':
                options = ChromeOptions()
                for option in browser.get('options', []):
                    options.add_argument(option)
                # Seems like the Chrome driver doesn't support a browser
                # binary argument.
                cls.selenium = webdriver.Chrome(
                    executable_path=browser.get('webdriver', 'chromedriver'),
                    chrome_options=options,
                )
                break

            if browser_name_lower == 'phantomjs':
                cls.selenium = webdriver.PhantomJS(
                    executable_path=browser.get('webdriver', 'phantomjs'),
                )
                break

        # These class-var names should be nicer for autocomplete usage.
        cls.TIMEOUT_DB_CONSISTENCY = \
            settings.SELENIUM_TIMEOUTS['db_consistency']
        cls.TIMEOUT_SHORT = settings.SELENIUM_TIMEOUTS['short']
        cls.TIMEOUT_MEDIUM = settings.SELENIUM_TIMEOUTS['medium']
        cls.TIMEOUT_PAGE_LOAD = settings.SELENIUM_TIMEOUTS['page_load']

        # The default timeout here can be quite long, like 300 seconds.
        cls.selenium.set_page_load_timeout(cls.TIMEOUT_PAGE_LOAD)

    @classmethod
    def tearDownClass(cls):
        cls.selenium.quit()

        super().tearDownClass()

    @contextmanager
    def wait_for_page_load(self, old_element=None):
        """
        Implementation from:
        http://www.obeythetestinggoat.com/how-to-get-selenium-to-wait-for-page-load-after-a-click.html

        Limitations:

        - "Note that this solution only works for "non-javascript" clicks,
        ie clicks that will cause the browser to load a brand new page,
        and thus load a brand new HTML body element."

        - Getting old_element and checking for staleness of it won't work
        if an alert is present. You'll get an unexpected alert exception.
        If you expect to have an alert present when starting this context
        manager, you should pass in an old_element, and wait until the alert
        is no longer present before finishing this context manager's block.

        - This doesn't wait for on-page-load Javascript to run. That will need
        to be checked separately.
        """
        if not old_element:
            old_element = self.selenium.find_element_by_tag_name('html')
        yield
        WebDriverWait(self.selenium, self.TIMEOUT_PAGE_LOAD) \
            .until(EC.staleness_of(old_element))

    def get_url(self, url):
        """
        url is something like `/login/`. In general it can be a result of
        reverse().
        """
        self.selenium.get('{}{}'.format(self.live_server_url, url))

    def login(self, username, password, stay_signed_in=False):
        self.get_url(reverse('login'))
        username_input = self.selenium.find_element_by_name("username")
        username_input.send_keys(username)
        password_input = self.selenium.find_element_by_name("password")
        password_input.send_keys(password)

        if stay_signed_in:
            # Tick the checkbox
            stay_signed_in_input = \
                self.selenium.find_element_by_name("stay_signed_in")
            stay_signed_in_input.click()

        with self.wait_for_page_load():
            self.selenium.find_element_by_css_selector(
                'input[value="Sign in"]').click()


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


def create_sample_image(width=200, height=200, cols=10, rows=10, mode='RGB'):
    """
    Create a test image. The image content is a color grid.
    Optionally specify pixel width/height, and the color grid cols/rows.
    You can also specify the "mode" (see PIL documentation).
    Colors are interpolated along the grid with randomly picked color ranges.

    Return as an in-memory PIL image.
    """
    # Randomly choose one RGB color component to vary along x, one to vary
    # along y, and one to stay constant.
    x_varying_component = random.choice([0, 1, 2])
    y_varying_component = random.choice(list(
        {0, 1, 2} - {x_varying_component}))
    const_component = list(
        {0, 1, 2} - {x_varying_component, y_varying_component})[0]
    # Randomly choose the ranges of colors.
    x_min_color = random.choice([0.0, 0.1, 0.2, 0.3])
    x_max_color = random.choice([0.7, 0.8, 0.9, 1.0])
    y_min_color = random.choice([0.0, 0.1, 0.2, 0.3])
    y_max_color = random.choice([0.7, 0.8, 0.9, 1.0])
    const_color = random.choice([0.3, 0.4, 0.5, 0.6, 0.7])

    col_width = width / cols
    row_height = height / rows
    min_rgb = 0
    max_rgb = 255

    im = PILImage.new(mode, (width, height))

    const_color_value = int(round(
        const_color*(max_rgb - min_rgb) + min_rgb
    ))

    for x in range(cols):

        left_x = int(round(x*col_width))
        right_x = int(round((x+1)*col_width))

        x_varying_color_value = int(round(
            (x/cols)*(x_max_color - x_min_color)*(max_rgb - min_rgb)
            + (x_min_color*min_rgb)
        ))

        for y in range(rows):

            upper_y = int(round(y*row_height))
            lower_y = int(round((y+1)*row_height))

            y_varying_color_value = int(round(
                (y/rows)*(y_max_color - y_min_color)*(max_rgb - min_rgb)
                + (y_min_color*min_rgb)
            ))

            color_dict = {
                x_varying_component: x_varying_color_value,
                y_varying_component: y_varying_color_value,
                const_component: const_color_value,
            }

            # The dict's keys should be the literals 0, 1, and 2.
            # We interpret these as R, G, and B respectively.
            if mode in ['L', '1', 'P']:
                # Gray scale, just grab one of the channels.
                im.paste(color_dict[0], (left_x, upper_y, right_x, lower_y))
            else:
                rgb_color = (color_dict[0], color_dict[1], color_dict[2])
                im.paste(rgb_color, (left_x, upper_y, right_x, lower_y))

    return im


def sample_image_as_file(filename, filetype=None, image_options=None):
    if not filetype:
        if posixpath.splitext(filename)[-1].upper() in ['.JPG', '.JPEG']:
            filetype = 'JPEG'
        elif posixpath.splitext(filename)[-1].upper() == '.PNG':
            filetype = 'PNG'
        else:
            raise ValueError(
                "Couldn't get filetype from filename: {}".format(filename))

    image_options = image_options or dict()
    im = create_sample_image(**image_options)
    with BytesIO() as stream:
        # Save the PIL image to an IO stream
        im.save(stream, filetype)
        # Convert to a file-like object, and use that in the upload form
        # http://stackoverflow.com/a/28209277/
        image_file = ContentFile(stream.getvalue(), name=filename)
    return image_file


def create_robot(source, set_as_deployed=True):
    """
    Add a robot (Classifier) to a source.
    NOTE: This does not use any standard task or utility function
    for adding a robot, so standard assumptions might not hold.
    :param source: Source to add a robot for.
    :return: The new robot.
    """
    classifier = Classifier(
        source=source,
        nbr_train_images=50,
        runtime_train=100,
        accuracy=0.50,
        status=Classifier.ACCEPTED,
    )
    classifier.save()

    if set_as_deployed:
        source.deployed_classifier = classifier
        source.save()

    return classifier


def random_annotations(image) -> dict[int, str]:
    """
    Example: {1: 'labelA', 2: 'labelB'}
    """
    point_count = image.point_set.count()
    point_numbers = range(1, point_count + 1)
    local_labels = list(image.source.labelset.locallabel_set.all())
    label_codes = [
        random.choice(local_labels).code
        for _ in range(point_count)]
    return dict(zip(point_numbers, label_codes))


def add_robot_annotations(robot, image, annotations=None):
    """
    Add robot annotations and scores to an image, without touching any
    computer vision algorithms.

    NOTE: This only uses helper functions for adding robot annotations,
    not an entire view or task. So the regular assumptions might not hold,
    like setting statuses, etc. Use with slight caution.

    :param robot: Classifier model object to use for annotation.
    :param image: Image to add annotations for.
    :param annotations: Annotations to add,
      as a dict of point numbers to label codes like: {1: 'AB', 2: 'CD'}
      OR dict of point numbers to label code / confidence value tuples:
      {1: ('AB', 85), 2: ('CD', 47)}
      You must specify annotations for ALL points in the image, because
      that's the expectation of the helper function called from here.
      Alternatively, you can skip specifying this parameter and let this
      function assign random labels.
    :return: None.
    """
    # This is the same way _add_annotations() orders points.
    # This is the order that the scores list should follow.
    points = Point.objects.filter(image=image).order_by('id')

    # Labels can be in any order, as long as the order stays consistent
    # throughout annotation adding.
    local_labels = list(image.source.labelset.get_labels())
    label_count = len(local_labels)

    if annotations is None:
        annotations = random_annotations(image)

    # Make label scores. The specified label should come out on top,
    # and that label's confidence value (if specified) should be respected.
    # The rest is arbitrary.
    scores = []
    for point in points:
        try:
            annotation = annotations[point.point_number]
        except KeyError:
            raise ValueError((
                "No annotation specified for point {num}. You must specify"
                " annotations for all points in this image.").format(
                    num=point.point_number))

        if isinstance(annotation, str):
            # Only top label specified
            label_code = annotation
            # Pick a top score, which is possible to be an UNTIED top score
            # given the label count (if tied, then the top label is ambiguous).
            # min with 100 to cover the 1-label-count case.
            lowest_possible_confidence = min(
                100, math.ceil(100 / label_count) + 1)
            top_score = random.randint(lowest_possible_confidence, 100)
        else:
            # Top label and top confidence specified
            label_code, top_score = annotation

        remaining_total = 100 - top_score
        quotient = remaining_total // (label_count - 1)
        remainder = remaining_total % (label_count - 1)
        other_scores = [quotient + 1] * remainder
        other_scores += [quotient] * (label_count - 1 - remainder)

        # We just tried to make the max of other_scores as small as
        # possible (given a total of 100), so if that didn't work,
        # then we'll conclude the confidence value is unreasonably low
        # given the label count. (Example: 33% confidence, 2 labels)
        if max(other_scores) >= top_score:
            raise ValueError((
                "Could not create {label_count} label scores with a"
                " top confidence value of {top_score}. Try lowering"
                " the confidence or adding more labels.").format(
                    label_count=label_count, top_score=top_score))

        scores_for_point = []
        # List of scores for a point and list of labels should be in
        # the same order. In particular, if the nth label is the top one,
        # then the nth score should be the top one too.
        for local_label in local_labels:
            if local_label.code == label_code:
                scores_for_point.append(top_score)
            else:
                scores_for_point.append(other_scores.pop())

        # Up to now we've represented 65% as the integer 65, for easier math.
        # But the utility functions we'll call actually expect the float 0.65.
        # So divide by 100.
        scores.append((
            point.row, point.column, [s / 100 for s in scores_for_point]))

    global_labels = [ll.global_label for ll in local_labels]

    # Package scores into a ClassifyReturnMsg. Note that this function expects
    # scores for all labels, but will only save the top
    # NBR_SCORES_PER_ANNOTATION per point.
    clf_return_msg = ClassifyReturnMsg(
        runtime=1.0,
        scores=scores,
        classes=[label.pk for label in global_labels],
        valid_rowcol=True
    )

    backend_task_helpers.add_scores(image.pk, clf_return_msg, global_labels)
    backend_task_helpers.add_annotations(
        image.pk, clf_return_msg, global_labels, robot)


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
