import copy
import json

from django.conf import settings
from django.test import override_settings
from django.urls import reverse
from rest_framework import status

from api_core.models import ApiJob, ApiJobUnit
from api_core.tests.utils import BaseAPIPermissionTest
from jobs.models import Job
from .utils import DeployBaseTest


class DeployStatusAccessTest(BaseAPIPermissionTest):

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
        url = reverse('api:deploy_status', args=[job.pk])
        job.delete()

        self.assertNotFound(url, self.user_request_kwargs)

    def test_needs_auth(self):
        job = ApiJob(type='deploy', user=self.user)
        job.save()
        url = reverse('api:deploy_status', args=[job.pk])
        response = self.client.get(url)
        self.assertForbiddenResponse(response)

    def test_post_method_not_allowed(self):
        job = ApiJob(type='deploy', user=self.user)
        job.save()
        url = reverse('api:deploy_status', args=[job.pk])

        response = self.client.post(url, **self.user_request_kwargs)
        self.assertMethodNotAllowedResponse(response)

    def test_job_of_same_user(self):
        job = ApiJob(type='deploy', user=self.user)
        job.save()
        url = reverse('api:deploy_status', args=[job.pk])
        self.assertPermissionGranted(url, self.user_request_kwargs)

    def test_job_of_other_user(self):
        job = ApiJob(type='deploy', user=self.user)
        job.save()
        url = reverse('api:deploy_status', args=[job.pk])
        self.assertNotFound(url, self.user_admin_request_kwargs)

    throttle_test_settings = copy.deepcopy(settings.REST_FRAMEWORK)
    throttle_test_settings['DEFAULT_THROTTLE_RATES']['sustained'] = '3/hour'

    @override_settings(REST_FRAMEWORK=throttle_test_settings)
    def test_throttling(self):
        job = ApiJob(type='deploy', user=self.user)
        job.save()
        url = reverse('api:deploy_status', args=[job.pk])

        for _ in range(3):
            response = self.client.get(url, **self.user_request_kwargs)
            self.assertNotEqual(
                response.status_code, status.HTTP_429_TOO_MANY_REQUESTS,
                "1st-3rd requests should not be throttled")

        response = self.client.get(url, **self.user_request_kwargs)
        self.assertThrottleResponse(
            response, msg="4th request should be denied by throttling")


class DeployStatusEndpointTest(DeployBaseTest):
    """
    Test the deploy status endpoint.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.set_up_classifier(cls.user)

    def schedule_deploy(self):
        self.client.post(
            self.deploy_url, self.deploy_data, **self.request_kwargs)

        job = ApiJob.objects.latest('pk')
        return job

    def get_job_status(self, job):
        status_url = reverse('api:deploy_status', args=[job.pk])
        response = self.client.get(status_url, **self.request_kwargs)
        return response

    def test_no_progress_yet(self):
        job = self.schedule_deploy()
        response = self.get_job_status(job)

        self.assertStatusOK(response)

        self.assertDictEqual(
            response.json(),
            dict(
                data=[
                    dict(
                        type="job",
                        id=str(job.pk),
                        attributes=dict(
                            status="Pending",
                            successes=0,
                            failures=0,
                            total=2))]),
            "Response JSON should be as expected")

        self.assertEqual(
            'application/vnd.api+json', response.get('content-type'),
            "Content type should be as expected")

    def test_some_images_in_progress(self):
        job = self.schedule_deploy()

        # Mark one unit's status as in progress
        job_unit = ApiJobUnit.objects.filter(parent=job).latest('pk')
        job_unit.internal_job.status = Job.Status.IN_PROGRESS
        job_unit.internal_job.save()

        response = self.get_job_status(job)

        self.assertStatusOK(response)

        self.assertDictEqual(
            response.json(),
            dict(
                data=[
                    dict(
                        type="job",
                        id=str(job.pk),
                        attributes=dict(
                            status="In Progress",
                            successes=0,
                            failures=0,
                            total=2))]),
            "Response JSON should be as expected")

    def test_all_images_in_progress(self):
        job = self.schedule_deploy()

        job_units = ApiJobUnit.objects.filter(parent=job)
        for job_unit in job_units:
            job_unit.internal_job.status = Job.Status.IN_PROGRESS
            job_unit.internal_job.save()

        response = self.get_job_status(job)

        self.assertStatusOK(response)

        self.assertDictEqual(
            response.json(),
            dict(
                data=[
                    dict(
                        type="job",
                        id=str(job.pk),
                        attributes=dict(
                            status="In Progress",
                            successes=0,
                            failures=0,
                            total=2))]),
            "Response JSON should be as expected")

    def test_some_images_success(self):
        job = self.schedule_deploy()

        # Mark one unit's status as success
        job_units = ApiJobUnit.objects.filter(parent=job)

        self.assertEqual(job_units.count(), 2)

        unit = job_units[0]
        unit.internal_job.status = Job.Status.SUCCESS
        unit.internal_job.save()

        response = self.get_job_status(job)

        self.assertStatusOK(response)

        self.assertDictEqual(
            response.json(),
            dict(
                data=[
                    dict(
                        type="job",
                        id=str(job.pk),
                        attributes=dict(
                            status="In Progress",
                            successes=1,
                            failures=0,
                            total=2))]),
            "Response JSON should be as expected")

    def test_some_images_failure(self):
        job = self.schedule_deploy()

        # Mark one unit's status as failure
        job_unit = ApiJobUnit.objects.filter(parent=job).latest('pk')
        job_unit.internal_job.status = Job.Status.FAILURE
        job_unit.internal_job.save()

        response = self.get_job_status(job)

        self.assertStatusOK(response)

        self.assertDictEqual(
            response.json(),
            dict(
                data=[
                    dict(
                        type="job",
                        id=str(job.pk),
                        attributes=dict(
                            status="In Progress",
                            successes=0,
                            failures=1,
                            total=2))]),
            "Response JSON should be as expected")

    def test_success(self):
        job = self.schedule_deploy()
        self.run_scheduled_jobs_including_deploy()
        self.do_collect_spacer_jobs()

        response = self.get_job_status(job)

        self.assertEqual(
            response.status_code, status.HTTP_303_SEE_OTHER,
            "Should get 303")

        self.assertEqual(
            response.content.decode(), '',
            "Response content should be empty")

        self.assertEqual(
            response['Location'],
            reverse('api:deploy_result', args=[job.pk]),
            "Location header should be as expected")

    def test_failure(self):
        job = self.schedule_deploy()

        # Mark both units' status as done: one success, one failure.
        #
        # Note: We must bind the units to separate names, since assigning an
        # attribute using an index access (like units[0].status = ...)
        # doesn't seem to work as desired (the attribute doesn't change).
        unit_1, unit_2 = ApiJobUnit.objects.filter(parent=job)
        unit_1.internal_job.status = Job.Status.SUCCESS
        unit_1.internal_job.save()
        unit_2.internal_job.status = Job.Status.FAILURE
        unit_2.internal_job.save()

        response = self.get_job_status(job)

        self.assertEqual(
            response.status_code, status.HTTP_303_SEE_OTHER,
            "Should get 303")

        self.assertEqual(
            response.content.decode(), '',
            "Response content should be empty")

        self.assertEqual(
            response['Location'],
            reverse('api:deploy_result', args=[job.pk]),
            "Location header should be as expected")
