# Utility classes and functions for tests.
import os
from django.conf import settings
from django.contrib.auth.models import User
from django.core.urlresolvers import reverse
from django.test import TestCase
from django.test.client import Client
from django.test.simple import DjangoTestSuiteRunner
from userena.managers import UserenaManager
from images.models import Source


class MyTestSuiteRunner(DjangoTestSuiteRunner):
    def setup_test_environment(self, **kwargs):
        DjangoTestSuiteRunner.setup_test_environment(self, **kwargs)

        # Media used in unit tests.
        abspath = lambda *p: os.path.abspath(os.path.join(*p))
        settings.MEDIA_ROOT = abspath(settings.PROJECT_ROOT, 'media_test')

        # The Celery daemon uses the regular Django database, while
        # the testing framework uses a separate database.  Therefore,
        # we can't get task results from the daemon during a test.
        #
        # The best solution for now is to not use the daemon, and
        # simply block and wait for the result as the task runs.
        # More info: http://docs.celeryproject.org/en/latest/django/unit-testing.html
        settings.CELERY_ALWAYS_EAGER = True


class BaseTest(TestCase):
    fixtures = []
    source_member_roles = []

    def setUp(self):
        self.setAccountPerms()
        self.setTestSpecificPerms()

    def tearDown(self):
        # TODO: Delete any files created by the tests.
        # To do this, perhaps maintain a list of files created
        # during the tests.  Then in this method, iterate over
        # that list and delete the files.  Remember to cover:
        # (1) Task-created files.  (Preprocess results files, etc.)
        # (2) Uploaded images.  (Might consider modifying upload_to()?)
        pass

    def setAccountPerms(self):
        # TODO: is the below necessary, or is adding these permissions done by magic anyway?
        #
        # Give account and profile permissions to each user.
        # It's less annoying to do this dynamically than it is to include
        # the permissions in the fixtures for every user.
        #UserenaManager().check_permissions()
        pass

    def setTestSpecificPerms(self):
        """
        Set permissions specific to the test class, e.g. source permissions.
        This has two advantages over specifying permissions in fixtures:
        (1) Can easily set permissions specific to a particular test class.
        (2) It's tedious to specify permissions in fixtures.
        """
        for role in self.source_member_roles:
            source = Source.objects.get(name=role[0])
            user = User.objects.get(username=role[1])
            source.assign_role(user, role[2])


class ClientTest(BaseTest):
    def setUp(self):
        BaseTest.setUp(self)
        self.client = Client()

    def assertStatusOK(self, response):
        self.assertEqual(response.status_code, 200)

    def login_required_page_test(self, protected_url, username, password):
        """
        Going to a login-required page while logged out should trigger a
        redirect to the login page.  Then once the user logs in, they
        should be redirected to the page they requested.
        """
        self.client.logout()
        response = self.client.get(protected_url)

        # This URL isn't built with django.utils.http.urlencode() because
        # (1) urlencode() unfortunately escapes the '/' in its arguments, and
        # (2) str concatenation should be safe when there's no possibility of
        # malicious input.
        url_signin_with_protected_page_next = reverse('signin') + '?next=' + protected_url
        self.assertRedirects(response, url_signin_with_protected_page_next)

        response = self.client.post(url_signin_with_protected_page_next, dict(
            identification=username,
            password=password,
        ))
        self.assertRedirects(response, protected_url)

    def permission_required_page_test(self, protected_url,
                                      denied_users, accepted_users):
        """
        Going to a permission-required page...
        - while logged out: should show the permission-denied template.
        - while logged in as a user without sufficient permission: should
        show the permission-denied template.
        - while logged in a a user with sufficient permission: should show
        the page they requested.
        """
        self.client.logout()
        response = self.client.get(protected_url)
        self.assertStatusOK(response)
        self.assertTemplateUsed(response, 'permission_denied.html')

        for user in denied_users:
            self.client.login(username=user['username'], password=user['password'])
            response = self.client.get(protected_url)
            self.assertStatusOK(response)
            self.assertTemplateUsed(response, 'permission_denied.html')

        for user in accepted_users:
            self.client.login(username=user['username'], password=user['password'])
            response = self.client.get(protected_url)
            self.assertStatusOK(response)
            self.assertTemplateNotUsed(response, 'permission_denied.html')