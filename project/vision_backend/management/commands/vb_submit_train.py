from django.core.management.base import BaseCommand

from jobs.utils import schedule_job


class Command(BaseCommand):
    help = (
        "Submit a new classifier-training job for a source."
        " This bypasses the usual criteria to see if the source"
        " needs a new classifier or not."
    )

    def add_arguments(self, parser):
        parser.add_argument('source_id', type=int, help="Source id to process")

    def handle(self, *args, **options):
        schedule_job(
            'train_classifier',
            options['source_id'],
            source_id=options['source_id'],
        )
        self.stdout.write("Training has been scheduled for this source.")
