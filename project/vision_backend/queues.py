import abc
import json
import logging
import posixpath
import time
from typing import Optional

import boto
from botocore.exceptions import ClientError
import boto.sqs
import boto3
from django.conf import settings
from django.core.files.storage import get_storage_class
from django.core.mail import mail_admins
from django.utils.module_loading import import_string
from six import StringIO
from spacer.messages import JobMsg, JobReturnMsg
from spacer.tasks import process_job

from vision_backend.models import BatchJob

logger = logging.getLogger(__name__)


def get_queue_class():
    """This function is modeled after Django's get_storage_class()."""

    if settings.SPACER_QUEUE_CHOICE in ['vision_backend.queues.SQSQueue',
                                        'vision_backend.queues.BatchQueue']:
        if settings.DEFAULT_FILE_STORAGE == \
                'lib.storage_backends.MediaStorageLocal':
            logger.error("Bad settings combination of queue and storage")
            raise ValueError('Can not use SQSQueue with local storage. '
                             'Please use S3 storage.')



    return import_string(settings.SPACER_QUEUE_CHOICE)


class BaseQueue(abc.ABC):

    @abc.abstractmethod
    def submit_job(self, job: JobMsg):
        pass

    @abc.abstractmethod
    def collect_job(self) -> Optional[JobReturnMsg]:
        pass


class SQSQueue(BaseQueue):
    """Communicates remotely with Spacer. Requires AWS SQS and S3."""

    def submit_job(self, job: JobMsg):
        """
        Submits message to the SQS spacer_jobs
        """
        raise RuntimeError('SQSQueue no longer supported. '
                           'Please use BatchQueue instead')

        conn = boto.sqs.connect_to_region(
            "us-west-2",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY
        )

        queue = conn.get_queue(settings.SQS_JOBS)
        msg = queue.new_message(body=json.dumps(job.serialize()))
        queue.write(msg)

    def collect_job(self) -> Optional[JobReturnMsg]:
        """
        If an AWS SQS job result is available, collect it, delete from queue
        if it's a job for this server instance, and return it.
        Else, return None.
        """

        # Grab a message
        message = self._read_message(settings.SQS_RES)
        if message is None:
            return None

        return_msg = JobReturnMsg.deserialize(json.loads(message.get_body()))

        # Delete message (at this point, if it is not handled correctly,
        # we still want to delete it from queue.)
        message.delete()

        return return_msg

    @staticmethod
    def _read_message(queue_name):
        """
        helper function for reading messages from AWS SQS.
        """

        conn = boto.sqs.connect_to_region(
            "us-west-2",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY
        )

        queue = conn.get_queue(queue_name)

        message = queue.read()
        if message is None:
            return None
        else:
            return message


class BatchQueue(BaseQueue):

    @staticmethod
    def get_job_name(job_msg: JobMsg):
        """ This gives the job a unique name. It can be useful when browsing
        the AWS Batch console. However, it's only for humans. The actual
        mapping is encoded in the BatchJobs table."""
        return settings.SPACER_JOB_HASH + '-' + \
            job_msg.task_name + '-' + \
            '-'.join([t.job_token for t in job_msg.tasks])

    def submit_job(self, job_msg: JobMsg):

        batch_client = boto3.client(
            'batch',
            region_name="us-west-2",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY
        )

        storage = get_storage_class()()

        batch_job = BatchJob(job_token=self.get_job_name(job_msg))
        batch_job.save()

        job_msg_loc = storage.spacer_data_loc(batch_job.job_key)
        job_msg.store(job_msg_loc)

        job_res_loc = storage.spacer_data_loc(batch_job.res_key)

        resp = batch_client.submit_job(
            jobQueue=settings.BATCH_QUEUE,
            jobName=str(batch_job.pk),
            jobDefinition=settings.BATCH_JOB_DEFINITION,
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

    def collect_job(self) -> Optional[JobReturnMsg]:
        batch_client = boto3.client(
            'batch',
            region_name="us-west-2",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY
        )
        storage = get_storage_class()()

        for job in BatchJob.objects.exclude(status='SUCCEEDED').\
                exclude(status='FAILED'):
            resp = batch_client.describe_jobs(jobs=[job.batch_token])
            job.status = resp['jobs'][0]['status']
            job.save()
            if job.status == 'SUCCEEDED':
                logger.info('Entering collection of job {}.'.format(str(job)))
                job_res_loc = storage.spacer_data_loc(job.res_key)
                try:
                    return_msg = JobReturnMsg.load(job_res_loc)
                    logger.info('Exiting collection of job {}.'.format(
                        str(job)))
                    return return_msg
                except ClientError:
                    # This should not happen. Any errors inside the
                    # job should be handled by spacer and it should still
                    # write a JobReturnMsg to the given location.
                    logger.error("Error loading {}".format(job_res_loc))
                    mail_admins("AWS Batch job {} returned with SUCCEEDED but "
                                "no output found".format(job.batch_token),
                                str(job))
                    job.status = 'FAILED'
                    job.save()
            if job.status == 'FAILED':
                # This should basically never happen. Let's email the admins.
                logger.error("AWS Batch job {} returned with FAILED".
                             format(str(job)))
                mail_admins("AWS Batch job {} returned with FAILED".
                            format(job.batch_token), str(job))
        return None


class LocalQueue(BaseQueue):
    """
    Used for testing the vision-backend Django tasks.
    Uses a local filesystem queue and calls spacer directly.
    """
    def submit_job(self, job: JobMsg):

        # Process the job right away.
        return_msg = process_job(job)

        storage = get_storage_class()()

        # Save as seconds.microseconds to avoid collisions.
        filepath = 'backend_job_res/{timestamp}.json'.\
            format(timestamp=time.time())
        storage.save(filepath, StringIO(json.dumps(return_msg.serialize())))

    def collect_job(self) -> Optional[JobReturnMsg]:
        """
        Read a job result from file storage, consume (delete) it,
        and return it. If no result is available, return None.
        """
        storage = get_storage_class()()
        dir_names, filenames = storage.listdir('backend_job_res')

        if len(filenames) == 0:
            return None

        # Sort by filename, which should also put them in job order
        # because the filenames have timestamps (to microsecond precision)
        filenames.sort()
        # Get the first job result file, so it's like a queue
        filename = filenames[0]
        # Read the job result message
        filepath = posixpath.join('backend_job_res', filename)
        with storage.open(filepath) as results_file:
            return_msg = JobReturnMsg.deserialize(json.load(results_file))
        # Delete the job result file
        storage.delete(filepath)

        return return_msg
