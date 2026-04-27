from datetime import timedelta
import json
from unittest import mock

from django.test.utils import override_settings
from spacer.data_classes import DataLocation
from spacer.messages import JobMsg
from spacer.tasks import process_job

from jobs.models import Job
from jobs.tasks import run_scheduled_jobs_until_empty
from vision_backend.models import BatchJob
from vision_backend.tests.tasks.utils import BaseTaskTest
from vision_backend.tests.base_queues import (
    QueueBasicTest, QueueClassificationTest)


def batch_queue_decorator(func):
    deco = override_settings(
        SPACER_QUEUE_CHOICE='aws.queues.BatchQueue')
    return deco(func)


class MockBotoClient:

    def __init__(self, response_type):
        self.response_type = response_type
        self.jobId = 0
        self.jobs = dict()

    def submit_job(self, containerOverrides=None, **kwargs):
        self.jobId += 1

        # Simulate different scenarios based on self.response_type.

        if self.response_type == 'no_batch_token':
            # Return a None batch_token
            return dict(jobId=None)

        if self.response_type == 'no_describe':
            # Leave this job out of self.jobs, so that it's not returned
            # by describe_jobs()
            return dict(jobId=self.jobId)

        if self.response_type == 'failed':
            status = 'FAILED'
        elif self.response_type == 'running':
            status = 'RUNNING'
        elif self.response_type == 'mixed_status':
            statuses = [
                'FAILED', 'RUNNING', 'SUCCEEDED',
                'FAILED', 'SUCCEEDED', 'SUCCEEDED',
            ]
            # Submitting 6 jobs in a row should get the above
            # set of statuses.
            status = statuses[self.jobId % 6]
        else:
            status = 'SUCCEEDED'

        self.jobs[str(self.jobId)] = status

        if self.response_type == 'no_result_storage':
            # Don't store the result in the expected storage
            return dict(jobId=self.jobId)

        # Get the storage locations
        environment = dict()
        for d in containerOverrides['environment']:
            environment[d['name']] = d['value']
        job_msg_loc = DataLocation.deserialize(
            json.loads(environment['JOB_MSG_LOC']))
        res_msg_loc = DataLocation.deserialize(
            json.loads(environment['RES_MSG_LOC']))

        # Load message, process job, store result message
        job_msg = JobMsg.load(job_msg_loc)
        return_msg = process_job(job_msg)
        return_msg.store(res_msg_loc)

        return dict(jobId=self.jobId)

    def describe_jobs(self, jobs=None):
        jobs_to_return = []

        for batch_token in jobs:
            if batch_token not in self.jobs:
                continue
            jobs_to_return.append(dict(
                jobId=batch_token,
                status=self.jobs[batch_token],
            ))

        return dict(jobs=jobs_to_return)


def mock_boto_client(response_type='succeeded'):
    """
    For testing BatchQueue without connecting to AWS.

    Use this as a context manager. Each usage of this context manager
    gets its own mock-boto-client instance. Make sure the instance is the
    same from job-submit time to job-collect time.
    """
    client = MockBotoClient(response_type)

    def get_mock_client():
        return client

    return mock.patch('aws.queues.get_batch_client', get_mock_client)


@batch_queue_decorator
class BatchQueueBasicTest(QueueBasicTest):

    def test_no_jobs(self):
        with mock_boto_client():
            self.do_test_no_jobs()

    def test_collect_feature_extraction(self):
        with mock_boto_client():
            self.do_test_collect_feature_extraction()

    def test_collect_training(self):
        with mock_boto_client():
            self.do_test_collect_training()

    def test_job_gets_consumed(self):
        with mock_boto_client():
            self.do_test_job_gets_consumed()

    def test_feature_extraction_fail(self):
        """A feature extraction job can't be collected."""
        self.upload_image(self.user, self.source)

        with mock_boto_client('failed'):
            # Submit feature extraction
            run_scheduled_jobs_until_empty()
            # Collect
            self.do_collect_spacer_jobs()
            self.assert_job_result_message(
                'collect_spacer_jobs', "Jobs checked/collected: 1 FAILED")

        # Check for error status
        job = Job.objects.get(job_name='extract_features')
        self.assertEqual(job.status, Job.Status.FAILURE)

    def test_training_fail(self):
        """A training job can't be collected."""
        self.upload_images_for_training()

        with mock_boto_client():
            # Feature extraction
            run_scheduled_jobs_until_empty()
            self.do_collect_spacer_jobs()

        with mock_boto_client('failed'):
            # Submit training
            run_scheduled_jobs_until_empty()
            # Collect
            self.do_collect_spacer_jobs()
            self.assert_job_result_message(
                'collect_spacer_jobs', "Jobs checked/collected: 1 FAILED")

        # Check for error status
        job = Job.objects.get(job_name='train_classifier')
        self.assertEqual(job.status, Job.Status.FAILURE)


@batch_queue_decorator
class BatchQueueClassificationTest(QueueClassificationTest):

    def test_collect_classification(self):
        with mock_boto_client():
            self.do_test_collect_classification()

    def test_collect_multiple_classification(self):
        with mock_boto_client():
            self.do_test_collect_multiple_classification()

    def test_classification_fail(self):
        """A classification job can't be collected."""
        with mock_boto_client():
            self.set_up_classifier(self.user)

        # Schedule classification
        images = [
            dict(type='image', attributes=dict(
                url='URL 1', points=[dict(row=10, column=10)]))]
        data = json.dumps(dict(data=images))
        self.client.post(self.deploy_url, data, **self.request_kwargs)

        with mock_boto_client('failed'):
            # Submit classification
            self.run_scheduled_jobs_including_deploy()
            # Collect
            self.do_collect_spacer_jobs()
            self.assert_job_result_message(
                'collect_spacer_jobs', "Jobs checked/collected: 1 FAILED")

        # Check for error status
        job = Job.objects.get(job_name='classify_image')
        self.assertEqual(job.status, Job.Status.FAILURE)


@batch_queue_decorator
class BatchQueueSpecificsTest(BaseTaskTest):

    def extract_and_assert_collect_count(self, expected_counts_str):
        # Submit feature extraction
        run_scheduled_jobs_until_empty()
        # Collect
        self.do_collect_spacer_jobs()
        self.assert_job_result_message(
            'collect_spacer_jobs',
            f"Jobs checked/collected: {expected_counts_str}")

    def assert_job_error(self, expected_error_template):
        # Check for error status
        batch_job = BatchJob.objects.latest('pk')
        job = Job.objects.get(job_name='extract_features')

        if '{batch_job}' in expected_error_template:
            expected_error = expected_error_template.format(
                batch_job=batch_job)
        else:
            expected_error = expected_error_template

        self.assertEqual(job.result_message, expected_error)

    def test_job_in_progress(self):
        """BatchJob has not succeeded or failed yet; still in progress."""
        self.upload_image(self.user, self.source)

        with mock_boto_client('running'):
            self.extract_and_assert_collect_count("1 RUNNING")

    def test_batch_token_none(self):
        """BatchJob's batch_token is None."""
        self.upload_image(self.user, self.source)

        with mock_boto_client('no_batch_token'):
            run_scheduled_jobs_until_empty()

            # Try to collect
            self.do_collect_spacer_jobs()
            self.assert_job_result_message(
                'collect_spacer_jobs',
                "Jobs checked/collected: 1 NOT SUBMITTED")

            # Make the BatchJob old enough to be considered a victim of
            # an AWS service error.
            batch_job = BatchJob.objects.latest('pk')
            batch_job.create_date = \
                batch_job.create_date - timedelta(minutes=60)
            batch_job.save()

            # Then try to collect again.
            self.do_collect_spacer_jobs()
            self.assert_job_result_message(
                'collect_spacer_jobs',
                "Jobs checked/collected: 1 DROPPED")

        self.assert_job_error("Failed to get AWS Batch token.")

    def test_batch_job_not_in_aws(self):
        """Querying AWS Batch for the batch_token gets nothing."""
        self.upload_image(self.user, self.source)

        with mock_boto_client('no_describe'):
            self.extract_and_assert_collect_count("1 DROPPED")
        self.assert_job_error("Batch job [{batch_job}] not found in AWS.")

    def test_batch_job_failed_in_aws(self):
        """AWS Batch marked the job as failed."""
        self.upload_image(self.user, self.source)

        with mock_boto_client('failed'):
            self.extract_and_assert_collect_count("1 FAILED")
        self.assert_job_error(
            "Batch job [{batch_job}] marked as FAILED by AWS.")

    def test_could_not_get_job_output(self):
        """
        AWS Batch marked the job as succeeded, but we can't get the
        output (may be a file, etc.)
        """
        self.upload_image(self.user, self.source)

        with mock_boto_client('no_result_storage'):
            self.extract_and_assert_collect_count("1 FAILED")

        # It's cumbersome to assert on the entire error message, so
        # just check the beginning.
        batch_job = BatchJob.objects.latest('pk')
        job = Job.objects.get(job_name='extract_features')
        expected_error_beginning = (
            f"Batch job [{batch_job}] succeeded,"
            f" but couldn't get output at the expected location."
        )
        self.assertIn(
            expected_error_beginning, job.result_message)

    def test_statuses_summary(self):
        for _ in range(6):
            self.upload_image(self.user, self.source)

        with mock_boto_client('mixed_status'):
            self.extract_and_assert_collect_count(
                "2 FAILED, 1 RUNNING, 3 SUCCEEDED")
