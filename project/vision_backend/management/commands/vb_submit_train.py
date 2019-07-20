from django.core.management.base import BaseCommand

from vision_backend.tasks import submit_classifier


class Command(BaseCommand):
    help = 'Submit a new classifier job for a source.'

    def add_arguments(self, parser):

        parser.add_argument('--source_id', type=int, nargs='?', help="Source id to process")
        parser.add_argument('--force', type=int, default=0, nargs='?', help="Force retrain?")

    def handle(self, *args, **options):
        submit_classifier.delay(options['source_id'], nbr_images=1e5, force=options['force'])
