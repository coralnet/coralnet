from unittest import mock

from django.test.utils import override_settings

from config.constants import SpacerJobSpec
from images.model_utils import PointGen
from jobs.tests.utils import do_job
from ..queues import get_queue_class
from .tasks.utils import BaseTaskTest
from .base_queues import QueueBasicTest, QueueClassificationTest


class LocalQueueBasicTest(QueueBasicTest):

    def test_no_jobs(self):
        self.do_test_no_jobs()

    def test_collect_feature_extraction(self):
        self.do_test_collect_feature_extraction()

    def test_collect_training(self):
        self.do_test_collect_training()

    def test_job_gets_consumed(self):
        self.do_test_job_gets_consumed()


class LocalQueueClassificationTest(QueueClassificationTest):

    def test_collect_classification(self):
        self.do_test_collect_classification()

    def test_collect_multiple_classification(self):
        self.do_test_collect_multiple_classification()


@override_settings(
    FEATURE_EXTRACT_SPEC_PIXELS=[
        (SpacerJobSpec.HIGH, 100*100),
        (SpacerJobSpec.MEDIUM, 0),
    ],
)
class JobSpecsTest(BaseTaskTest):
    """
    Test the logic for picking job spec levels when submitting
    spacer jobs.
    """

    def test_extract_features(self):
        image_less = self.upload_image(
            self.user, self.source, image_options=dict(
                width=90, height=110))
        image_equal = self.upload_image(
            self.user, self.source, image_options=dict(
                width=50, height=200))
        image_greater = self.upload_image(
            self.user, self.source, image_options=dict(
                width=110, height=100))

        with (
            mock.patch.object(get_queue_class(), 'submit_job')
            as mock_method
        ):
            do_job('extract_features', image_less.pk)
            do_job('extract_features', image_equal.pk)
            do_job('extract_features', image_greater.pk)

        self.assertEqual(
            mock_method.call_args_list[0].args[2], SpacerJobSpec.MEDIUM)
        self.assertEqual(
            mock_method.call_args_list[1].args[2], SpacerJobSpec.HIGH)
        self.assertEqual(
            mock_method.call_args_list[2].args[2], SpacerJobSpec.HIGH)

    def do_test_train_classifier(
        self, image_point_counts, threshold, expected_job_spec
    ):
        for num, image_point_count in enumerate(image_point_counts, 1):
            if num == 1:
                filename = f'val{num}.png'
            else:
                filename = f'train{num}.png'

            self.source.default_point_generation_method = \
                PointGen(type='simple', points=image_point_count).db_value
            self.source.save()
            image = self.upload_image_with_annotations(filename)

            do_job('extract_features', image.pk, source_id=self.source.pk)

        self.do_collect_spacer_jobs()

        with (
            mock.patch.object(get_queue_class(), 'submit_job')
            as mock_method,
            override_settings(TRAIN_SPEC_ANNOTATIONS=[
                (SpacerJobSpec.HIGH, threshold),
                (SpacerJobSpec.MEDIUM, 0),
            ])
        ):
            do_job('train_classifier', self.source.pk)

        self.assertIsNotNone(
            mock_method.call_args[0],
            "Should have called submit_job() (sanity check)")
        self.assertEqual(
            mock_method.call_args[0][2], expected_job_spec,
            "Should have called submit_job() with the expected job spec")

    def test_train_classifier_less(self):
        # Need at least 2 points in each of the 3 images so that it's
        # possible to have 2 different labels in each of train, ref, val.
        self.do_test_train_classifier([2,4,10], 20, SpacerJobSpec.MEDIUM)

    def test_train_classifier_equal(self):
        self.do_test_train_classifier([2,4,10], 16, SpacerJobSpec.HIGH)

    def test_train_classifier_greater(self):
        self.do_test_train_classifier([2,4,10], 10, SpacerJobSpec.HIGH)
