from typing import Iterable

from django.contrib.auth.models import User
from django.db import models
from django.db.models import Q


class JobQuerySet(models.QuerySet):

    def pending(self):
        return self.filter(status=Job.Status.PENDING)

    def incomplete(self):
        return self.filter(
            status__in=[Job.Status.PENDING, Job.Status.IN_PROGRESS])

    def completed(self):
        return self.filter(
            status__in=[Job.Status.SUCCESS, Job.Status.FAILURE])


class Job(models.Model):
    """
    Tracks any kind of asynchronous job/task.
    Don't have to track every single job/task like this; just ones we want to
    keep a closer eye on.
    """
    objects = JobQuerySet.as_manager()

    job_name = models.CharField(max_length=100)

    # Secondary identifier for this Job based on the arguments it was
    # called with. Jobs with the same name + args are considered to be
    # doing the same thing.
    arg_identifier = models.CharField(max_length=100, blank=True)

    # Source this Job applies to, if applicable.
    source = models.ForeignKey(
        'sources.Source', null=True, on_delete=models.CASCADE)

    # User who initiated this Job, if applicable.
    user = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)

    class Status(models.TextChoices):
        PENDING = 'pending', "Pending"
        IN_PROGRESS = 'in_progress', "In Progress"
        SUCCESS = 'success', "Success"
        FAILURE = 'failure', "Failure"
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING)

    # Error message or comment about the job's result.
    result_message = models.CharField(max_length=5000, blank=True)

    # If this is a retry of a failed Job, then we set this to be the previous
    # Job's attempt number + 1. This allows better tracking and debugging of
    # repeat failures.
    attempt_number = models.IntegerField(default=1)

    # Set this flag to prevent the Job from being purged from the DB
    # when it gets old enough.
    persist = models.BooleanField(default=False)

    # Set this flag to prevent the Job from being listed on job-list views by
    # default. Use this for jobs that might clutter the list too much, without
    # offering that much useful info.
    hidden = models.BooleanField(default=False)

    # Date/time the Job was scheduled (pending).
    create_date = models.DateTimeField("Date created", auto_now_add=True)
    # Date/time the Job is scheduled to start, assuming server resources are
    # available then.
    # May be null if the Job is meant to be started by a specific function
    # instead of on a schedule.
    scheduled_start_date = models.DateTimeField(
        "Scheduled start date", null=True)
    # Date/time the Job actually started (status changed to in-progress).
    start_date = models.DateTimeField("Start date", null=True)
    # Date/time the Job was modified. If the Job is done, this should tell us
    # how long the Job took. This is useful info for tuning
    # task delays / periodic runs.
    modify_date = models.DateTimeField("Date modified", auto_now=True)

    class Meta:
        constraints = [
            # There cannot be two identical Jobs among the
            # incomplete Jobs.
            models.UniqueConstraint(
                fields=['job_name', 'arg_identifier'],
                condition=Q(status__in=['pending', 'in_progress']),
                name='unique_incomplete_jobs',
            ),
        ]

    def __str__(self):
        s = self.job_name
        if self.arg_identifier:
            s += f" / {self.arg_identifier}"
        if self.attempt_number > 1:
            s += f", attempt {self.attempt_number}"
        return s

    @staticmethod
    def args_to_identifier(args: Iterable) -> str:
        return ','.join([str(arg) for arg in args])

    @staticmethod
    def identifier_to_args(identifier: str) -> list[str]:
        """
        Note: this gets the args in string form, and doesn't work if the
        args themselves have , in them.
        """
        if identifier == '':
            return []
        return identifier.split(',')
