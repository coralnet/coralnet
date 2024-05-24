from abc import ABCMeta
from io import BytesIO
import math
from unittest import mock

from django.conf import settings
from django.test import override_settings
from django.urls import reverse
from rest_framework import status

from api_core.tests.utils import BaseAPITest
from jobs.tasks import run_scheduled_jobs_until_empty
from lib.tests.utils import create_sample_image
from sources.models import Source
from vision_backend.tests.tasks.utils import do_collect_spacer_jobs


@override_settings(ENABLE_PERIODIC_JOBS=False)
class DeployBaseTest(BaseAPITest, metaclass=ABCMeta):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user(
            username='testuser', password='SamplePassword')
        cls.source = cls.create_source(
            cls.user,
            visibility=Source.VisibilityTypes.PUBLIC,
            default_point_generation_method=dict(type='simple', points=2),
        )

        label_names = ['A', 'B']
        labels = cls.create_labels(cls.user, label_names, 'GroupA')
        labelset = cls.create_labelset(cls.user, cls.source, labels)
        cls.labels_by_name = dict(
            zip(label_names, labelset.get_globals_ordered_by_name()))

        # Set custom label codes, so we can confirm we're returning the
        # source's custom codes, not the default codes.
        for label_name in label_names:
            local_label = labelset.locallabel_set.get(
                global_label__name=label_name)
            # A_mycode, B_mycode, etc.
            local_label.code = label_name + '_mycode'
            local_label.save()

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

    def assert_expected_400_error(self, response, error_dict):
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST,
            "Should get 400")
        self.assertDictEqual(
            response.json(),
            dict(errors=[error_dict]),
            "Response JSON should be as expected")

    @classmethod
    def train_classifier(cls):
        """
        This convenience function is almost always useful for deploy-related
        tests, but we don't call it in this class's setUpTestData().

        The reason is that sometimes we want to apply subclass-specific
        mocks to the extraction and/or training, and this only appears to
        be possible if this method is called from that subclass's
        definition, not this class's definition.
        """
        # Add enough annotated images to train a classifier.
        #
        # Must have at least 2 unique labels in training data in order to
        # be accepted by spacer.
        annotations = {1: 'A_mycode', 2: 'B_mycode'}
        num_validation_images = math.ceil(settings.TRAINING_MIN_IMAGES / 8)
        for i in range(settings.TRAINING_MIN_IMAGES):
            img = cls.upload_image(
                cls.user, cls.source, dict(filename=f'train{i}.png'))
            cls.add_annotations(cls.user, img, annotations)
        for i in range(num_validation_images):
            # Unit tests use the image filename to designate what goes into
            # the validation set.
            img = cls.upload_image(
                cls.user, cls.source, dict(filename=f'val{i}.png'))
            cls.add_annotations(cls.user, img, annotations)

        # Extract features.
        run_scheduled_jobs_until_empty()
        do_collect_spacer_jobs()
        # Train a classifier.
        run_scheduled_jobs_until_empty()
        do_collect_spacer_jobs()
        cls.classifier = cls.source.last_accepted_classifier

        cls.deploy_url = reverse('api:deploy', args=[cls.classifier.pk])

    @staticmethod
    def run_scheduled_jobs_including_deploy():
        """
        When running scheduled jobs which include deploy jobs, call this
        method instead of run_scheduled_jobs_until_empty(), so that the
        test doesn't have to download from any URLs.

        Note that mock.patch() doesn't seem to reliably carry over with
        test-subclassing, so this seems to be the better way to 'DRY' a
        mock.patch().
        """
        with mock.patch(
            'spacer.storage.URLStorage.load', mock_url_storage_load
        ):
            run_scheduled_jobs_until_empty()


def mock_url_storage_load(*args) -> BytesIO:
    """
    Returns a Pillow image as a stream. This can be used to mock
    spacer.storage.URLStorage.load()
    to bypass image-downloading from URL.
    """
    im = create_sample_image()
    # Save the PIL image to an IO stream
    stream = BytesIO()
    im.save(stream, 'PNG')
    # Return the (not yet closed) IO stream
    return stream
