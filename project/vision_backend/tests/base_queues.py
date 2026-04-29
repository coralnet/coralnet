import json

from api_core.models import ApiJob, ApiJobUnit
from jobs.models import Job
from jobs.tasks import run_scheduled_jobs_until_empty
from jobs.tests.utils import JobUtilsMixin
from vision_backend_api.tests.utils import DeployBaseTest
from ..common import ClassifierStatuses
from .tasks.utils import BaseTaskTest


class QueueBasicTest(BaseTaskTest):
    """
    We subclass this for each queue type. Maybe there's a better way
    to 'parameterize' these tests.
    """
    def do_test_no_jobs(self):
        self.do_collect_spacer_jobs()
        self.assert_job_result_message(
            'collect_spacer_jobs', "Jobs checked/collected: 0")

    def do_test_collect_feature_extraction(self):
        img = self.upload_image(self.user, self.source)
        # Submit feature extraction
        run_scheduled_jobs_until_empty()
        # Collect
        self.do_collect_spacer_jobs()
        self.assert_job_result_message(
            'collect_spacer_jobs', "Jobs checked/collected: 1 SUCCEEDED")
        # Check for successful result handling
        self.assertTrue(img.features.extracted)

    def do_test_collect_training(self):
        self.upload_images_for_training()
        # Feature extraction
        run_scheduled_jobs_until_empty()
        self.do_collect_spacer_jobs()
        # Submit training
        run_scheduled_jobs_until_empty()
        # Collect
        self.do_collect_spacer_jobs()
        self.assert_job_result_message(
            'collect_spacer_jobs', "Jobs checked/collected: 1 SUCCEEDED")
        # Check for successful result handling
        latest_classifier = self.source.classifier_set.latest('pk')
        self.assertEqual(
            latest_classifier.status, ClassifierStatuses.ACCEPTED.value)

    def do_test_job_gets_consumed(self):
        """
        collect_spacer_jobs should consume the jobs so that a
        repeat call doesn't see those jobs anymore.
        """
        self.upload_image(self.user, self.source)
        # Submit feature extraction
        run_scheduled_jobs_until_empty()
        # Collect
        self.do_collect_spacer_jobs()
        self.assert_job_result_message(
            'collect_spacer_jobs', "Jobs checked/collected: 1 SUCCEEDED")
        # Collect again; job should already be consumed
        self.do_collect_spacer_jobs()
        self.assert_job_result_message(
            'collect_spacer_jobs', "Jobs checked/collected: 0")


class QueueClassificationTest(DeployBaseTest, JobUtilsMixin):
    """
    We subclass this for each queue type.
    """

    def do_test_collect_classification(self):
        self.set_up_classifier(self.user)
        # Schedule classification
        images = [
            dict(type='image', attributes=dict(
                url='URL 1', points=[dict(row=10, column=10)]))]
        data = json.dumps(dict(data=images))
        self.client.post(self.deploy_url, data, **self.request_kwargs)
        # Submit classification
        self.run_scheduled_jobs_including_deploy()
        # Collect
        self.do_collect_spacer_jobs()
        self.assert_job_result_message(
            'collect_spacer_jobs', "Jobs checked/collected: 1 SUCCEEDED")
        # Check for successful result handling
        unit = ApiJobUnit.objects.latest('pk')
        self.assertEqual(unit.status, Job.Status.SUCCESS)
        self.assertTrue(unit.result_json)

    def do_test_collect_multiple_classification(self):
        self.set_up_classifier(self.user)
        # Schedule classifications
        images = [
            dict(
                type='image',
                attributes=dict(
                    url=f'URL {image_number}',
                    points=[dict(row=10, column=10)],
                )
            )
            for image_number in range(1, 5+1)
        ]
        data = json.dumps(dict(data=images))
        self.client.post(self.deploy_url, data, **self.request_kwargs)
        # Schedule more classifications (separate ApiJob)
        images = [
            dict(
                type='image',
                attributes=dict(
                    url=f'URL {image_number + 5}',
                    points=[dict(row=10, column=10)],
                )
            )
            for image_number in range(1, 3+1)
        ]
        data = json.dumps(dict(data=images))
        self.client.post(self.deploy_url, data, **self.request_kwargs)

        # Submit classifications
        self.run_scheduled_jobs_including_deploy()

        # Collect
        self.do_collect_spacer_jobs()
        self.assert_job_result_message(
            'collect_spacer_jobs', "Jobs checked/collected: 8 SUCCEEDED")

        # Check for successful result handling
        api_jobs = list(ApiJob.objects.all())
        self.assertEqual(api_jobs[0].status, ApiJob.DONE)
        self.assertEqual(api_jobs[1].status, ApiJob.DONE)