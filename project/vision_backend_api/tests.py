from __future__ import unicode_literals

from django.conf import settings
from django.core.cache import cache
from django.test import override_settings
from django.urls import reverse
from rest_framework import status

from images.models import Source
from lib.tests.utils import ClientTest


# Alter throttle rates for this test.
throttle_test_settings = settings.REST_FRAMEWORK.copy()
throttle_test_settings['DEFAULT_THROTTLE_RATES'] = {
    'deploy': '3/hour',
    'token': '5/hour',
}
@override_settings(REST_FRAMEWORK=throttle_test_settings)
class DeployTest(ClientTest):

    @classmethod
    def setUpTestData(cls):
        super(DeployTest, cls).setUpTestData()

        cls.user = cls.create_user(
            username='testuser', password='SamplePassword')

        # Get a token
        response = cls.client.post(
            reverse('api:token_auth'),
            dict(
                username='testuser',
                password='SamplePassword',
            ),
        )
        token = response.json()['token']
        cls.token_headers = dict(
            HTTP_AUTHORIZATION='Token {token}'.format(token=token))

    def setUp(self):
        # DRF implements throttling by tracking usage counts in the cache.
        # We don't want usages in one test to trigger throttling in another
        # test. So we clear the cache between tests.
        cache.clear()

    def test_nonexistent_source(self):
        # To ensure we have an ID which corresponds to no source, we'll
        # create a source, get its ID, and then delete it.
        source = self.create_source(self.user)
        url = reverse('api:deploy', args=[source.pk])
        source.delete()

        response = self.client.post(url, **self.token_headers)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_private_source(self):
        source = self.create_source(
            self.user, visibility=Source.VisibilityTypes.PRIVATE)
        url = reverse('api:deploy', args=[source.pk])

        response = self.client.post(url, **self.token_headers)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_success(self):
        source = self.create_source(
            self.user, visibility=Source.VisibilityTypes.PUBLIC,
            name="Source 123")
        url = reverse('api:deploy', args=[source.pk])

        response = self.client.post(url, **self.token_headers)
        self.assertStatusOK(response)
        self.assertDictEqual(
            response.json(), dict(data=dict(name="Source 123")))

    def test_throttling(self):
        source = self.create_source(self.user)
        url = reverse('api:deploy', args=[source.pk])

        # 1st-3rd requests should be permitted.
        for _ in range(3):
            response = self.client.post(url, **self.token_headers)
            self.assertStatusOK(response)

        # 4th request should be denied by throttling.
        response = self.client.post(url, **self.token_headers)
        self.assertEqual(
            response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
