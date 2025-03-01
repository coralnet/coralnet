import datetime
import os
import tempfile
from unittest import mock

from django.test.utils import override_settings
from django.utils import timezone

from .utils import ManagementCommandTest


def get_time(**kwargs):
    datetime_kwargs = dict(
        year=2000, month=1, day=1, hour=0, minute=0, second=0,
        tzinfo=timezone.get_current_timezone(),
    )
    datetime_kwargs.update(kwargs)
    return datetime.datetime(**datetime_kwargs)


class MaintenanceOnTest(ManagementCommandTest):

    def test_no_args(self):
        with (
            mock.patch('django.utils.timezone.now') as mock_now,
            tempfile.NamedTemporaryFile(
                mode='w', newline='', delete=False) as temp_file,
            override_settings(MAINTENANCE_STATUS_FILE_PATH=temp_file.name),
        ):
            # The command opens the file from the pathname, so close it first.
            temp_file.close()

            mock_now.return_value = get_time(minute=2, second=30)
            stdout_text, _ = self.call_command_and_get_output(
                'lib', 'maintenanceon',
                # Color-style characters are not present in PyCharm but are
                # present in Windows command prompt. Make them consistently
                # absent for ease of assertions.
                args=['--no-color'],
            )

            os.remove(temp_file.name)

        self.assertEqual(
            "The site will be considered under maintenance starting at:"
            "\n2000-01-01, 00:25"
            "\nThat's 22\xa0minutes from now."
            "\nMaintenance mode on.",
            stdout_text,
            msg="Output should be as expected",
        )

    # TODO: Test with args
