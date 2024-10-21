from django.core.management.base import BaseCommand

from ...utils import abort_job


class Command(BaseCommand):
    help = (
        "Abort Job instances by ID. Useful if a Job is known to be stuck."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            'job_ids', type=int, nargs='+',
            help="List of Job IDs to abort")

    def handle(self, *args, **options):
        job_ids = options.get('job_ids')
        for job_id in job_ids:
            abort_job(job_id)
        self.stdout.write(
            f"The {len(job_ids)} specified Job(s) have been aborted.")
