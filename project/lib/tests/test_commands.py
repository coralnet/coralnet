from contextlib import contextmanager
import datetime
import os
import tempfile
from unittest import mock

from bs4 import BeautifulSoup
from django.test.client import Client
from django.test.utils import override_settings
from django.urls import reverse
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

    @contextmanager
    def context_for_command(self):
        with (
            mock.patch('django.utils.timezone.now') as mock_now,
            tempfile.NamedTemporaryFile(
                mode='w', newline='', delete=False) as temp_file,
            override_settings(MAINTENANCE_DETAILS_FILE_PATH=temp_file.name),
        ):
            # The command opens the file from the pathname, so close it first.
            temp_file.close()

            yield mock_now

            os.remove(temp_file.name)

    @staticmethod
    def get_maintenance_message_on_page():
        client = Client()
        response = client.get(reverse('about'))
        response_soup = BeautifulSoup(response.content, 'html.parser')
        maintenance_soup = response_soup.find(
            'div', class_='maintenance_message')
        return ''.join(
            [str(content) for content in maintenance_soup.contents])

    def test_no_args(self):
        with self.context_for_command() as mock_now:
            mock_now.return_value = get_time(minute=2, second=30)
            stdout_text, _ = self.call_command_and_get_output(
                'lib', 'maintenanceon',
                # Color-style characters are not present in PyCharm but are
                # present in Windows command prompt. Make them consistently
                # absent for ease of assertions.
                args=['--no-color'],
            )

        self.assertEqual(
            "The site will be considered under maintenance starting at:"
            "\n2000-01-01, 00:25"
            "\nThat's 22\xa0minutes from now."
            "\nMaintenance mode on.",
            stdout_text,
            msg="Output should be as expected",
        )

    def test_specific_time(self):
        with self.context_for_command() as mock_now:
            mock_now.return_value = get_time(hour=6)
            stdout_text, _ = self.call_command_and_get_output(
                'lib', 'maintenanceon',
                args=['8:14', '--no-color'],
            )

        self.assertEqual(
            "The site will be considered under maintenance starting at:"
            "\n2000-01-01, 08:14"
            "\nThat's 2\xa0hours, 14\xa0minutes from now."
            "\nMaintenance mode on.",
            stdout_text,
            msg="Output should be as expected",
        )

    def test_specific_time_next_day(self):
        with self.context_for_command() as mock_now:
            mock_now.return_value = get_time(hour=6)
            stdout_text, _ = self.call_command_and_get_output(
                'lib', 'maintenanceon',
                args=['3:14', '--no-color'],
            )

        self.assertEqual(
            "The site will be considered under maintenance starting at:"
            "\n2000-01-02, 03:14"
            "\nThat's 21\xa0hours, 14\xa0minutes from now."
            "\nMaintenance mode on.",
            stdout_text,
            msg="Output should be as expected",
        )

    def test_specific_time_and_date(self):
        with self.context_for_command() as mock_now:
            mock_now.return_value = get_time(hour=6)
            stdout_text, _ = self.call_command_and_get_output(
                'lib', 'maintenanceon',
                args=['8:14', '--date', '2000-01-02', '--no-color'],
            )

        self.assertEqual(
            "The site will be considered under maintenance starting at:"
            "\n2000-01-02, 08:14"
            "\nThat's 1\xa0day, 2\xa0hours from now."
            "\nMaintenance mode on.",
            stdout_text,
            msg="Output should be as expected",
        )

    def test_specific_time_and_date_in_past(self):
        """This should be valid, and considered to be '0 minutes from now'."""
        with self.context_for_command() as mock_now:
            mock_now.return_value = get_time(hour=6)
            stdout_text, _ = self.call_command_and_get_output(
                'lib', 'maintenanceon',
                args=['8:14', '--date', '1999-12-31', '--no-color'],
            )

        self.assertEqual(
            "The site will be considered under maintenance starting at:"
            "\n1999-12-31, 08:14"
            "\nThat's 0\xa0minutes from now."
            "\nMaintenance mode on.",
            stdout_text,
            msg="Output should be as expected",
        )

    def test_pre_maintenance_message(self):
        with (
            self.context_for_command() as mock_now,
            # Can't mock the now() that the built-in timeuntil uses,
            # so we mock timeuntil instead.
            mock.patch('django.template.defaultfilters.timeuntil')
                as mock_timeuntil,
        ):
            mock_now.return_value = get_time(minute=2, second=30)
            mock_timeuntil.return_value = "22\xa0minutes"
            stdout_text, _ = self.call_command_and_get_output(
                'lib', 'maintenanceon',
                args=['--no-color'],
            )
            maintenance_message = self.get_maintenance_message_on_page()

        self.assertHTMLEqual(
            maintenance_message,
            """
            The site will be under maintenance in
            <strong>22\xa0minutes.</strong>
            If you're working on something, please wrap it up soon
            and resume when maintenance is over.
            Sorry for the inconvenience.
            """
        )

    def test_message_default(self):
        # Maintenance time in the past, so it's already in maintenance.
        with self.context_for_command() as mock_now:
            mock_now.return_value = get_time(hour=6)
            stdout_text, _ = self.call_command_and_get_output(
                'lib', 'maintenanceon',
                args=['3:14', '--date', '2000-01-01', '--no-color'],
            )
            maintenance_message = self.get_maintenance_message_on_page()

        self.assertHTMLEqual(
            maintenance_message,
            """
            <strong>The site is under maintenance.</strong>
            During maintenance, the site may abruptly become unavailable,
            and certain pages may not work properly. If you're going to
            upload or change anything, we advise you to use the site at
            a later time. We’re sorry for the inconvenience.
            """
        )

    def test_message_custom(self):
        # Maintenance time in the past, so it's already in maintenance.
        with self.context_for_command() as mock_now:
            mock_now.return_value = get_time(hour=6)
            stdout_text, _ = self.call_command_and_get_output(
                'lib', 'maintenanceon',
                args=[
                    '3:14',
                    '--date', '2000-01-01',
                    '--message', "Here's a <em>custom</em> message.",
                    '--no-color',
                ],
            )
            maintenance_message = self.get_maintenance_message_on_page()

        self.assertHTMLEqual(
            maintenance_message, "Here's a <em>custom</em> message.")
