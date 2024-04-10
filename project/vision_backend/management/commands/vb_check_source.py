from django.core.management.base import BaseCommand

from ...utils import schedule_source_check


class Command(BaseCommand):
    help = (
        "Check one or more sources for VB tasks to run."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            'source_ids', type=int, nargs='+',
            help="List of source ids to process.")

    def handle(self, *args, **options):
        source_ids = options.get('source_ids')
        for source_id in source_ids:
            schedule_source_check(source_id)
        self.stdout.write(
            f"Source checks have been scheduled for the"
            f" {len(source_ids)} source(s) requested.")
