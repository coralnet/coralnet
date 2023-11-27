import abc
from datetime import timedelta
from io import BytesIO
import json
import logging
import sys
from typing import Optional, Type

import boto3
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.files.storage import get_storage_class
from django.utils import timezone
from django.utils.module_loading import import_string
from spacer.messages import JobMsg, JobReturnMsg
from spacer.tasks import process_job

from config.constants import SpacerJobSpec
from jobs.utils import finish_job
from .models import BatchJob

logger = logging.getLogger(__name__)


class BaseQueue(abc.ABC):

    def __init__(self):
        self.storage = get_storage_class()()

    @abc.abstractmethod
    def submit_job(self, job: JobMsg, job_id: int, spec_level: SpacerJobSpec):
        raise NotImplementedError

    @abc.abstractmethod
    def get_collectable_jobs(self):
        raise NotImplementedError

    @abc.abstractmethod
    def collect_job(self, job) -> tuple[Optional[JobReturnMsg], str]:
        raise NotImplementedError


def get_queue_class() -> Type[BaseQueue]:
    """This function is modeled after Django's get_storage_class()."""

    if (
        settings.SPACER_QUEUE_CHOICE ==
        'vision_backend.queues.BatchQueue'
        and
        settings.DEFAULT_FILE_STORAGE ==
        'lib.storage_backends.MediaStorageLocal'
        and
        'test' not in sys.argv
    ):
        # We only raise this in non-test environments, because some tests
        # are able to use mocks to test BatchQueue while sticking with
        # local storage.
        raise ImproperlyConfigured(
            "Can not use Remote queue with local storage."
            " Please use S3 storage."
        )

    return import_string(settings.SPACER_QUEUE_CHOICE)


def get_batch_client():
    return boto3.client(
        'batch',
        region_name=settings.AWS_BATCH_REGION,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY
    )


class BatchQueue(BaseQueue):
    """
    Manages AWS Batch jobs.
    """
    def __init__(self):
        super().__init__()
        self.batch_client = get_batch_client()

    def submit_job(
            self, job_msg: JobMsg, internal_job_id: int,
            spec_level: SpacerJobSpec):

        batch_job = BatchJob(internal_job_id=internal_job_id)
        batch_job.save()

        job_msg_loc = self.storage.spacer_data_loc(batch_job.job_key)
        job_msg.store(job_msg_loc)

        job_res_loc = self.storage.spacer_data_loc(batch_job.res_key)

        resp = self.batch_client.submit_job(
            jobQueue=settings.BATCH_QUEUES[spec_level],
            jobName=batch_job.make_batch_job_name(),
            jobDefinition=settings.BATCH_JOB_DEFINITIONS[spec_level],
            containerOverrides={
                'environment': [
                    {
                        'name': 'JOB_MSG_LOC',
                        'value': json.dumps(job_msg_loc.serialize()),
                    },
                    {
                        'name': 'RES_MSG_LOC',
                        'value': json.dumps(job_res_loc.serialize()),
                    },
                ],
            }
        )
        batch_job.batch_token = resp['jobId']
        batch_job.save()

    @staticmethod
    def handle_job_failure(batch_job, error_message):
        batch_job.status = 'FAILED'
        batch_job.save()

        finish_job(
            batch_job.internal_job, success=False, result_message=error_message)

    def get_collectable_jobs(self):
        # Not-yet-collected BatchJobs.
        return BatchJob.objects.exclude(
            status__in=['SUCCEEDED', 'FAILED']
        )

    def collect_job(self, job: BatchJob) -> tuple[Optional[JobReturnMsg], str]:
        if job.batch_token is None:
            # Didn't get a batch token from AWS Batch. May indicate AWS
            # service problems (see coralnet issue 458) or it may just be
            # unlucky timing between submit and collect. Check the
            # create_date to be sure.
            if timezone.now() - job.create_date > timedelta(minutes=30):
                # Likely an AWS service problem.
                self.handle_job_failure(
                    job, "Failed to get AWS Batch token.")
                return None, 'DROPPED'
            else:
                # Let's wait a bit longer.
                return None, 'NOT SUBMITTED'

        resp = self.batch_client.describe_jobs(jobs=[job.batch_token])

        if len(resp['jobs']) == 0:
            self.handle_job_failure(
                job, f"Batch job [{job}] not found in AWS.")
            return None, 'DROPPED'

        job.status = resp['jobs'][0]['status']
        job.save()

        if job.status == 'FAILED':
            self.handle_job_failure(
                job, f"Batch job [{job}] marked as FAILED by AWS.")
            return None, job.status

        if job.status != 'SUCCEEDED':
            return None, job.status

        # Else: 'SUCCEEDED'
        logger.info(f"Entering collection of Batch job [{job}].")
        job_res_loc = self.storage.spacer_data_loc(job.res_key)

        try:
            return_msg = JobReturnMsg.load(job_res_loc)
        except IOError as e:
            self.handle_job_failure(
                job,
                f"Batch job [{job}] succeeded,"
                f" but couldn't get output at the expected location."
                f" ({e})")
            return None, job.status

        # All went well
        logger.info(f"Exiting collection of Batch job [{job}].")
        return return_msg, job.status


class LocalQueue(BaseQueue):
    """
    Used for testing the vision-backend Django tasks.
    Uses a local filesystem queue and calls spacer directly.
    """

    def submit_job(self, job: JobMsg, job_id: int, spec_level: SpacerJobSpec):

        # Process the job right away.
        return_msg = process_job(job)

        filepath = self.storage.path_join('backend_job_res', f'{job_id}.json')
        self.storage.save(
            filepath,
            BytesIO(json.dumps(return_msg.serialize()).encode()))

    def get_collectable_jobs(self):
        try:
            dir_names, filenames = self.storage.listdir('backend_job_res')
        except FileNotFoundError:
            # Perhaps this is a test run and no results files were created
            # yet (thus, the backend_job_res directory was not created).
            filenames = []

        # Sort by filename, which should also put them in job order
        filenames.sort()
        return filenames

    def collect_job(
            self, job_filename: str) -> tuple[Optional[JobReturnMsg], str]:

        # Read the job result message
        filepath = self.storage.path_join('backend_job_res', job_filename)
        with self.storage.open(filepath) as results_file:
            return_msg = JobReturnMsg.deserialize(json.load(results_file))
        # Delete the job result file
        self.storage.delete(filepath)

        # Unlike BatchQueue, LocalQueue is only aware of the
        # jobs that successfully output their results.
        return return_msg, 'SUCCEEDED'
