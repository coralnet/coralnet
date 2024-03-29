from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from jobs.utils import job_runner
from .models import ApiJob


@job_runner(interval=timedelta(days=1))
def clean_up_old_api_jobs():
    """
    Clean up API jobs that satisfy both of these criteria:
    1. Job was created x+ days ago
    2. All of the job's job units were modified x+ days ago

    Note that 2 is not sufficient in the corner case where a job has been
    created, but its job units haven't been created yet.
    """
    x_days_ago = timezone.now() - timedelta(days=settings.JOB_MAX_DAYS)
    count = 0

    for job in ApiJob.objects.filter(create_date__lt=x_days_ago):
        units_were_modified_in_last_x_days = job.apijobunit_set.filter(
            internal_job__modify_date__gt=x_days_ago).exists()
        if not units_were_modified_in_last_x_days:
            # Delete the job, and its job units should cascade-delete with it.
            job.delete()
            count += 1

    if count > 0:
        return f"Cleaned up {count} old API job(s)"
    else:
        return "No old API jobs to clean up"
