from __future__ import unicode_literals
from datetime import timedelta
from django.utils import timezone

from celery.decorators import periodic_task

from .models import ApiJob


@periodic_task(
    run_every=timedelta(days=1),
    name="Clean up old API jobs",
    ignore_result=True,
)
def clean_up_old_api_jobs():
    """
    Clean up API jobs that satisfy both of these criteria:
    1. Job was created 30+ days ago
    2. All of the job's job units were modified 30+ days ago

    Note that 2 is not sufficient in the corner case where a job has been
    created, but its job units haven't been created yet.
    """
    thirty_days_ago = timezone.now() - timedelta(days=30)

    for job in ApiJob.objects.filter(create_date__lt=thirty_days_ago):
        units_were_modified_in_last_30_days = job.apijobunit_set.filter(
            modify_date__gt=thirty_days_ago).exists()
        if not units_were_modified_in_last_30_days:
            # Delete the job, and its job units should cascade-delete with it.
            job.delete()
