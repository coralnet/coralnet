import mock

from django.core.cache import cache
from django.db import IntegrityError
from django.test import override_settings
from django.test.utils import patch_logger
import numpy as np
import spacer.config as spacer_config

from accounts.utils import get_robot_user, is_robot_user
from annotations.models import Annotation
from images.models import Point
from vision_backend.models import Score
from vision_backend.tasks import (
    classify_image, collect_all_jobs, submit_classifier)
from .utils import BaseTaskTest, MockImage


class BaseClassifyTest(BaseTaskTest):

    def train_classifier(self):
        # Provide enough data for training
        self.upload_images_for_training(
            train_image_count=spacer_config.MIN_TRAINIMAGES, val_image_count=1)
        # Process feature extraction results
        collect_all_jobs()

        # Train classifier
        submit_classifier(self.source.id)
        collect_all_jobs()


@mock.patch('images.models.Image.valset', MockImage.valset)
class ClassifyImageTest(BaseClassifyTest):

    def test_classify_unannotated_image(self):
        """Classify an image where all points are unannotated."""
        self.train_classifier()

        # Image without annotations
        img = self.upload_image(self.user, self.source)
        # Process feature extraction results + classify image
        collect_all_jobs()

        for point in Point.objects.filter(image__id=img.id):
            try:
                point.annotation
            except Annotation.DoesNotExist:
                self.fail("New image's points should be classified")
            self.assertTrue(
                is_robot_user(point.annotation.user),
                "Image should have robot annotations")
            # Score count per point should be label count or 5,
            # whichever is less. (In this case it's label count)
            self.assertEqual(
                2, point.score_set.count(), "Each point should have scores")

    def test_more_than_5_labels(self):
        """
        When there are more than 5 labels, score count should be capped to 5.
        """
        # Increase label count from 2 to 8.
        labels = self.create_labels(
            self.user, ['C', 'D', 'E', 'F', 'G', 'H'], "Group2")
        self.create_labelset(self.user, self.source, labels | self.labels)

        # Use each label, so that they all have enough training
        # data to be considered during classification.
        img = self.upload_image(self.user, self.source)
        self.add_annotations(
            self.user, img, {1: 'A', 2: 'B', 3: 'C', 4: 'D', 5: 'E'})
        img = self.upload_image(self.user, self.source)
        self.add_annotations(
            self.user, img, {1: 'F', 2: 'G', 3: 'H', 4: 'B', 5: 'C'})
        img = self.upload_image(self.user, self.source)
        self.add_annotations(
            self.user, img, {1: 'D', 2: 'E', 3: 'F', 4: 'G', 5: 'H'})

        # This uploads a bunch of images using nothing but A/B, then runs
        # tasks needed to train a classifier.
        self.train_classifier()

        # Upload, extract features, classify
        img = self.upload_image(self.user, self.source)
        collect_all_jobs()

        for point in Point.objects.filter(image__id=img.id):
            # Score count per point should be label count or 5,
            # whichever is less. (In this case it's 5)
            self.assertEqual(
                5, point.score_set.count(), "Each point should have 5 scores")

    def test_classify_unconfirmed_image(self):
        """
        Classify an image which has already been machine-classified
        previously.
        """
        def mock_classify_msg_1(
                self_, runtime, scores, classes, valid_rowcol):
            self_.runtime = runtime
            self_.classes = classes
            self_.valid_rowcol = valid_rowcol

            # 1 list per point; 1 float score per label per point.
            # This would classify as all A.
            scores_simple = [
                [0.8, 0.2], [0.8, 0.2], [0.8, 0.2], [0.8, 0.2], [0.8, 0.2],
            ]
            self_.scores = []
            for i, score in enumerate(scores):
                self_.scores.append((score[0], score[1], scores_simple[i]))

        def mock_classify_msg_2(
                self_, runtime, scores, classes, valid_rowcol):
            self_.runtime = runtime
            self_.classes = classes
            self_.valid_rowcol = valid_rowcol

            # This would classify as 3 A's, 2 B's.
            # We'll just check the count of each label later to check
            # correctness of results, since assigning specific scores to
            # specific points is trickier to keep track of.
            scores_simple = [
                [0.6, 0.4], [0.4, 0.6], [0.4, 0.6], [0.6, 0.4], [0.6, 0.4],
            ]
            self_.scores = []
            for i, score in enumerate(scores):
                self_.scores.append((score[0], score[1], scores_simple[i]))

        self.train_classifier()
        clf_1 = self.source.get_latest_robot()

        # Upload
        img = self.upload_image(self.user, self.source)
        # Extract features + classify with a particular set of scores
        with mock.patch(
                'spacer.messages.ClassifyReturnMsg.__init__',
                mock_classify_msg_1):
            collect_all_jobs()

        # Create another valid classifier. Override settings so that 1) we
        # don't need more images to train a new classifier, and 2) we don't
        # need improvement to mark a new classifier as valid.
        with override_settings(
                NEW_CLASSIFIER_TRAIN_TH=0.0001,
                NEW_CLASSIFIER_IMPROVEMENT_TH=0.0001):
            submit_classifier(self.source.id)
            # 1) Save classifier. 2) re-classify with a different set of
            # scores so that specific points get their labels changed (and
            # other points don't).
            with mock.patch(
                    'spacer.messages.ClassifyReturnMsg.__init__',
                    mock_classify_msg_2):
                with patch_logger('vision_backend.tasks', 'info') as tasks_log:
                    with patch_logger('vision_backend.task_helpers', 'info') as helpers_log:
                        collect_all_jobs()
                        self.fail("tasks log: {}, helpers log: {}".format(tasks_log, helpers_log))

        clf_2 = self.source.get_latest_robot()
        self.assertNotEqual(
            clf_1.id, clf_2.id, "Should have a new valid classifier")

        for point in Point.objects.filter(image=img):
            self.assertTrue(
                is_robot_user(point.annotation.user),
                "Should still have robot annotations")
        self.assertEqual(
            3,
            Point.objects.filter(
                image=img, annotation__label__name='A').count(),
            "3 points should be labeled A")
        self.assertEqual(
            2,
            Point.objects.filter(
                image=img, annotation__label__name='B').count(),
            "2 points should be labeled B")
        self.assertEqual(
            3,
            Point.objects.filter(
                image=img, annotation__robot_version=clf_1).count(),
            "3 points should still be under classifier 1")
        self.assertEqual(
            2,
            Point.objects.filter(
                image=img, annotation__robot_version=clf_2).count(),
            "2 points should have been updated by classifier 2")

    def test_classify_partially_confirmed_image(self):
        """
        Classify an image where some, but not all points have confirmed
        annotations.
        """
        self.train_classifier()

        # Image without annotations
        img = self.upload_image(self.user, self.source)
        # Add partial annotations
        self.add_annotations(self.user, img, {1: 'A'})
        # Process feature extraction results + classify image
        collect_all_jobs()

        for point in Point.objects.filter(image__id=img.id):
            if point.point_number == 1:
                self.assertFalse(
                    is_robot_user(point.annotation.user),
                    "The confirmed annotation should still be confirmed")
            else:
                self.assertTrue(
                    is_robot_user(point.annotation.user),
                    "The other annotations should be unconfirmed")
            self.assertEqual(
                2, point.score_set.count(), "Each point should have scores")

    def test_classify_confirmed_image(self):
        """Attempt to classify an image where all points are confirmed."""
        self.train_classifier()

        # Image with annotations
        img = self.upload_image_with_annotations('confirmed.png')
        # Process feature extraction results
        collect_all_jobs()
        # Try to classify
        classify_image(img.id)

        for point in Point.objects.filter(image__id=img.id):
            self.assertFalse(
                is_robot_user(point.annotation.user),
                "Image should still have confirmed annotations")
            self.assertEqual(
                2, point.score_set.count(), "Each point should have scores")

    def test_classify_scores_and_labels_match(self):
        """
        Check that the Scores and the labels assigned by classification are
        consistent with each other.
        """
        self.train_classifier()

        # Upload, extract features, classify
        img = self.upload_image(self.user, self.source)
        collect_all_jobs()

        for point in Point.objects.filter(image__id=img.id):
            ann = point.annotation
            scores = Score.objects.filter(point=point)
            posteriors = [score.score for score in scores]
            self.assertEqual(
                scores[int(np.argmax(posteriors))].label, ann.label,
                "Max score label should match the annotation label."
                " Posteriors: {}".format(posteriors))

    def test_with_dupe_points(self):
        """
        The image to be classified has two points with the same row/column.
        """
        # Provide enough data for training
        self.upload_images_for_training(
            train_image_count=spacer_config.MIN_TRAINIMAGES, val_image_count=1)
        # Add one image without annotations, including a duplicate point
        img = self.upload_image_with_dupe_points('has_dupe.png')
        # Extract features
        collect_all_jobs()

        # Train classifier + classify image
        submit_classifier(self.source.id)
        collect_all_jobs()

        self.assertEqual(
            len(self.rowcols_with_dupes_included),
            Annotation.objects.filter(image__id=img.id).count(),
            "New image should be classified, including dupe points")

    def test_legacy_features(self):
        """Classify an image which has features saved in the legacy format."""
        def mock_classify_msg(
                self_, runtime, scores, classes, valid_rowcol):
            self_.runtime = runtime
            self_.scores = [
                (0, 0, [0.2, 0.8]),
                (0, 0, [0.8, 0.2]),
                (0, 0, [0.2, 0.8]),
                (0, 0, [0.2, 0.8]),
                (0, 0, [0.8, 0.2]),
            ]
            self_.classes = classes
            self_.valid_rowcol = False

        self.train_classifier()

        # Image without annotations
        img = self.upload_image(self.user, self.source)
        # Process feature extraction results + classify image
        with mock.patch(
                'spacer.messages.ClassifyReturnMsg.__init__',
                mock_classify_msg):
            collect_all_jobs()

        for point in Point.objects.filter(image__id=img.id):
            try:
                point.annotation
            except Annotation.DoesNotExist:
                self.fail("New image's points should be classified")
            self.assertTrue(
                is_robot_user(point.annotation.user),
                "Image should have robot annotations")
            # Score count per point should be label count or 5,
            # whichever is less. (In this case it's label count)
            self.assertEqual(
                2, point.score_set.count(), "Each point should have scores")

        # Check the labels to make sure the mock was actually applied. For
        # legacy features, the scores are assumed to be in order of point pk.
        actual_labels = Point.objects.filter(image__id=img.id) \
            .order_by('pk').values_list('annotation__label__name', flat=True)
        self.assertListEqual(
            ['B', 'A', 'B', 'B', 'A'], list(actual_labels),
            "Applied labels match the given scores")


@mock.patch('images.models.Image.valset', MockImage.valset)
class AbortCasesTest(BaseClassifyTest):
    """Test cases where the task would abort before reaching the end."""

    def test_classify_nonexistent_image(self):
        """Try to classify a nonexistent image ID."""
        # To get a nonexistent image ID, upload an image, get its ID, then
        # delete the image.
        img = self.upload_image(self.user, self.source)
        image_id = img.pk
        img.delete()

        # patch_logger is an undocumented Django test utility. It lets us check
        # logged messages.
        # https://stackoverflow.com/a/54055056
        with patch_logger('vision_backend.tasks', 'info') as log_messages:
            classify_image(image_id)

            log_message = "Image {} does not exist.".format(image_id)
            self.assertIn(
                log_message, log_messages,
                "Should log the appropriate message")

    def test_classify_without_features(self):
        """Try to classify an image without features extracted."""
        self.train_classifier()

        img = self.upload_image(self.user, self.source)
        classify_image(img.pk)

        self.assertFalse(
            Annotation.objects.filter(image=img).exists(),
            "Image shouldn't have been classified")

    def test_classify_without_classifier(self):
        """Try to classify an image without a classifier for the source."""
        img = self.upload_image(self.user, self.source)
        # Extract features
        collect_all_jobs()
        # Try to classify
        classify_image(img.pk)

        self.assertFalse(
            Annotation.objects.filter(image=img).exists(),
            "Image shouldn't have been classified")

    def test_integrity_error_when_saving_annotations(self):
        """Get an IntegrityError when saving annotations."""
        self.train_classifier()
        classifier = self.source.get_latest_robot()

        img = self.upload_image(self.user, self.source)

        def mock_update_annotation(
                point, label, now_confirmed, user_or_robot_version):
            # Raise an IntegrityError on the FIRST call only. We want to get an
            # IntegrityError the first time and then do fine the second time.
            # Due to auto-retries and CELERY_ALWAYS_EAGER, if we always raised
            # the error, we'd infinite-loop.
            if not cache.get('raised_integrity_error'):
                cache.set('raised_integrity_error', True)
                raise IntegrityError

            # This is a simple saving case (for brevity) which works for this
            # particular test.
            new_annotation = Annotation(
                point=point, image=point.image,
                source=point.image.source, label=label,
                user=get_robot_user(),
                robot_version=user_or_robot_version)
            new_annotation.save()

        # Extract features + classify
        with patch_logger('vision_backend.tasks', 'info') as log_messages:
            with mock.patch(
                    'annotations.models.Annotation.objects'
                    '.update_point_annotation_if_applicable',
                    mock_update_annotation):
                collect_all_jobs()

            log_message = (
                "Failed to classify Image {} [Source: {} [{}] with "
                "classifier {}. There might have been a race condition "
                "when trying to save annotations. Will try again later."
                .format(
                    img.pk, img.source, img.source_id, classifier.pk
                )
            )
            self.assertIn(
                log_message, log_messages,
                "Should log the appropriate message")

        self.assertTrue(
            Annotation.objects.filter(image=img).exists(),
            "Image should have been classified after retry")
