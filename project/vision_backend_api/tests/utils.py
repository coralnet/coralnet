from __future__ import unicode_literals
from abc import ABCMeta
import six

from django.core.cache import cache
from django.urls import reverse

from images.models import Source
from lib.tests.utils import ClientTest


@six.add_metaclass(ABCMeta)
class DeployBaseTest(ClientTest):

    longMessage = True

    def setUp(self):
        super(DeployBaseTest, self).setUp()

        # DRF implements throttling by tracking usage counts in the cache.
        # We don't want usages in one test to trigger throttling in another
        # test. So we clear the cache between tests.
        cache.clear()

    @classmethod
    def setUpTestData(cls):
        super(DeployBaseTest, cls).setUpTestData()

        # Don't want DRF throttling to be a factor during class setup, either.
        cache.clear()

        cls.user = cls.create_user(
            username='testuser', password='SamplePassword')
        cls.source = cls.create_source(
            cls.user, visibility=Source.VisibilityTypes.PUBLIC)
        cls.labels = cls.create_labels(cls.user, ['A'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, cls.labels)
        cls.classifier = cls.create_robot(cls.source)
        cls.deploy_url = reverse('api:deploy', args=[cls.classifier.pk])

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


# During tests, we use CELERY_ALWAYS_EAGER = True to run tasks synchronously,
# so that we don't have to wait for tasks to finish before checking their
# results. To test state before all tasks finish, we'll mock the task
# functions to disable or change their behavior.
#
# Note: We have to patch the run() method of the task rather than patching
# the task itself. Otherwise, the patched task may end up being
# patched / not patched in tests where it's not supposed to be.
# https://stackoverflow.com/a/29269211/
#
# Note: Yes, patching views.deploy_extract_features.run (views, not tasks) is
# correct if we want to affect usages of deploy_extract_features in the
# views module.
# https://docs.python.org/3/library/unittest.mock.html#where-to-patch


def noop_task(*args):
    pass
