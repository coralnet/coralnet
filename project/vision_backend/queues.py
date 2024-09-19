import abc
from datetime import timedelta
from io import BytesIO
import json
from logging import getLogger
from typing import Optional, Type

import boto3
from botocore.exceptions import ClientError
from django.conf import settings
from django.core.files.storage import default_storage
from django.utils import timezone
from django.utils.module_loading import import_string
from spacer.messages import JobMsg, JobReturnMsg
from spacer.tasks import process_job

from config.constants import SpacerJobSpec
from jobs.utils import finish_job
from .models import BatchJob

logger = getLogger(__name__)


class BaseQueue(abc.ABC):

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

        batch_job = BatchJob(
            internal_job_id=internal_job_id, spec_level=spec_level.value)
        batch_job.save()

        job_msg_loc = default_storage.spacer_data_loc(batch_job.job_key)
        job_msg.store(job_msg_loc)

        job_res_loc = default_storage.spacer_data_loc(batch_job.res_key)

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
            # Not done yet, e.g. RUNNING
            return None, job.status

        # Else: 'SUCCEEDED'
        job_res_loc = default_storage.spacer_data_loc(job.res_key)

        try:
            return_msg = JobReturnMsg.load(job_res_loc)
        except (ClientError, IOError) as e:
            # IOError for local storage, ClientError for S3 storage
            self.handle_job_failure(
                job,
                f"Batch job [{job}] succeeded,"
                f" but couldn't get output at the expected location."
                f" ({e})")
            return None, job.status

        # All went well
        return return_msg, job.status


class LocalQueue(BaseQueue):
    """
    Used for testing the vision-backend Django tasks.
    Uses a local filesystem queue and calls spacer directly.
    """

    def submit_job(self, job: JobMsg, job_id: int, spec_level: SpacerJobSpec):

        # Process the job right away.
        return_msg = process_job(job)

        filepath = default_storage.path_join('backend_job_res', f'{job_id}.json')
        default_storage.save(
            filepath,
            BytesIO(json.dumps(return_msg.serialize()).encode()))

    def get_collectable_jobs(self):
        try:
            dir_names, filenames = default_storage.listdir('backend_job_res')
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
        filepath = default_storage.path_join('backend_job_res', job_filename)
        with default_storage.open(filepath) as results_file:
            return_msg = JobReturnMsg.deserialize(json.load(results_file))
        # Delete the job result file
        default_storage.delete(filepath)

        # Unlike BatchQueue, LocalQueue is only aware of the
        # jobs that successfully output their results.
        return return_msg, 'SUCCEEDED'
