from django.conf import settings
from django.db import models

from config.constants import SpacerJobSpec
from jobs.models import Job


class BatchJob(models.Model):
    """
    Simple table that tracks the AWS Batch job tokens and status.
    """
    STATUS_CHOICES = [
        ('SUBMITTED', 'SUBMITTED'),
        ('PENDING', 'PENDING'),
        ('RUNNABLE', 'RUNNABLE'),
        ('STARTING', 'STARTING'),
        ('RUNNING', 'RUNNING'),
        ('SUCCEEDED', 'SUCCEEDED'),
        ('FAILED', 'FAILED'),
    ]

    def __str__(self):
        return (
            f"BatchJob {self.pk}, for Job {self.internal_job}")

    # The status taxonomy is from AWS Batch.
    status = models.CharField(
        max_length=12, choices=STATUS_CHOICES, default='SUBMITTED')

    # Unique job identifier returned by Batch.
    batch_token = models.CharField(max_length=128, null=True)

    # Job instance that this BatchJob is associated with.
    # When the Job is cleaned up, this BatchJob also gets cleaned up via
    # cascade-delete.
    internal_job = models.OneToOneField(Job, on_delete=models.CASCADE)

    # Level of resource specs assigned to the job.
    spec_level = models.CharField(
        max_length=20,
        choices=[(s.value, s.name) for s in SpacerJobSpec],
        # This default accommodates legacy BatchJobs.
        default='',
    )

    # This can be used to see long the BatchJob is taking.
    create_date = models.DateTimeField("Date created", auto_now_add=True)

    @property
    def job_key(self):
        return settings.BATCH_JOB_PATTERN.format(pk=self.id)

    @property
    def res_key(self):
        return settings.BATCH_RES_PATTERN.format(pk=self.id)

    def make_batch_job_name(self):
        """
        This is just a name that can be useful for identifying Batch jobs
        when browsing the AWS Batch console.
        However, the Batch token is what's actually used to retrieve
        previously-submitted Batch jobs.
        """
        # Using the SPACER_JOB_HASH allows us to differentiate between
        # submissions from production, staging, and different dev setups.
        return (
            f'{settings.SPACER_JOB_HASH}'
            f'-{self.internal_job.job_name}'
            f'-{self.internal_job.pk}')
