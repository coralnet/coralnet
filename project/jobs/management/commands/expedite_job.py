from django.core.management.base import BaseCommand
from django.utils import timezone

from jobs.models import Job


class Command(BaseCommand):
    help = (
        "Get pending Job instances by ID and set their start times to now."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            'job_ids', type=int, nargs='+',
            help="List of Job IDs to expedite")

    def handle(self, *args, **options):
        job_ids = options.get('job_ids')
        for job_id in job_ids:
            job = Job.objects.get(pk=job_id)
            if job.status != Job.Status.PENDING:
                self.stdout.write(
                    f"Job {job_id} isn't pending; no action taken.")
            else:
                job.scheduled_start_date = timezone.now()
                job.save()
                self.stdout.write(
                    f"Job {job_id} has been expedited.")
