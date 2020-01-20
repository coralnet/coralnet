from __future__ import unicode_literals
import copy
import json
from unittest import skip

from django.conf import settings
from django.test import override_settings
from django.urls import reverse
from mock import patch
from rest_framework import status

from api_core.models import ApiJob, ApiJobUnit
from api_core.tests.utils import BaseAPIPermissionTest
from .utils import DeployBaseTest, noop_task


class DeployStatusAccessTest(BaseAPIPermissionTest):

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
        url = reverse('api:deploy_status', args=[job.pk])
        job.delete()

        self.assertNotFound(url, self.user_token_headers)

    def test_needs_auth(self):
        job = ApiJob(type='deploy', user=self.user)
        job.save()
        url = reverse('api:deploy_status', args=[job.pk])
        self.assertNeedsAuth(url)

    def test_post_method_not_allowed(self):
        job = ApiJob(type='deploy', user=self.user)
        job.save()
        url = reverse('api:deploy_status', args=[job.pk])

        response = self.client.post(url, **self.user_token_headers)
        self.assertEqual(
            response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED,
            "Should get 405")

    def test_job_of_same_user(self):
        job = ApiJob(type='deploy', user=self.user)
        job.save()
        url = reverse('api:deploy_status', args=[job.pk])
        self.assertPermissionGranted(url, self.user_token_headers)

    def test_job_of_other_user(self):
        job = ApiJob(type='deploy', user=self.user)
        job.save()
        url = reverse('api:deploy_status', args=[job.pk])
        self.assertNotFound(url, self.user_admin_token_headers)

    throttle_test_settings = copy.deepcopy(settings.REST_FRAMEWORK)
    throttle_test_settings['DEFAULT_THROTTLE_RATES']['sustained'] = '3/hour'

    @override_settings(REST_FRAMEWORK=throttle_test_settings)
    def test_throttling(self):
        job = ApiJob(type='deploy', user=self.user)
        job.save()
        url = reverse('api:deploy_status', args=[job.pk])

        for _ in range(3):
            response = self.client.get(url, **self.user_token_headers)
            self.assertNotEqual(
                response.status_code, status.HTTP_429_TOO_MANY_REQUESTS,
                "1st-3rd requests should not be throttled")

        response = self.client.get(url, **self.user_token_headers)
        self.assertEqual(
            response.status_code, status.HTTP_429_TOO_MANY_REQUESTS,
            "4th request should be denied by throttling")


class DeployStatusEndpointTest(DeployBaseTest):
    """
    Test the deploy status endpoint.
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

    def get_job_status(self, job):
        status_url = reverse('api:deploy_status', args=[job.pk])
        response = self.client.get(status_url, **self.token_headers)
        return response

    @patch('vision_backend_api.views.deploy.run', noop_task)
    def test_no_progress_yet(self):
        job = self.deploy()
        response = self.get_job_status(job)

        self.assertStatusOK(response)

        self.assertDictEqual(
            response.json(),
            dict(
                data=dict(
                    status="Pending",
                    successes=0,
                    failures=0,
                    total=2)),
            "Response JSON should be as expected")

    @patch('vision_backend_api.views.deploy.run', noop_task)
    def test_some_images_working(self):
        job = self.deploy()

        # Mark one feature-extract unit's status as working
        features_job_unit = ApiJobUnit.objects.filter(
            job=job, type='deploy').latest('pk')
        features_job_unit.status = ApiJobUnit.IN_PROGRESS
        features_job_unit.save()

        response = self.get_job_status(job)

        self.assertStatusOK(response)

        self.assertDictEqual(
            response.json(),
            dict(
                data=dict(
                    status="In Progress",
                    successes=0,
                    failures=0,
                    total=2)),
            "Response JSON should be as expected")

    @patch('vision_backend.tasks.deploy.run', noop_task)
    def test_features_extracted(self):
        job = self.deploy()
        response = self.get_job_status(job)

        self.assertStatusOK(response)

        self.assertDictEqual(
            response.json(),
            dict(
                data=dict(
                    status="Pending",
                    successes=0,
                    failures=0,
                    total=2)),
            "Response JSON should be as expected")

    @patch('vision_backend.tasks.deploy.run', noop_task)
    def test_some_images_success(self):
        job = self.deploy()

        # Mark one classify unit's status as success
        job_units = ApiJobUnit.objects.filter(job=job, type='deploy')

        self.assertEqual(job_units.count(), 2)

        ju = job_units[0]
        ju.status = ApiJobUnit.SUCCESS
        ju.save()

        response = self.get_job_status(job)

        self.assertStatusOK(response)

        self.assertDictEqual(
            response.json(),
            dict(
                data=dict(
                    status="In Progress",
                    successes=1,
                    failures=0,
                    total=2)),
            "Response JSON should be as expected")

    @patch('vision_backend.tasks.deploy.run', noop_task)
    def test_some_images_failure(self):
        job = self.deploy()

        # Mark one classify unit's status as failure
        classify_job_unit = ApiJobUnit.objects.filter(
            job=job, type='deploy').latest('pk')
        classify_job_unit.status = ApiJobUnit.FAILURE
        classify_job_unit.save()

        response = self.get_job_status(job)

        self.assertStatusOK(response)

        self.assertDictEqual(
            response.json(),
            dict(
                data=dict(
                    status="In Progress",
                    successes=0,
                    failures=1,
                    total=2)),
            "Response JSON should be as expected")

    @skip("Need to have a mock backend before testing.")
    def test_success(self):
        job = self.deploy()
        response = self.get_job_status(job)

        self.assertEqual(
            response.status_code, status.HTTP_303_SEE_OTHER,
            "Should get 303")

        self.assertEqual(
            response.content, '',
            "Response content should be empty")

        self.assertEqual(
            response['Location'],
            reverse('api:deploy_result', args=[job.pk]),
            "Location header should be as expected")

    @patch('vision_backend.tasks.deploy.run', noop_task)
    def test_failure(self):
        job = self.deploy()

        # Mark both classify units' status as done: one success, one failure.
        #
        # Note: We must bind the units to separate names, since assigning an
        # attribute using an index access (like units[0].status = 'SC')
        # doesn't seem to work as desired (the attribute doesn't change).
        unit_1, unit_2 = ApiJobUnit.objects.filter(
            job=job, type='deploy')
        unit_1.status = ApiJobUnit.SUCCESS
        unit_1.save()
        unit_2.status = ApiJobUnit.FAILURE
        unit_2.save()

        response = self.get_job_status(job)

        self.assertEqual(
            response.status_code, status.HTTP_303_SEE_OTHER,
            "Should get 303")

        self.assertEqual(
            response.content, '',
            "Response content should be empty")

        self.assertEqual(
            response['Location'],
            reverse('api:deploy_result', args=[job.pk]),
            "Location header should be as expected")
