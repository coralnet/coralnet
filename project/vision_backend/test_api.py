from __future__ import unicode_literals

from django.urls import reverse

from lib.tests.utils import ClientTest


class DeployTest(ClientTest):

    @classmethod
    def setUpTestData(cls):
        super(DeployTest, cls).setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user, name="Source 123")

    def test_basic(self):
        response = \
            self.client.get(reverse('api:deploy', args=[self.source.pk])).json()
        self.assertDictEqual(response, dict(data=dict(name="Source 123")))
