from __future__ import unicode_literals

from django.urls import reverse

from lib.tests.utils import ClientTest


class DeployTest(ClientTest):

    @classmethod
    def setUpTestData(cls):
        super(DeployTest, cls).setUpTestData()

        cls.user = cls.create_user(
            username='testuser', password='SamplePassword')
        cls.source = cls.create_source(cls.user, name="Source 123")

    def test_session_auth(self):
        self.client.force_login(self.user)

        url = reverse('api:deploy', args=[self.source.pk])
        response = self.client.post(url)
        self.assertStatusOK(response)
        self.assertDictEqual(
            response.json(), dict(data=dict(name="Source 123")))

    def test_token_auth(self):
        # Get a token
        response = self.client.post(
            reverse('api_token_auth'),
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
        self.assertDictEqual(
            response.json(), dict(data=dict(name="Source 123")))
