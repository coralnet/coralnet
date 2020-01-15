from __future__ import unicode_literals
import copy
import json

from django.conf import settings
from django.test import override_settings
from django.urls import reverse
from mock import patch
from rest_framework import status

from api_core.models import ApiJob, ApiJobUnit
from api_core.tests.utils import BaseAPIPermissionTest
from .utils import DeployBaseTest, noop_task


class DeployResultAccessTest(BaseAPIPermissionTest):

    def assertNotFound(self, url, token_headers):
        response = self.client.get(url, **token_headers)
        self.assertEqual(
            response.status_code, status.HTTP_404_NOT_FOUND,
            "Should get 404")
        detail = "This deploy job doesn't exist or is not accessible"
        self.assertDictEqual(
            response.json(),
            dict(errors=[dict(detail=detail)]),
            "Response JSON should be as expected")

    def assertPermissionGranted(self, url, token_headers):
        response = self.client.get(url, **token_headers)
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

        self.assertNotFound(url, self.user_token_headers)

    def test_needs_auth(self):
        job = ApiJob(type='deploy', user=self.user)
        job.save()
        url = reverse('api:deploy_result', args=[job.pk])
        self.assertNeedsAuth(url)

    def test_post_method_not_allowed(self):
        job = ApiJob(type='deploy', user=self.user)
        job.save()
        url = reverse('api:deploy_result', args=[job.pk])

        response = self.client.post(url, **self.user_token_headers)
        self.assertEqual(
            response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED,
            "Should get 405")

    def test_job_of_same_user(self):
        job = ApiJob(type='deploy', user=self.user)
        job.save()
        url = reverse('api:deploy_result', args=[job.pk])
        self.assertPermissionGranted(url, self.user_token_headers)

    def test_job_of_other_user(self):
        job = ApiJob(type='deploy', user=self.user)
        job.save()
        url = reverse('api:deploy_result', args=[job.pk])
        self.assertNotFound(url, self.user_admin_token_headers)

    throttle_test_settings = copy.deepcopy(settings.REST_FRAMEWORK)
    throttle_test_settings['DEFAULT_THROTTLE_RATES']['sustained'] = '3/hour'

    @override_settings(REST_FRAMEWORK=throttle_test_settings)
    def test_throttling(self):
        job = ApiJob(type='deploy', user=self.user)
        job.save()
        url = reverse('api:deploy_result', args=[job.pk])

        for _ in range(3):
            response = self.client.get(url, **self.user_token_headers)
            self.assertNotEqual(
                response.status_code, status.HTTP_429_TOO_MANY_REQUESTS,
                "1st-3rd requests should not be throttled")

        response = self.client.get(url, **self.user_token_headers)
        self.assertEqual(
            response.status_code, status.HTTP_429_TOO_MANY_REQUESTS,
            "4th request should be denied by throttling")


class DeployResultEndpointTest(DeployBaseTest):
    """
    Test the deploy result endpoint.
    """
    def setUp(self):
        self.data = dict(images=json.dumps([
            dict(url='URL 1', points=[
                dict(row=10, column=10),
                dict(row=20, column=5),
            ]),
            dict(url='URL 2', points=[
                dict(row=10, column=10),
            ]),
        ]))

    def deploy(self):
        self.client.post(self.deploy_url, self.data, **self.token_headers)
        job = ApiJob.objects.latest('pk')
        return job

    def get_job_result(self, job):
        result_url = reverse('api:deploy_result', args=[job.pk])
        response = self.client.get(result_url, **self.token_headers)
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

    @patch('vision_backend_api.views.deploy_extract_features.run', noop_task)
    def test_no_progress_yet(self):
        job = self.deploy()
        response = self.get_job_result(job)

        self.assert_result_response_not_finished(response)

    @patch('vision_backend_api.views.deploy_extract_features.run', noop_task)
    def test_some_images_working(self):
        job = self.deploy()

        # Mark one feature-extract unit's status as working
        features_job_unit = ApiJobUnit.objects.filter(
            job=job, type='deploy_extract_features').latest('pk')
        features_job_unit.status = ApiJobUnit.IN_PROGRESS
        features_job_unit.save()

        response = self.get_job_result(job)

        self.assert_result_response_not_finished(response)

    @patch('vision_backend_api.tasks.deploy_classify.run', noop_task)
    def test_features_extracted(self):
        job = self.deploy()
        response = self.get_job_result(job)

        self.assert_result_response_not_finished(response)

    @patch('vision_backend_api.tasks.deploy_classify.run', noop_task)
    def test_some_images_success(self):
        job = self.deploy()

        # Mark one classify unit's status as success
        classify_job_unit = ApiJobUnit.objects.filter(
            job=job, type='deploy_classify').latest('pk')
        classify_job_unit.status = ApiJobUnit.SUCCESS
        classify_job_unit.save()

        response = self.get_job_result(job)

        self.assert_result_response_not_finished(response)

    @patch('vision_backend_api.tasks.deploy_classify.run', noop_task)
    def test_some_images_failure(self):
        job = self.deploy()

        # Mark one classify unit's status as failure
        classify_job_unit = ApiJobUnit.objects.filter(
            job=job, type='deploy_classify').latest('pk')
        classify_job_unit.status = ApiJobUnit.FAILURE
        classify_job_unit.save()

        response = self.get_job_result(job)

        self.assert_result_response_not_finished(response)

    def test_success(self):
        job = self.deploy()
        response = self.get_job_result(job)

        self.assertStatusOK(response)

        classifications = [dict(
            label_id=self.labels[0].pk, label_name='A',
            default_code='A', score=1.0)]
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
        points_2 = [dict(
            row=10, column=10,
            classifications=classifications,
        )]
        self.assertDictEqual(
            response.json(),
            dict(
                data=dict(
                    images=[
                        dict(url='URL 1', points=points_1),
                        dict(url='URL 2', points=points_2),
                    ])),
            "Response JSON should be as expected")

    @patch('vision_backend_api.tasks.deploy_classify.run', noop_task)
    def test_failure(self):
        job = self.deploy()

        # Mark both classify units' status as done: one success, one failure.
        unit_1, unit_2 = ApiJobUnit.objects.filter(
            job=job, type='deploy_classify').order_by('pk')

        unit_1.status = ApiJobUnit.SUCCESS
        classifications = [dict(
            label_id=self.labels[0].pk, label_name='A',
            default_code='A', score=1.0)]
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

        unit_2.status = ApiJobUnit.FAILURE
        url_2_errors = ["Classifier of id 33 does not exist."]
        unit_2.result_json = dict(
            url='URL 2', errors=url_2_errors)
        unit_2.save()

        response = self.get_job_result(job)

        self.assertStatusOK(response)

        self.assertDictEqual(
            response.json(),
            dict(
                data=dict(
                    images=[
                        dict(url='URL 1', points=points_1),
                        dict(url='URL 2', errors=url_2_errors),
                    ])),
            "Response JSON should be as expected")
