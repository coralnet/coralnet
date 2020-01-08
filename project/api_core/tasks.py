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
    thirty_days_ago = timezone.now() - timedelta(days=30)
    for job in ApiJob.objects.filter(modify_date__lt=thirty_days_ago):
        # Job was last modified over 30 days ago.
        # Delete the job, and its job units should cascade-delete with it.
        job.delete()
