import copy
import json
import operator

from django.conf import settings
from django.test import override_settings
from django.urls import reverse
from rest_framework import status

from api_core.models import ApiJob, ApiJobUnit
from api_core.tests.utils import BaseAPIPermissionTest
from jobs.models import Job
from vision_backend.tests.tasks.utils import do_collect_spacer_jobs
from .utils import DeployBaseTest


class DeployResultAccessTest(BaseAPIPermissionTest):

    def assertNotFound(self, url, request_kwargs):
        response = self.client.get(url, **request_kwargs)
        self.assertEqual(
            response.status_code, status.HTTP_404_NOT_FOUND,
            "Should get 404")
        detail = "This deploy job doesn't exist or is not accessible"
        self.assertDictEqual(
            response.json(),
            dict(errors=[dict(detail=detail)]),
            "Response JSON should be as expected")

    def assertPermissionGranted(self, url, request_kwargs):
        response = self.client.get(url, **request_kwargs)
        self.assertNotEqual(
            response.status_code, status.HTTP_404_NOT_FOUND,
            "Should not get 404")
        self.assertNotEqual(
            response.status_code, status.HTTP_403_FORBIDDEN,
            "Should not get 403")

    def test_nonexistent_job(self):
        # To secure an ID which corresponds to no job, we
        # delete a previously existing job.
        job = ApiJob(type='deploy', user=self.user)
        job.save()
        url = reverse('api:deploy_result', args=[job.pk])
        job.delete()

        self.assertNotFound(url, self.user_request_kwargs)

    def test_needs_auth(self):
        job = ApiJob(type='deploy', user=self.user)
        job.save()
        url = reverse('api:deploy_result', args=[job.pk])
        response = self.client.get(url)
        self.assertForbiddenResponse(response)

    def test_post_method_not_allowed(self):
        job = ApiJob(type='deploy', user=self.user)
        job.save()
        url = reverse('api:deploy_result', args=[job.pk])

        response = self.client.post(url, **self.user_request_kwargs)
        self.assertMethodNotAllowedResponse(response)

    def test_job_of_same_user(self):
        job = ApiJob(type='deploy', user=self.user)
        job.save()
        url = reverse('api:deploy_result', args=[job.pk])
        self.assertPermissionGranted(url, self.user_request_kwargs)

    def test_job_of_other_user(self):
        job = ApiJob(type='deploy', user=self.user)
        job.save()
        url = reverse('api:deploy_result', args=[job.pk])
        self.assertNotFound(url, self.user_admin_request_kwargs)

    throttle_test_settings = copy.deepcopy(settings.REST_FRAMEWORK)
    throttle_test_settings['DEFAULT_THROTTLE_RATES']['sustained'] = '3/hour'

    @override_settings(REST_FRAMEWORK=throttle_test_settings)
    def test_throttling(self):
        job = ApiJob(type='deploy', user=self.user)
        job.save()
        url = reverse('api:deploy_result', args=[job.pk])

        for _ in range(3):
            response = self.client.get(url, **self.user_request_kwargs)
            self.assertNotEqual(
                response.status_code, status.HTTP_429_TOO_MANY_REQUESTS,
                "1st-3rd requests should not be throttled")

        response = self.client.get(url, **self.user_request_kwargs)
        self.assertThrottleResponse(
            response, msg="4th request should be denied by throttling")


class DeployResultEndpointTest(DeployBaseTest):
    """
    Test the deploy result endpoint.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.set_up_classifier(cls.user)

        images = [
            dict(
                type='image',
                attributes=dict(
                    url='URL 1',
                    points=[
                        dict(row=10, column=10),
                        dict(row=20, column=5),
                    ])),
            dict(
                type='image',
                attributes=dict(
                    url='URL 2',
                    points=[
                        dict(row=10, column=10),
                    ])),
        ]
        cls.data = json.dumps(dict(data=images))

    def schedule_deploy(self):
        self.client.post(self.deploy_url, self.data, **self.request_kwargs)
        job = ApiJob.objects.latest('pk')
        return job

    def get_job_result(self, job):
        result_url = reverse('api:deploy_result', args=[job.pk])
        response = self.client.get(result_url, **self.request_kwargs)
        return response

    def assert_result_response_not_finished(self, response):
        self.assertEqual(
            response.status_code, status.HTTP_409_CONFLICT,
            "Should get 409")

        self.assertDictEqual(
            response.json(),
            dict(errors=[
                dict(detail="This job isn't finished yet")]),
            "Response JSON should be as expected")

    def test_no_progress_yet(self):
        job = self.schedule_deploy()
        response = self.get_job_result(job)

        self.assert_result_response_not_finished(response)

    def test_some_images_in_progress(self):
        job = self.schedule_deploy()

        # Mark one unit's status as in progress
        job_unit = ApiJobUnit.objects.filter(parent=job).latest('pk')
        job_unit.internal_job.status = Job.Status.IN_PROGRESS
        job_unit.internal_job.save()

        response = self.get_job_result(job)

        self.assert_result_response_not_finished(response)

    def test_all_images_in_progress(self):
        job = self.schedule_deploy()

        job_units = ApiJobUnit.objects.filter(parent=job)
        for job_unit in job_units:
            job_unit.internal_job.status = Job.Status.IN_PROGRESS
            job_unit.internal_job.save()

        response = self.get_job_result(job)

        self.assert_result_response_not_finished(response)

    def test_some_images_success(self):
        job = self.schedule_deploy()

        # Mark one unit's status as success
        job_unit = ApiJobUnit.objects.filter(parent=job).latest('pk')
        job_unit.internal_job.status = Job.Status.SUCCESS
        job_unit.internal_job.save()

        response = self.get_job_result(job)

        self.assert_result_response_not_finished(response)

    def test_some_images_failure(self):
        job = self.schedule_deploy()

        # Mark one unit's status as failure
        job_unit = ApiJobUnit.objects.filter(parent=job).latest('pk')
        job_unit.internal_job.status = Job.Status.FAILURE
        job_unit.internal_job.save()

        response = self.get_job_result(job)

        self.assert_result_response_not_finished(response)

    def test_success(self):
        job = self.schedule_deploy()
        self.run_scheduled_jobs_including_deploy()
        do_collect_spacer_jobs()

        response = self.get_job_result(job)

        self.assertStatusOK(response)

        # Check the response content. The classifications can vary, so this
        # will take some doing.

        points_1_without_classifications = [
            dict(row=10, column=10),
            dict(row=20, column=5),
        ]
        points_2_without_classifications = [
            dict(row=10, column=10),
        ]

        response_json = response.json()
        point_classifications = [
            response_json['data'][0]['attributes']['points'][0]
                .pop('classifications'),
            response_json['data'][0]['attributes']['points'][1]
                .pop('classifications'),
            response_json['data'][1]['attributes']['points'][0]
                .pop('classifications'),
        ]
        response_json_without_classifications = response_json

        self.assertDictEqual(
            response_json_without_classifications,
            dict(
                data=[
                    dict(
                        type='image',
                        id='URL 1',
                        attributes=dict(
                            url='URL 1',
                            points=points_1_without_classifications),
                    ),
                    dict(
                        type='image',
                        id='URL 2',
                        attributes=dict(
                            url='URL 2',
                            points=points_2_without_classifications),
                    ),
                ]),
            "Response JSON besides classifications should be as expected")

        # The following is an example of what a point's classifications may
        # look like, but the label order or scores may vary.
        # [
        #     dict(
        #         label_id=self.labels_by_name['B'].pk, label_name='B',
        #         label_code='B_mycode', score=0.5),
        #     dict(
        #         label_id=self.labels_by_name['A'].pk, label_name='A',
        #         label_code='A_mycode', score=0.5),
        # ]

        for point_classification in point_classifications:
            scores = [
                label_dict.pop('score') for label_dict in point_classification]
            self.assertAlmostEqual(
                1.0, sum(scores), places=3,
                msg="Scores for each point should add up to 1")
            self.assertGreaterEqual(
                scores[0], scores[1], "Scores should be in descending order")

            point_classification_without_scores = point_classification
            point_classification_without_scores.sort(
                key=operator.itemgetter('label_name'))
            self.assertListEqual(
                [
                    dict(
                        label_id=self.labels_by_name['A'].pk, label_name='A',
                        label_code='A_mycode'),
                    dict(
                        label_id=self.labels_by_name['B'].pk, label_name='B',
                        label_code='B_mycode'),
                ],
                point_classification_without_scores,
                "Classifications JSON besides scores should be as expected")

    def test_failure(self):
        job = self.schedule_deploy()

        # Mark both units' status as done: one success, one failure.
        unit_1, unit_2 = ApiJobUnit.objects.filter(
            parent=job).order_by('order_in_parent')

        unit_1.internal_job.status = Job.Status.SUCCESS
        unit_1.internal_job.save()
        classifications = [dict(
            label_id=self.labels_by_name['A'].pk, label_name='A',
            label_code='A_mycode', score=1.0)]
        points_1 = [
            dict(
                row=10, column=10,
                classifications=classifications,
            ),
            dict(
                row=20, column=5,
                classifications=classifications,
            ),
        ]
        unit_1.result_json = dict(
            url='URL 1', points=points_1)
        unit_1.save()

        unit_2.internal_job.status = Job.Status.FAILURE
        unit_2.internal_job.result_message = (
            "Classifier of id 33 does not exist.")
        unit_2.internal_job.save()

        response = self.get_job_result(job)

        self.assertStatusOK(response)

        self.assertDictEqual(
            response.json(),
            dict(
                data=[
                    dict(
                        type='image',
                        id='URL 1',
                        attributes=dict(url='URL 1', points=points_1),
                    ),
                    dict(
                        type='image',
                        id='URL 2',
                        attributes=dict(
                            url='URL 2',
                            errors=[
                                "Classifier of id 33 does not exist."]),
                    ),
                ]),
            "Response JSON should be as expected")

        self.assertEqual(
            'application/vnd.api+json', response.get('content-type'),
            "Content type should be as expected")
