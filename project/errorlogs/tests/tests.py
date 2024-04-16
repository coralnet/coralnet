from unittest import mock

from django.test.client import Client
from django.urls import reverse

from lib.tests.utils import ClientTest
from ..models import ErrorLog


class ErrorLogTest(ClientTest):

    @staticmethod
    def mock_render(*args):
        raise ValueError("Test error")

    def setUp(self):
        super().setUp()

        # These tests are intended to get error statuses, so don't crash the
        # test when such statuses happen.
        self.client = Client(raise_request_exception=False)

    def test_get(self):
        # Mock render(), which is going to be called at the end of the view.
        # This is django.shortcuts.render, but due to the way it's imported
        # in views, the patch target is lib.views.render.
        with mock.patch('lib.views.render', self.mock_render):
            self.client.get(reverse('index'))

        log = ErrorLog.objects.latest('pk')
        self.assertEqual(log.kind, "ValueError")
        self.assertEqual(log.info, "Test error")

        relative_url = reverse('index')
        self.assertEqual(log.path, f'http://testserver{relative_url}')
        self.assertTrue(
            log.data.startswith("Traceback (most recent call last):"))
        self.assertInHTML(f"<h1>ValueError at {relative_url}</h1>", log.html)

    def test_post(self):
        user = self.create_user()
        self.client.force_login(user)
        with mock.patch('sources.views.render', self.mock_render):
            self.client.post(reverse('source_new'))

        log = ErrorLog.objects.latest('pk')
        self.assertEqual(log.kind, "ValueError")
        self.assertEqual(log.info, "Test error")

        relative_url = reverse('source_new')
        self.assertEqual(log.path, f'http://testserver{relative_url}')
        self.assertTrue(
            log.data.startswith("Traceback (most recent call last):"))
        self.assertInHTML(f"<h1>ValueError at {relative_url}</h1>", log.html)
