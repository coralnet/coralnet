import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):

    help = "Removes the top-of-page maintenance notice."

    def handle(self, *args, **options):
        filepath = settings.MAINTENANCE_DETAILS_FILE_PATH

        if os.path.isfile(filepath):
            try:
                os.remove(filepath)
            except IOError:
                raise CommandError(
                    "Failed to remove the maintenance JSON file.")

            self.stdout.write(self.style.SUCCESS(
                "Maintenance mode off."))
        else:
            self.stdout.write(self.style.SUCCESS(
                "Maintenance mode is already off."))
