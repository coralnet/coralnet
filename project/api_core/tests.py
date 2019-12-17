from __future__ import unicode_literals

from django.conf import settings
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from rest_framework import status

from lib.tests.utils import ClientTest


class AuthTest(ClientTest):
    """
    Test API authentication.
    """
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
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_session_auth(self):
        # Log in like we would for non-API requests
        self.client.force_login(self.user)

        url = reverse('api:deploy', args=[self.source.pk])
        response = self.client.post(url)
        self.assertStatusOK(response)

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
        self.assertStatusOK(response)


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
        # 1st-5th requests should be permitted.
        token = None
        for _ in range(5):
            response = self.client.post(
                reverse('api:token_auth'),
                dict(username='testuser', password='SamplePassword'))
            self.assertStatusOK(response)
            token = response.json()['token']

        # 6th request should be denied by throttling.
        response = self.client.post(
            reverse('api:token_auth'),
            dict(username='testuser', password='SamplePassword'))
        self.assertEqual(
            response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

        # Throttle scopes besides 'token' should not be affected by the
        # previous requests.
        response = self.client.post(
            reverse('api:deploy', args=[self.source.pk]),
            HTTP_AUTHORIZATION='Token {token}'.format(token=token))
        self.assertStatusOK(response)

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

        # 4th request should be denied by throttling.
        response = self.client.post(
            reverse('api:deploy', args=[self.source.pk]),
            HTTP_AUTHORIZATION='Token {token}'.format(token=token))
        self.assertEqual(
            response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

        # Get a token for testuser2.
        response = self.client.post(
            reverse('api:token_auth'),
            dict(username='testuser2', password='SamplePassword'))
        token = response.json()['token']

        # testuser2 should not be affected by testuser's previous requests.
        response = self.client.post(
            reverse('api:deploy', args=[self.source.pk]),
            HTTP_AUTHORIZATION='Token {token}'.format(token=token))
        self.assertStatusOK(response)

    def test_throttling_tracked_per_anonymous_ip(self):
        # 1st-5th requests.
        for _ in range(5):
            self.client.post(
                reverse('api:token_auth'),
                dict(username='testuser', password='SamplePassword'))

        # 6th request should be denied by throttling.
        response = self.client.post(
            reverse('api:token_auth'),
            dict(username='testuser', password='SamplePassword'))
        self.assertEqual(
            response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

        # When anonymous users are making API requests, DRF distinguishes
        # those users by IP address for rate limiting purposes. So we simulate
        # 'another user' by changing the REMOTE_ADDR.
        args = [
            reverse('api:token_auth'),
            dict(username='testuser', password='SamplePassword')]
        kwargs = dict(REMOTE_ADDR='1.2.3.4')
        for _ in range(5):
            response = self.client.post(*args, **kwargs)
            self.assertStatusOK(response)
