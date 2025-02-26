import abc
from datetime import timedelta
from io import BytesIO
import json
from logging import getLogger
from typing import Type

import boto3
from botocore.exceptions import ClientError
from django.conf import settings
from django.core.files.storage import default_storage
from django.utils import timezone
from django.utils.module_loading import import_string
from spacer.messages import JobMsg, JobReturnMsg
from spacer.tasks import process_job

from config.constants import SpacerJobSpec
from jobs.models import Job
from jobs.utils import finish_jobs
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
    def collect_jobs(self, jobs: list) -> tuple[list[JobReturnMsg], list[str]]:
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
    def handle_job_failures(failures):
        if not failures:
            return

        internal_jobs_by_id = Job.objects.in_bulk(
            [batch_job.internal_job_id for batch_job, _ in failures])

        finish_jobs_args = []
        for batch_job, error_message in failures:
            batch_job.status = 'FAILED'
            finish_jobs_args.append(dict(
                job=internal_jobs_by_id[batch_job.internal_job_id],
                success=False,
                result_message=error_message,
            ))

        finish_jobs(finish_jobs_args)

    def get_collectable_jobs(self):
        # Not-yet-collected BatchJobs.
        return (
            BatchJob.objects
            .exclude(status__in=['SUCCEEDED', 'FAILED'])
            .order_by('pk')
        )

    @staticmethod
    def process_response_for_job(job, response_for_job):

        job.status = response_for_job['status']

        if job.status == 'FAILED':
            return dict(
                failure=(job, f"Batch job [{job}] marked as FAILED by AWS."),
                status=job.status,
            )

        if job.status != 'SUCCEEDED':
            # Not done yet, e.g. RUNNING
            return dict(
                status=job.status,
            )

        # Else: 'SUCCEEDED'
        job_res_loc = default_storage.spacer_data_loc(job.res_key)

        try:
            return_msg = JobReturnMsg.load(job_res_loc)
        except (ClientError, IOError) as e:
            # IOError for local storage, ClientError for S3 storage
            message = (
                f"Batch job [{job}] succeeded, but couldn't get"
                f" output at the expected location. ({e})"
            )
            return dict(
                failure=(job, message),
                status='FAILED',
            )

        # All went well.
        return dict(
            result=return_msg,
            status=job.status,
        )

    def collect_jobs(
        self, jobs: list[BatchJob]
    ) -> tuple[list[JobReturnMsg], list[str]]:

        now = timezone.now()
        failures = []
        results = []
        statuses = []
        batch_tokens = []
        job_ids_without_tokens = []

        for job in jobs:
            if job.batch_token:
                batch_tokens.append(job.batch_token)
            else:
                # Didn't get a batch token from AWS Batch. May indicate AWS
                # service problems (see coralnet issue 458) or it may just be
                # unlucky timing between submit and collect. Check the
                # create_date to be sure.
                if now - job.create_date > timedelta(minutes=30):
                    # Likely an AWS service problem.
                    failures.append((
                        job, "Failed to get AWS Batch token."))
                    statuses.append('DROPPED')
                else:
                    # Let's wait a bit longer.
                    statuses.append('NOT SUBMITTED')
                job_ids_without_tokens.append(job.pk)

        # https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/batch/client/describe_jobs.html
        # jobs is "A list of up to 100 job IDs."
        boto_response = self.batch_client.describe_jobs(jobs=batch_tokens)

        batch_tokens_to_responses = dict(
            (response_job['jobId'], response_job)
            for response_job in boto_response['jobs']
        )

        for job in jobs:

            if job.pk in job_ids_without_tokens:
                # Nothing more to do right now without a token.
                continue

            if job.batch_token not in batch_tokens_to_responses:
                failures.append((
                    job, f"Batch job [{job}] not found in AWS."))
                statuses.append('DROPPED')
                continue

            response_for_job = batch_tokens_to_responses[job.batch_token]

            d = self.process_response_for_job(job, response_for_job)
            if 'failure' in d:
                failures.append(d['failure'])
            if 'status' in d:
                statuses.append(d['status'])
            if 'result' in d:
                results.append(d['result'])

        self.handle_job_failures(failures)

        BatchJob.objects.bulk_update(jobs, ['status'])

        return results, statuses


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

    def collect_jobs(
        self, job_filenames: list[str]
    ) -> tuple[list[JobReturnMsg], list[str]]:

        results = []
        statuses = []

        for job_filename in job_filenames:
            # Read the job result message
            filepath = default_storage.path_join(
                'backend_job_res', job_filename)
            with default_storage.open(filepath) as results_file:
                return_msg = JobReturnMsg.deserialize(json.load(results_file))
            # Delete the job result file
            default_storage.delete(filepath)

            # Unlike BatchQueue, LocalQueue is only aware of the
            # jobs that successfully output their results.
            results.append(return_msg)
            statuses.append('SUCCEEDED')

        return results, statuses
