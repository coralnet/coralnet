from unittest import mock

from django.test.client import Client
from django.urls import reverse

from lib.tests.utils import BaseTest, ClientTest
from ..models import ErrorLog
from ..utils import instantiate_error_log


class ErrorLogTest(BaseTest):
    """
    Test saving of ErrorLogs, independently of the exception handling process.
    """

    def test_null_chars(self):
        """
        Null chars can't be saved to the database. They should be replaced
        with the replacement char uFFFD.
        We don't expect them to appear in the `kind` field though.
        """
        path = 'http://127.0.0.1:8000/some/path/?arg=abc\x00def'
        info = "unsupported value: 'abc\x00def'"
        instantiate_error_log(
            kind='ValueError',
            html=f'<span>{path}</span><span>{info}</span>',
            path=path,
            info=info,
            data=f"Traceback (most recent call last): ... ValueError: {info}",
        ).save()

        log = ErrorLog.objects.latest('pk')
        self.assertEqual(log.kind, 'ValueError')
        self.assertEqual(
            log.html,
            "<span>http://127.0.0.1:8000/some/path/?arg=abc\uFFFDdef</span>"
            "<span>unsupported value: 'abc\uFFFDdef'</span>")
        self.assertEqual(
            log.path, 'http://127.0.0.1:8000/some/path/?arg=abc\uFFFDdef')
        self.assertEqual(log.info, "unsupported value: 'abc\uFFFDdef'")
        self.assertEqual(
            log.data,
            "Traceback (most recent call last): ..."
            " ValueError: unsupported value: 'abc\uFFFDdef'")

    def test_truncate(self):
        path = f'http://127.0.0.1:8000/some/path/?arg={"abcdefg"*30}'
        instantiate_error_log(
            kind='ValueError',
            html='<span>...</span>',
            path=path,
            info="An error",
            data="Traceback ...",
        ).save()

        log = ErrorLog.objects.latest('pk')
        self.assertLess(
            len(log.path), len(path),
            msg="path should be long enough to warrant truncation")
        self.assertEqual(
            log.path, path[:199] + '…',
            msg="path should be truncated to 200 chars")

    def test_truncate_and_null_chars(self):
        path = f'http://127.0.0.1:8000/some/path/?arg=\x00{"abcdefg"*30}'
        instantiate_error_log(
            kind='ValueError',
            html='<span>...</span>',
            path=path,
            info="An error",
            data="Traceback ...",
        ).save()

        log = ErrorLog.objects.latest('pk')
        self.assertLess(
            len(log.path), len(path),
            msg="path should be long enough to warrant truncation")
        self.assertEqual(
            log.path, path[:199].replace('\x00', '\uFFFD') + '…',
            msg="path should be truncated to 200 chars"
                " and should have its null char replaced")


class ExceptionTest(ClientTest):
    """
    Test ErrorLog saving in the context of exception handling.
    """

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
