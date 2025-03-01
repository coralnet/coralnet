from datetime import datetime
import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import dateformat, timezone
from django.utils.timesince import timeuntil


DEFAULT_MESSAGE = """
<strong>The site is under maintenance.</strong>
During maintenance, the site may abruptly become unavailable,
and certain pages may not work properly. If you're going to
upload or change anything, we advise you to use the site at
a later time. We’re sorry for the inconvenience.
"""


class Command(BaseCommand):

    help = "Sets the top-of-page maintenance notice."

    def add_arguments(self, parser):
        parser.add_argument('time', nargs='?', help=(
            "Time to start maintenance in 24 hour format."
            " Assumed to be in the server's timezone. Example: 18:30"))
        parser.add_argument('--date', help=(
            "Date to start maintenance."
            " Assumed to be in the server's timezone."
            " If not specified, the time is assumed to be"
            " within 24 hours from now."
            " Example: 2016-11-17"))
        parser.add_argument('--message', help=(
            "Message to display as a site header during maintenance."
            " Supports HTML tags."
            " If not specified, a default message will be displayed."))

    def handle(self, *args, **options):
        maintenance_datetime = self.get_maintenance_datetime(**options)

        # This 'now' is slightly later than the 'now' in the get-datetime
        # call, but even if there's a slight inconsistency, it shouldn't have
        # much consequence.
        now_utc = timezone.now()
        now_local = timezone.localtime(now_utc)
        time_until = timeuntil(maintenance_datetime, now_local)
        start_str = datetime.strftime(maintenance_datetime, '%Y-%m-%d, %H:%M')

        self.stdout.write(
            f"The site will be considered under maintenance starting at:"
            f"\n{start_str}"
            f"\nThat's {time_until} from now.")

        # Interactivity taken from squashmigrations code.
        answer = None
        while not answer or answer not in "yn":
            answer = input("Is this OK? [yN] ")
            if not answer:
                answer = "n"
                break
            else:
                answer = answer[0].lower()
        if answer != "y":
            self.stdout.write("Aborting.")
            return

        # Options for serializing:
        # 1. DjangoJSONEncoder().encode(dt) - successfully serializes to ISO
        # format, but needs the 3rd party package dateutil to deserialize.
        # 2. Unix timestamp - done with 'U' option of dateformat.format().
        # Can deserialize with e.g. fromtimestamp().
        dt_serializable = int(dateformat.format(maintenance_datetime, 'U'))

        message = options['message'] or DEFAULT_MESSAGE

        with open(settings.MAINTENANCE_DETAILS_FILE_PATH, 'w') as json_file:
            params = dict(
                timestamp=dt_serializable,
                message=message,
            )
            json.dump(params, json_file)

        self.stdout.write(self.style.SUCCESS(
            "Maintenance mode on."))

    def get_maintenance_datetime(self, **options):
        time_str = options.get('time')
        now_utc = timezone.now()
        now_local = timezone.localtime(now_utc)

        if not time_str:
            # Start 20-25 minutes from now, making the minute of the
            # start time a multiple of 5, with no leftover seconds/micros.
            now_minute_accuracy = now_local.replace(second=0, microsecond=0)
            return now_minute_accuracy + timezone.timedelta(
                minutes=25-(now_local.minute % 5))

        date_str = options.get('date')

        if date_str:
            try:
                naive_local_datetime = datetime.strptime(
                    date_str + ' ' + time_str, '%Y-%m-%d %H:%M')
            except ValueError:
                raise CommandError(
                    "Date and time parsing failed."
                    " Date format is YYYY-MM-DD,"
                    " time format is HH:MM in the 24-hour system.")
            return timezone.make_aware(
                naive_local_datetime, timezone.get_current_timezone())

        # The time of day was specified, but not the date.
        # We'll check the current time of day.
        # If it's currently earlier than the specified time,
        # we'll infer the specified time refers to today.
        # If it's currently later than the specified time,
        # we'll infer the specified time refers to tomorrow.
        try:
            time_only = datetime.strptime(time_str, '%H:%M').time()
        except ValueError:
            raise CommandError(
                "Time parsing failed."
                " Time format is HH:MM in the 24-hour system.")
        this_time_today_naive_local = datetime.combine(
            now_local.date(), time_only)
        this_time_today = timezone.make_aware(
            this_time_today_naive_local, timezone.get_current_timezone())

        if now_local < this_time_today:
            return this_time_today

        date_tomorrow = datetime.fromordinal(
            now_local.date().toordinal() + 1).date()
        this_time_tomorrow_naive_local = datetime.combine(
            date_tomorrow, time_only)
        this_time_tomorrow = timezone.make_aware(
            this_time_tomorrow_naive_local, timezone.get_current_timezone())
        return this_time_tomorrow
