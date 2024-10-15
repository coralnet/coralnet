from datetime import timedelta
import random

from django.core.management.base import BaseCommand

from images.models import Source
from ...utils import schedule_source_check


class Command(BaseCommand):
    help = (
        "Check all sources for VB tasks to run."
    )

    def handle(self, *args, **options):
        scheduled = 0
        for source in Source.objects.all():
            # Schedule a check of this source at a random time in the
            # next 4 hours.
            delay_in_seconds = random.randrange(1, 60*60*4)
            job, created = schedule_source_check(
                source.pk, delay=timedelta(seconds=delay_in_seconds))
            if created:
                scheduled += 1
        self.stdout.write(
            f"Source checks have been scheduled for {scheduled} source(s)."
            f" (The other sources already had checks scheduled.)")
