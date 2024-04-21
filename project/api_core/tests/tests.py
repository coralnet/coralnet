import copy
import datetime
import json

from django.conf import settings
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from jobs.models import Job
from jobs.tests.utils import do_job
from lib.tests.utils import ClientTest
from ..models import ApiJob, ApiJobUnit
from .utils import BaseAPITest


class AuthTest(BaseAPITest):
    """
    Test API authentication.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user(
            username='testuser', password='SamplePassword')
        cls.source = cls.create_source(cls.user)
        cls.classifier = cls.create_robot(cls.source)

    def test_no_auth(self):
        # Don't log in or anything
        url = reverse('api:deploy', args=[self.classifier.pk])
        response = self.client.post(url)

        # Endpoints unrelated to getting API tokens should require auth
        self.assertForbiddenResponse(response)

    def test_session_auth(self):
        # Log in like we would for non-API requests
        self.client.force_login(self.user)

        url = reverse('api:deploy', args=[self.classifier.pk])
        response = self.client.post(url)
        self.assertNotEqual(
            response.status_code, status.HTTP_403_FORBIDDEN,
            "Session auth should work")

    def test_token_auth(self):
        # Get a token
        response = self.client.post(
            reverse('api:token_auth'),
            data='{"username": "testuser", "password": "SamplePassword"}',
            content_type='application/vnd.api+json',
        )
        token = response.json()['token']

        url = reverse('api:deploy', args=[self.classifier.pk])
        response = self.client.post(
            url, HTTP_AUTHORIZATION='Token {token}'.format(token=token))
        self.assertNotEqual(
            response.status_code, status.HTTP_403_FORBIDDEN,
            "Token auth should work")

    def test_token_response(self):
        response = self.client.post(
            reverse('api:token_auth'),
            data='{"username": "testuser", "password": "SamplePassword"}',
            content_type='application/vnd.api+json',
        )
        response_json = response.json()
        self.assertIn(
            'token', response_json, "Response should have a token member")
        self.assertEqual(
            len(response_json), 1,
            "Response should have no other top-level members")
        self.assertEqual(
            'application/vnd.api+json', response.get('content-type'),
            "Content type should be as expected")


class ContentTypeTest(BaseAPITest):
    """
    Test API content type checks.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user(
            username='testuser', password='SamplePassword')
        cls.source = cls.create_source(cls.user)
        cls.classifier = cls.create_robot(cls.source)

        # Get a token
        response = cls.client.post(
            reverse('api:token_auth'),
            data='{"username": "testuser", "password": "SamplePassword"}',
            content_type='application/vnd.api+json',
        )
        cls.token = response.json()['token']

    def test_token_auth_wrong_content_type(self):
        response = self.client.post(
            reverse('api:token_auth'),
            data='{"username": "testuser", "password": "SamplePassword"}',
            content_type='application/json',
        )

        self.assertEqual(
            response.status_code, status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Should get 415")
        detail = (
            "Content type should be application/vnd.api+json,"
            " not application/json")
        self.assertDictEqual(
            response.json(), dict(errors=[dict(detail=detail)]),
            "Response JSON should be as expected")

    def test_get_wrong_content_type(self):
        """
        Test content-type checking for GET requests.
        """
        job = ApiJob(type='test', user=self.user)
        job.save()
        status_url = reverse('api:deploy_status', args=[job.pk])
        response = self.client.get(
            status_url,
            HTTP_AUTHORIZATION='Token {token}'.format(token=self.token),
            content_type='multipart/form-data',
        )

        self.assertNotEqual(
            response.status_code, status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            msg="Should not be strict about content types for GET requests")

    def test_post_wrong_content_type(self):
        """
        Test content-type checking for POST requests (other than token auth).
        """
        deploy_url = reverse('api:deploy', args=[self.classifier.pk])
        response = self.client.post(
            deploy_url,
            HTTP_AUTHORIZATION='Token {token}'.format(token=self.token),
            content_type='multipart/form-data',
        )

        self.assertEqual(
            response.status_code, status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Should get 415")
        detail = (
            "Content type should be application/vnd.api+json,"
            " not multipart/form-data")
        self.assertDictEqual(
            response.json(), dict(errors=[dict(detail=detail)]),
            "Response JSON should be as expected")


class ThrottleTest(BaseAPITest):
    """
    Test API throttling.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user(
            username='testuser', password='SamplePassword')
        cls.user2 = cls.create_user(
            username='testuser2', password='SamplePassword')
        cls.source = cls.create_source(cls.user)
        cls.classifier = cls.create_robot(cls.source)

    def request_token(self, username='testuser'):
        response = self.client.post(
            reverse('api:token_auth'),
            data=json.dumps(
                dict(username=username, password='SamplePassword')),
            content_type='application/vnd.api+json',
        )
        return response

    # Alter throttle rates for the following test. Use deepcopy to avoid
    # altering the original setting, since it's a nested data structure.
    throttle_test_settings = copy.deepcopy(settings.REST_FRAMEWORK)
    throttle_test_settings['DEFAULT_THROTTLE_RATES']['burst'] = '3/min'
    throttle_test_settings['DEFAULT_THROTTLE_RATES']['sustained'] = '100/hour'

    @override_settings(REST_FRAMEWORK=throttle_test_settings)
    def test_burst_throttling(self):
        """Test that we get throttled if we hit the burst rate but not the
        sustained rate."""
        for _ in range(3):
            response = self.request_token()
            self.assertStatusOK(
                response, "1st-3rd requests should be permitted")

        response = self.request_token()
        self.assertThrottleResponse(
            response, msg="4th request should be denied by throttling")

    throttle_test_settings = copy.deepcopy(settings.REST_FRAMEWORK)
    throttle_test_settings['DEFAULT_THROTTLE_RATES']['burst'] = '100/min'
    throttle_test_settings['DEFAULT_THROTTLE_RATES']['sustained'] = '3/hour'

    @override_settings(REST_FRAMEWORK=throttle_test_settings)
    def test_sustained_throttling(self):
        """Test that we get throttled if we hit the sustained rate but not the
        burst rate."""
        for _ in range(3):
            response = self.request_token()
            self.assertStatusOK(
                response, "1st-3rd requests should be permitted")

        response = self.request_token()
        self.assertThrottleResponse(
            response, msg="4th request should be denied by throttling")

    throttle_test_settings = copy.deepcopy(settings.REST_FRAMEWORK)
    throttle_test_settings['DEFAULT_THROTTLE_RATES']['burst'] = '3/min'

    @override_settings(REST_FRAMEWORK=throttle_test_settings)
    def test_throttling_tracked_per_registered_user(self):
        response = self.request_token(username='testuser')
        token = response.json()['token']

        for _ in range(3):
            response = self.client.post(
                reverse('api:deploy', args=[self.classifier.pk]),
                HTTP_AUTHORIZATION='Token {token}'.format(token=token))
            self.assertNotEqual(
                response.status_code, status.HTTP_429_TOO_MANY_REQUESTS,
                "1st-3rd testuser requests should not be throttled")

        response = self.client.post(
            reverse('api:deploy', args=[self.classifier.pk]),
            HTTP_AUTHORIZATION='Token {token}'.format(token=token))
        self.assertThrottleResponse(
            response, msg="4th testuser request should be throttled")

        response = self.request_token(username='testuser2')
        token_2 = response.json()['token']

        for _ in range(3):
            response = self.client.post(
                reverse('api:deploy', args=[self.classifier.pk]),
                HTTP_AUTHORIZATION='Token {token}'.format(token=token_2))
            self.assertNotEqual(
                response.status_code, status.HTTP_429_TOO_MANY_REQUESTS,
                "testuser2 should not be affected by testuser's requests")

    throttle_test_settings = copy.deepcopy(settings.REST_FRAMEWORK)
    throttle_test_settings['DEFAULT_THROTTLE_RATES']['burst'] = '3/min'

    @override_settings(REST_FRAMEWORK=throttle_test_settings)
    def test_throttling_tracked_per_anonymous_ip(self):
        for _ in range(3):
            response = self.request_token()
            self.assertStatusOK(
                response, "1st-3rd anon-1 requests should be permitted")

        response = self.request_token()
        self.assertThrottleResponse(
            response, msg="4th anon-1 request should be denied by throttling")

        # When anonymous users are making API requests, DRF distinguishes
        # those users by IP address for rate limiting purposes. So we simulate
        # 'another user' by changing the REMOTE_ADDR.
        kwargs = dict(
            path=reverse('api:token_auth'),
            data='{"username": "testuser", "password": "SamplePassword"}',
            content_type='application/vnd.api+json',
            REMOTE_ADDR='1.2.3.4',
        )
        for _ in range(3):
            response = self.client.post(**kwargs)
            self.assertStatusOK(
                response,
                "Different anon IP should not be affected by the"
                " first anon IP's requests")


@override_settings(JOB_MAX_DAYS=30)
class JobCleanupTest(ClientTest):
    """
    Test cleanup of old API jobs.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()

    @staticmethod
    def create_unit(api_job, order):
        internal_job = Job(
            job_name='test', arg_identifier=f'{api_job.pk}_{order}')
        internal_job.save()
        unit = ApiJobUnit(
            parent=api_job, internal_job=internal_job,
            order_in_parent=order, request_json=[],
        )
        unit.save()
        return unit

    @staticmethod
    def run_and_get_result():
        do_job('clean_up_old_api_jobs')
        job = Job.objects.filter(
            job_name='clean_up_old_api_jobs',
            status=Job.Status.SUCCESS).latest('pk')
        return job.result_message

    def test_zero_jobs_message(self):
        """
        Check the result message when there are no API jobs to clean up.
        """
        self.assertEqual(
            self.run_and_get_result(), "No old API jobs to clean up")

    def test_job_selection(self):
        """
        Only jobs eligible for cleanup should be cleaned up.
        """
        thirty_one_days_ago = timezone.now() - datetime.timedelta(days=31)

        job = ApiJob(type='new job, no units', user=self.user)
        job.save()

        job = ApiJob(type='old job, no units', user=self.user)
        job.save()
        job.create_date = thirty_one_days_ago
        job.save()

        job = ApiJob(type='new job, recent unit work', user=self.user)
        job.save()
        self.create_unit(job, 1)
        self.create_unit(job, 2)

        job = ApiJob(type='old job, recent unit work', user=self.user)
        job.save()
        job.create_date = thirty_one_days_ago
        job.save()
        self.create_unit(job, 1)
        self.create_unit(job, 2)

        job = ApiJob(
            type='old job, mixed units', user=self.user)
        job.save()
        job.create_date = thirty_one_days_ago
        job.save()
        unit_1 = self.create_unit(job, 1)
        self.create_unit(job, 2)
        # Use QuerySet.update() instead of Model.save() so that the modify
        # date doesn't get auto-updated to the current time.
        Job.objects.filter(pk=unit_1.internal_job.pk).update(
            modify_date=thirty_one_days_ago)

        job = ApiJob(
            type='old job, old units', user=self.user)
        job.save()
        job.create_date = thirty_one_days_ago
        job.save()
        unit_1 = self.create_unit(job, 1)
        unit_2 = self.create_unit(job, 2)
        Job.objects.filter(pk=unit_1.internal_job.pk).update(
            modify_date=thirty_one_days_ago)
        Job.objects.filter(pk=unit_2.internal_job.pk).update(
            modify_date=thirty_one_days_ago)

        self.assertEqual(
            self.run_and_get_result(), "Cleaned up 2 old API job(s)")

        self.assertTrue(
            ApiJob.objects.filter(type='new job, no units').exists(),
            "Shouldn't clean up new jobs with no units yet")
        self.assertFalse(
            ApiJob.objects.filter(type='old job, no units').exists(),
            "Should clean up old jobs with no units")
        self.assertTrue(
            ApiJob.objects.filter(
                type='new job, recent unit work').exists(),
            "Shouldn't clean up new jobs with units")
        self.assertTrue(
            ApiJob.objects.filter(
                type='old job, recent unit work').exists(),
            "Shouldn't clean up old jobs if units were modified recently")
        self.assertTrue(
            ApiJob.objects.filter(
                type='old job, mixed units').exists(),
            "Shouldn't clean up old jobs if some units were modified recently")
        self.assertFalse(
            ApiJob.objects.filter(
                type='old job, old units').exists(),
            "Should clean up old jobs if no units were modified recently")

    def test_unit_cleanup(self):
        """
        The cleanup task should also clean up associated job units.
        """
        thirty_one_days_ago = timezone.now() - datetime.timedelta(days=31)

        job = ApiJob(type='new', user=self.user)
        job.save()
        for n in range(1, 5+1):
            self.create_unit(job, n)

        job = ApiJob(type='old', user=self.user)
        job.save()
        job.create_date = thirty_one_days_ago
        job.save()
        for n in range(1, 5+1):
            unit = self.create_unit(job, n)
            # Use QuerySet.update() instead of Model.save() so that the modify
            # date doesn't get auto-updated to the current date.
            Job.objects.filter(pk=unit.internal_job.pk).update(
                modify_date=thirty_one_days_ago)

        self.run_and_get_result()

        self.assertTrue(
            ApiJobUnit.objects.filter(parent__type='new').exists(),
            "Shouldn't clean up the new job's units")
        self.assertFalse(
            ApiJobUnit.objects.filter(parent__type='old').exists(),
            "Should clean up the old job's units")
