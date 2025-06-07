from django.urls import reverse

from lib.tests.utils import ClientTest


class ExportTestMixin:

    def assert_csv_content_equal(self, actual_csv_content, expected_lines):
        """
        Tests that a CSV's content is as expected.

        :param actual_csv_content: CSV content from the export view's
          response, as either a Unicode string or a bytes-like object
          (bytes if passing response.content into here directly, Unicode if
          pre-processed first).
        :param expected_lines: List of strings, without newline characters,
          representing the expected line contents. Note that this is a
          different format from actual_csv_content, just because it's easier
          to type non-newline strings in Python code.
        Throws AssertionError if actual and expected CSVs are not equal.
        """
        # Convert from bytes to Unicode if necessary.
        if isinstance(actual_csv_content, bytes):
            actual_csv_content = actual_csv_content.decode()

        # The Python csv module uses \r\n by default (as part of the Excel
        # dialect). Due to the way we compare line by line, splitting on
        # \n would mess up the comparison, so we use split() instead of
        # splitlines().
        actual_lines = actual_csv_content.split('\r\n')
        # Since we're not using splitlines(), we have to deal with ending
        # newlines manually.
        if actual_lines[-1] == "":
            actual_lines.pop()
        expected_content = '\r\n'.join(expected_lines) + '\r\n'

        # Compare individual lines (so that if we get a mismatch, the error
        # message will be readable)
        for line_num, actual_line in enumerate(actual_lines, 1):
            self.assertGreaterEqual(
                len(expected_lines), line_num,
                f"Actual content should not have {line_num} or more lines")
            expected_line = expected_lines[line_num-1]
            self.assertEqual(
                actual_line, expected_line,
                msg=f"Line {line_num} should be equal | Actual: {actual_line}"
                    f" | Expected: {expected_line}"
            )
        # Compare entire file, to ensure line separator types and line counts
        # match.
        self.assertEqual(actual_csv_content, expected_content)


class BaseExportTest(ClientTest, ExportTestMixin):

    def export_metadata(self, post_data=None):
        """POST to export_metadata, and return the response."""
        self.client.force_login(self.user)
        return self.client.post(
            reverse('export_metadata', args=[self.source.pk]),
            post_data or {},
            follow=True,
        )
