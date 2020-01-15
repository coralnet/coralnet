from __future__ import unicode_literals
import copy
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from lib.tests.utils import ClientTest
from ..models import ApiJob, ApiJobUnit
from ..tasks import clean_up_old_api_jobs


class AuthTest(ClientTest):
    """
    Test API authentication.
    """
    longMessage = True

    @classmethod
    def setUpTestData(cls):
        super(AuthTest, cls).setUpTestData()

        cls.user = cls.create_user(
            username='testuser', password='SamplePassword')
        cls.source = cls.create_source(cls.user)

    def test_no_auth(self):
        # Don't log in or anything
        url = reverse('api:deploy', args=[self.source.pk])
        response = self.client.post(url)
        self.assertEqual(
            response.status_code, status.HTTP_403_FORBIDDEN,
            "Endpoints unrelated to getting API tokens should require auth")

    def test_session_auth(self):
        # Log in like we would for non-API requests
        self.client.force_login(self.user)

        url = reverse('api:deploy', args=[self.source.pk])
        response = self.client.post(url)
        self.assertNotEqual(
            response.status_code, status.HTTP_403_FORBIDDEN,
            "Session auth should work")

    def test_token_auth(self):
        # Get a token
        response = self.client.post(
            reverse('api:token_auth'),
            dict(
                username='testuser',
                password='SamplePassword',
            ),
        )
        token = response.json()['token']

        url = reverse('api:deploy', args=[self.source.pk])
        response = self.client.post(
            url, HTTP_AUTHORIZATION='Token {token}'.format(token=token))
        self.assertNotEqual(
            response.status_code, status.HTTP_403_FORBIDDEN,
            "Token auth should work")


class ThrottleTest(ClientTest):
    """
    Test API throttling.
    """
    longMessage = True

    @classmethod
    def setUpTestData(cls):
        super(ThrottleTest, cls).setUpTestData()

        cls.user = cls.create_user(
            username='testuser', password='SamplePassword')
        cls.user2 = cls.create_user(
            username='testuser2', password='SamplePassword')
        cls.source = cls.create_source(cls.user)

    def setUp(self):
        # DRF implements throttling by tracking usage counts in the cache.
        # We don't want usages in one test to trigger throttling in another
        # test. So we clear the cache between tests.
        cache.clear()

    def request_token(self, username='testuser'):
        response = self.client.post(
            reverse('api:token_auth'),
            dict(username=username, password='SamplePassword'))
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
        self.assertEqual(
            response.status_code, status.HTTP_429_TOO_MANY_REQUESTS,
            "4th request should be denied by throttling")

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
        self.assertEqual(
            response.status_code, status.HTTP_429_TOO_MANY_REQUESTS,
            "4th request should be denied by throttling")

    throttle_test_settings = copy.deepcopy(settings.REST_FRAMEWORK)
    throttle_test_settings['DEFAULT_THROTTLE_RATES']['burst'] = '3/min'

    @override_settings(REST_FRAMEWORK=throttle_test_settings)
    def test_throttling_tracked_per_registered_user(self):
        response = self.request_token(username='testuser')
        token = response.json()['token']

        for _ in range(3):
            response = self.client.post(
                reverse('api:deploy', args=[self.source.pk]),
                HTTP_AUTHORIZATION='Token {token}'.format(token=token))
            self.assertNotEqual(
                response.status_code, status.HTTP_429_TOO_MANY_REQUESTS,
                "1st-3rd testuser requests should not be throttled")

        response = self.client.post(
            reverse('api:deploy', args=[self.source.pk]),
            HTTP_AUTHORIZATION='Token {token}'.format(token=token))
        self.assertEqual(
            response.status_code, status.HTTP_429_TOO_MANY_REQUESTS,
            "4th testuser request should be throttled")

        response = self.request_token(username='testuser2')
        token_2 = response.json()['token']

        for _ in range(3):
            response = self.client.post(
                reverse('api:deploy', args=[self.source.pk]),
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
        self.assertEqual(
            response.status_code, status.HTTP_429_TOO_MANY_REQUESTS,
            "4th anon-1 request should be denied by throttling")

        # When anonymous users are making API requests, DRF distinguishes
        # those users by IP address for rate limiting purposes. So we simulate
        # 'another user' by changing the REMOTE_ADDR.
        args = [
            reverse('api:token_auth'),
            dict(username='testuser', password='SamplePassword')]
        kwargs = dict(REMOTE_ADDR='1.2.3.4')
        for _ in range(3):
            response = self.client.post(*args, **kwargs)
            self.assertStatusOK(
                response,
                "Different anon IP should not be affected by the"
                " first anon IP's requests")


class JobCleanupTest(ClientTest):
    """
    Test cleanup of old API jobs.
    """
    longMessage = True

    @classmethod
    def setUpTestData(cls):
        super(JobCleanupTest, cls).setUpTestData()

        cls.user = cls.create_user()

    def test_job_selection(self):
        """
        Only jobs eligible for cleanup should be cleaned up.
        """
        thirty_one_days_ago = timezone.now() - timedelta(days=31)

        job = ApiJob(type='new job, no units', user=self.user)
        job.save()

        job = ApiJob(type='old job, no units', user=self.user)
        job.save()
        job.create_date = thirty_one_days_ago
        job.save()

        job = ApiJob(type='new job, recent unit work', user=self.user)
        job.save()
        unit_1 = ApiJobUnit(job=job, type='', request_json=[])
        unit_1.save()
        unit_2 = ApiJobUnit(job=job, type='', request_json=[])
        unit_2.save()

        job = ApiJob(type='old job, recent unit work', user=self.user)
        job.save()
        job.create_date = thirty_one_days_ago
        job.save()
        unit_1 = ApiJobUnit(job=job, type='', request_json=[])
        unit_1.save()
        unit_2 = ApiJobUnit(job=job, type='', request_json=[])
        unit_2.save()

        job = ApiJob(
            type='old job, mixed units', user=self.user)
        job.save()
        job.create_date = thirty_one_days_ago
        job.save()
        unit_1 = ApiJobUnit(job=job, type='', request_json=[])
        unit_1.save()
        unit_2 = ApiJobUnit(job=job, type='', request_json=[])
        unit_2.save()
        # Use QuerySet.update() instead of Model.save() so that the modify
        # date doesn't get auto-updated to the current date.
        ApiJobUnit.objects.filter(pk=unit_1.pk).update(
            modify_date=thirty_one_days_ago)

        job = ApiJob(
            type='old job, old units', user=self.user)
        job.save()
        job.create_date = thirty_one_days_ago
        job.save()
        unit_1 = ApiJobUnit(job=job, type='', request_json=[])
        unit_1.save()
        unit_2 = ApiJobUnit(job=job, type='', request_json=[])
        unit_2.save()
        ApiJobUnit.objects.filter(pk=unit_1.pk).update(
            modify_date=thirty_one_days_ago)
        ApiJobUnit.objects.filter(pk=unit_2.pk).update(
            modify_date=thirty_one_days_ago)

        clean_up_old_api_jobs()

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
        thirty_one_days_ago = timezone.now() - timedelta(days=31)

        job = ApiJob(type='new', user=self.user)
        job.save()
        for _ in range(5):
            unit = ApiJobUnit(job=job, type='new_unit', request_json=[])
            unit.save()

        job = ApiJob(type='old', user=self.user)
        job.save()
        job.create_date = thirty_one_days_ago
        job.save()
        for _ in range(5):
            unit = ApiJobUnit(job=job, type='old_unit', request_json=[])
            unit.save()
            # Use QuerySet.update() instead of Model.save() so that the modify
            # date doesn't get auto-updated to the current date.
            ApiJobUnit.objects.filter(pk=unit.pk).update(
                modify_date=thirty_one_days_ago)

        clean_up_old_api_jobs()

        self.assertTrue(
            ApiJobUnit.objects.filter(type='new_unit').exists(),
            "Shouldn't clean up the new job's units")
        self.assertFalse(
            ApiJobUnit.objects.filter(type='old_unit').exists(),
            "Should clean up the old job's units")
