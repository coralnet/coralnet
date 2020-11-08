from __future__ import unicode_literals
from abc import ABCMeta
import six

from django.test import override_settings
from django.urls import reverse
from spacer.config import MIN_TRAINIMAGES

from api_core.tests.utils import BaseAPITest
from images.model_utils import PointGen
from images.models import Source
from lib.tests.utils import create_sample_image
from vision_backend.tasks import collect_all_jobs, submit_classifier

# Create and annotate sufficient nbr images.
# Since 1/8 of images go to val, we need to add a few more to
# make sure there are enough train images.
MIN_IMAGES = int(MIN_TRAINIMAGES * (1+1/8) + 1)


@override_settings(MIN_NBR_ANNOTATED_IMAGES=1)
@six.add_metaclass(ABCMeta)
class DeployBaseTest(BaseAPITest):

    @classmethod
    def setUpTestData(cls):
        super(DeployBaseTest, cls).setUpTestData()

        cls.user = cls.create_user(
            username='testuser', password='SamplePassword')
        cls.source = cls.create_source(
            cls.user,
            visibility=Source.VisibilityTypes.PUBLIC,
            point_generation_type=PointGen.Types.SIMPLE,
            simple_number_of_points=2,
        )
        cls.labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        labelset = cls.create_labelset(cls.user, cls.source, cls.labels)

        # Set a custom label code, so we can confirm whether responses
        # contain the source's custom codes or default codes.
        local_label = labelset.locallabel_set.get(code='A')
        local_label.code = 'A_mycode'
        local_label.save()

        # Add enough annotated images to train a classifier.
        for _ in range(MIN_IMAGES):
            img = cls.upload_image(cls.user, cls.source)
            # Must have at least 2 unique labels in training data in order to
            # be accepted by spacer.
            cls.add_annotations(
                cls.user, img, {1: 'A_mycode', 2: 'B'})
        # Extract features.
        collect_all_jobs()
        # Train a classifier.
        submit_classifier(cls.source.id)
        collect_all_jobs()
        cls.classifier = cls.source.get_latest_robot()

        cls.deploy_url = reverse('api:deploy', args=[cls.classifier.pk])

        # Get a token
        response = cls.client.post(
            reverse('api:token_auth'),
            data='{"username": "testuser", "password": "SamplePassword"}',
            content_type='application/vnd.api+json',
        )
        token = response.json()['token']

        # Kwargs for test client post() and get().
        cls.request_kwargs = dict(
            # Authorization header.
            HTTP_AUTHORIZATION='Token {token}'.format(token=token),
            # Content type. Particularly needed for POST requests,
            # but doesn't hurt for other requests either.
            content_type='application/vnd.api+json',
        )


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
# Note: Yes, patching views.deploy.run (views, not tasks) is
# correct if we want to affect usages of deploy in the views module.
# https://docs.python.org/3/library/unittest.mock.html#where-to-patch


def noop_task(*args):
    pass


def mocked_load_image(*args):
    """
    Return a Pillow image. This can be used to mock spacer.storage.load_image()
    to bypass image downloading from URL, for example.
    """
    return create_sample_image()
