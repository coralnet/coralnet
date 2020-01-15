from __future__ import unicode_literals

from django.contrib.auth.models import User
from django.db import models
from django.contrib.postgres.fields import JSONField


class ApiJob(models.Model):
    """
    Asynchronous jobs that were requested via the API.
    """
    # String specifying the type of job, e.g. deploy.
    type = models.CharField(max_length=30)

    # Status can be computed from the statuses of this job's job units. So,
    # saving status as a field here would be redundant. However, we'll define
    # constants for reporting the computed status.
    # Note that "Done" isn't here, because if it's done, we'll respond with
    # 303 Other with a Location header and no data in the body. That seems to
    # be standard for 303 responses.
    PENDING = "Pending"
    IN_PROGRESS = "In Progress"

    # User who requested this job. Can be used for permissions on viewing
    # job status and results.
    user = models.ForeignKey(User, on_delete=models.CASCADE)

    # This can be used to report how long the job took or is taking.
    create_date = models.DateTimeField("Date created", auto_now_add=True)


class ApiJobUnit(models.Model):
    """
    A smaller unit of work within an ApiJob.
    """
    # The larger job that this unit is a part of.
    job = models.ForeignKey(ApiJob, on_delete=models.CASCADE)

    # String specifying the type of job unit. For example, deploy might have
    # feature extraction and classification, and thus use strings like
    # 'deploy_feature_extract'.
    type = models.CharField(max_length=30)

    PENDING = 'PN'
    IN_PROGRESS = 'IP'
    SUCCESS = 'SC'
    FAILURE = 'FL'

    STATUS_CHOICES = [
        (PENDING, "Pending"),
        (IN_PROGRESS, "In Progress"),
        (SUCCESS, "Success"),
        (FAILURE, "Failure"),
    ]
    status = models.CharField(
        max_length=2, choices=STATUS_CHOICES, default=PENDING)

    # JSON containing data on the requested work. The exact format depends
    # on the type of job unit.
    request_json = JSONField()

    # JSON results of the job unit when it's done. The exact format depends
    # on the type of job.
    result_json = JSONField(null=True)

    # This can be used to report how long the job unit took or is taking
    # (including time waiting on the queue).
    create_date = models.DateTimeField("Date created", auto_now_add=True)

    # We can clean up old jobs if they haven't been modified in a while.
    modify_date = models.DateTimeField("Date last modified", auto_now=True)
