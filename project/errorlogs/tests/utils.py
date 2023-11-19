from unittest.case import TestCase

from ..models import ErrorLog


class ErrorReportTestMixin(TestCase):

    def assert_no_error_log_saved(self):
        self.assertFalse(
            ErrorLog.objects.exists(), "Should not have created error log")

    def assert_error_log_saved(self, kind, info):
        try:
            # Assume the latest error log is the one to check.
            error_log = ErrorLog.objects.latest('pk')
        except ErrorLog.DoesNotExist:
            raise AssertionError("Should have created error log")

        self.assertEqual(
            kind,
            error_log.kind,
            "Error log should have the expected class name")
        self.assertEqual(
            info,
            error_log.info,
            "Error log should have the expected error info")
