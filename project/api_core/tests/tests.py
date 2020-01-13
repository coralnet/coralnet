from __future__ import unicode_literals
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


# Alter throttle rates for this test.
throttle_test_settings = settings.REST_FRAMEWORK.copy()
throttle_test_settings['DEFAULT_THROTTLE_RATES'] = {
    'deploy': '3/hour',
    'token': '5/hour',
}
@override_settings(REST_FRAMEWORK=throttle_test_settings)
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

    def test_token_view_throttling(self):
        token = None
        for _ in range(5):
            response = self.client.post(
                reverse('api:token_auth'),
                dict(username='testuser', password='SamplePassword'))
            self.assertStatusOK(
                response, "1st-5th requests should be permitted")
            token = response.json()['token']

        # .
        response = self.client.post(
            reverse('api:token_auth'),
            dict(username='testuser', password='SamplePassword'))
        self.assertEqual(
            response.status_code, status.HTTP_429_TOO_MANY_REQUESTS,
            "6th request should be denied by throttling")

        response = self.client.post(
            reverse('api:deploy', args=[self.source.pk]),
            HTTP_AUTHORIZATION='Token {token}'.format(token=token))
        # This response might not be OK, if there's some requirement missing
        # for deploy, but at least it shouldn't be throttled.
        self.assertNotEqual(
            response.status_code, status.HTTP_429_TOO_MANY_REQUESTS,
            "Throttle scopes besides 'token' should not be affected"
            " by the previous requests")

    def test_throttling_tracked_per_registered_user(self):
        # Get a token for testuser.
        response = self.client.post(
            reverse('api:token_auth'),
            dict(username='testuser', password='SamplePassword'))
        token = response.json()['token']

        # 1st-3rd requests.
        for _ in range(3):
            self.client.post(
                reverse('api:deploy', args=[self.source.pk]),
                HTTP_AUTHORIZATION='Token {token}'.format(token=token))

        response = self.client.post(
            reverse('api:deploy', args=[self.source.pk]),
            HTTP_AUTHORIZATION='Token {token}'.format(token=token))
        self.assertEqual(
            response.status_code, status.HTTP_429_TOO_MANY_REQUESTS,
            "4th request should be denied by throttling")

        # Get a token for testuser2.
        response = self.client.post(
            reverse('api:token_auth'),
            dict(username='testuser2', password='SamplePassword'))
        token = response.json()['token']

        response = self.client.post(
            reverse('api:deploy', args=[self.source.pk]),
            HTTP_AUTHORIZATION='Token {token}'.format(token=token))
        self.assertNotEqual(
            response.status_code, status.HTTP_429_TOO_MANY_REQUESTS,
            "testuser2 should not be affected by testuser's"
            " previous requests")

    def test_throttling_tracked_per_anonymous_ip(self):
        # 1st-5th requests.
        for _ in range(5):
            self.client.post(
                reverse('api:token_auth'),
                dict(username='testuser', password='SamplePassword'))

        response = self.client.post(
            reverse('api:token_auth'),
            dict(username='testuser', password='SamplePassword'))
        self.assertEqual(
            response.status_code, status.HTTP_429_TOO_MANY_REQUESTS,
            "6th request should be denied by throttling")

        # When anonymous users are making API requests, DRF distinguishes
        # those users by IP address for rate limiting purposes. So we simulate
        # 'another user' by changing the REMOTE_ADDR.
        args = [
            reverse('api:token_auth'),
            dict(username='testuser', password='SamplePassword')]
        kwargs = dict(REMOTE_ADDR='1.2.3.4')
        for _ in range(5):
            response = self.client.post(*args, **kwargs)
            self.assertStatusOK(
                response,
                "Different anonymous IP should not be affected by the"
                " first anonymous IP's requests")


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
        Only jobs that were last modified over 30 days ago should be
        cleaned up by the task.
        """
        thirty_one_days_ago = timezone.now() - timedelta(days=31)

        job = ApiJob(type='new', user=self.user)
        job.save()

        job = ApiJob(type='create date old', user=self.user)
        job.save()
        job.create_date = thirty_one_days_ago
        job.save()

        job = ApiJob(type='create and modify dates old', user=self.user)
        job.save()
        job.create_date = thirty_one_days_ago
        job.save()
        # Use QuerySet.update() instead of Model.save() so that the modify
        # date doesn't get auto-updated to the current date.
        ApiJob.objects.filter(pk=job.pk).update(
            modify_date=thirty_one_days_ago)

        clean_up_old_api_jobs()

        self.assertTrue(
            ApiJob.objects.filter(type='new').exists(),
            "Shouldn't clean up new jobs")
        self.assertTrue(
            ApiJob.objects.filter(type='create date old').exists(),
            "Shouldn't clean up jobs that were created a while ago,"
            " but modified recently")
        self.assertFalse(
            ApiJob.objects.filter(type='create and modify dates old').exists(),
            "Should clean up jobs that were last modified a while ago")

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
        # Use QuerySet.update() instead of Model.save() so that the modify
        # date doesn't get auto-updated to the current date.
        ApiJob.objects.filter(pk=job.pk).update(
            modify_date=thirty_one_days_ago)
        for _ in range(5):
            unit = ApiJobUnit(job=job, type='old_unit', request_json=[])
            unit.save()

        clean_up_old_api_jobs()

        self.assertTrue(
            ApiJobUnit.objects.filter(type='new_unit').exists(),
            "Shouldn't clean up the new job's units")
        self.assertFalse(
            ApiJobUnit.objects.filter(type='old_unit').exists(),
            "Should clean up the old job's units")
