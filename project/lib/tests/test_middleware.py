import re
from unittest import mock

from django.test.client import Client
from django.urls import reverse

from lib.tests.utils import ClientTest


class ViewLoggingMiddlewareTest(ClientTest):

    def setUp(self):
        super().setUp()

        # At least one of these tests are intended to get error statuses,
        # so don't crash the test when such statuses happen.
        self.client = Client(raise_request_exception=False)

    def test_general(self):
        with self.assertLogs(logger='coralnet_views', level='DEBUG') as cm:
            self.client.get(reverse('index'))

        expected_start_message_regex = re.compile(
            # Message prefix applied by assertLogs() (the logging handler
            # format defined in settings is not used here)
            r"DEBUG:coralnet_views:"
            # UUID for this view instance
            r"[a-f\d\-]+;"
            # start or end of view processing
            r"start;"
            # Number of concurrent views after adding this one
            r"1;"
            r";"
            r";;GET;None;/"
        )
        self.assertRegexpMatches(
            cm.output[0],
            expected_start_message_regex,
            f"Should log the expected start message")

        expected_end_message_regex = re.compile(
            r"DEBUG:coralnet_views:"
            r"[a-f\d\-]+;"
            r"end;"
            # Number of concurrent views after removing this one
            r"0;"
            # Seconds elapsed
            r"[\d.]+;"
            # View name; status code; method; user ID; request path
            r"index;200;GET;None;/"
        )
        self.assertRegexpMatches(
            cm.output[1],
            expected_end_message_regex,
            f"Should log the expected end message")

    def test_user_id(self):
        self.client.force_login(self.superuser)
        with self.assertLogs(logger='coralnet_views', level='DEBUG') as cm:
            self.client.get(reverse('index'))

        self.assertTrue(
            cm.output[0].endswith(f";GET;{self.superuser.pk};/"),
            f"Start message should have user ID. Message: {cm.output[0]}")
        self.assertTrue(
            cm.output[1].endswith(f";GET;{self.superuser.pk};/"),
            f"End message should have user ID. Message: {cm.output[1]}")

    @staticmethod
    def mock_render(*args):
        raise ValueError("Test error")

    def test_error_status(self):
        with (
            mock.patch('lib.views.render', self.mock_render),
            self.assertLogs(logger='coralnet_views', level='DEBUG') as cm
        ):
            self.client.get(reverse('index'))

        self.assertEqual(
            len(cm.output), 2, "Should still log start and end messages")
        self.assertTrue(
            cm.output[1].endswith(f";500;GET;None;/"),
            f"End message should have status code. Message: {cm.output[1]}")
