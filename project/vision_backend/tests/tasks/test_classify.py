import re
from unittest import mock

from django.core.cache import cache
from django.db.utils import IntegrityError
from django.test import override_settings
import numpy as np

from accounts.utils import get_robot_user, is_robot_user
from annotations.models import Annotation
from annotations.tests.utils import AnnotationHistoryTestMixin
from events.models import ClassifyImageEvent
from images.models import Point
from jobs.models import Job
from jobs.tasks import run_scheduled_jobs, run_scheduled_jobs_until_empty
from jobs.tests.utils import (
    do_job, JobUtilsMixin, queue_and_run_job, queue_job)
from ...exceptions import RowColumnMismatchError
from ...models import Score
from ...utils import clear_features
from .utils import BaseTaskTest, queue_and_run_collect_spacer_jobs


def noop(*args, **kwargs):
    pass


def classify(image, create_event=True):
    if create_event:
        queue_and_run_job('classify_features', image.pk)
    else:
        with mock.patch.object(ClassifyImageEvent, 'save', noop):
            queue_and_run_job('classify_features', image.pk)


class SourceCheckTest(BaseTaskTest, JobUtilsMixin):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.upload_data_and_train_classifier()

    def test_basic(self):
        self.upload_image_for_classification()
        self.upload_image_for_classification()
        self.source_check_and_assert_message(
            "Queued 2 image classification(s)")
        self.source_check_and_assert_message(
            "Waiting for image classification(s) to finish")

    def test_do_not_requeue(self):
        img1 = self.upload_image_for_classification()
        img2 = self.upload_image_for_classification()
        self.source_check_and_assert_message(
            "Queued 2 image classification(s)")

        self.upload_image_for_classification()

        img1.refresh_from_db()
        img2.refresh_from_db()
        img1.annoinfo.refresh_from_db()
        img2.annoinfo.refresh_from_db()
        self.assertFalse(
            any([img1.annoinfo.classified, img2.annoinfo.classified]),
            msg="First 2 classifications shouldn't have run yet (sanity check)",
        )

        self.source_check_and_assert_message(
            "Queued 1 image classification(s)",
            assert_msg="Should not re-queue the original 2 classifications",
        )

    def check_is_pending(self):
        return Job.objects.filter(
            job_name='check_source',
            arg_identifier=self.source.pk,
            status=Job.Status.PENDING,
        ).exists()

    def test_queue_check_after_last_classification(self):
        """
        After the current classifier seems to have gone over all
        classifiable images, another source-check should be queued
        to confirm whether the source is all caught up. That's useful
        to know when looking at job/backend dashboards.
        """
        image_1 = self.upload_image_for_classification()
        image_2 = self.upload_image_for_classification()
        self.source_check_and_assert_message(
            "Queued 2 image classification(s)")

        do_job('classify_features', image_1.pk, source_id=self.source.pk)
        self.assertFalse(
            self.check_is_pending(),
            msg="Should not queue a check after classifying just 1 image",
        )
        do_job('classify_features', image_2.pk, source_id=self.source.pk)
        self.assertTrue(
            self.check_is_pending(),
            msg="Should queue a check after classifying both images",
        )

        # Accept another classifier.
        with override_settings(
            NEW_CLASSIFIER_TRAIN_TH=0.0001,
            NEW_CLASSIFIER_IMPROVEMENT_TH=0.0001,
        ):
            self.upload_data_and_train_classifier(new_train_images_count=0)

        # Ensure there's no pending source check.
        do_job('check_source', self.source.pk, source_id=self.source.pk)

        do_job('classify_features', image_1.pk, source_id=self.source.pk)
        self.assertFalse(
            self.check_is_pending(),
            msg="Should not queue a check after classifying just 1 image,"
                " even if the other image was handled by the previous"
                " classifier",
        )
        do_job('classify_features', image_2.pk, source_id=self.source.pk)
        self.assertTrue(
            self.check_is_pending(),
            msg="Should queue a check after classifying both images",
        )

    def test_various_image_cases_new_classifier_on_events_and_annotations(self):
        self.do_test_various_image_cases(True, True)

    def test_various_image_cases_new_classifier_on_events_only(self):
        self.do_test_various_image_cases(True, False)

    def test_various_image_cases_new_classifier_on_annotations_only(self):
        self.do_test_various_image_cases(False, True)

    def test_various_image_cases_new_classifier_on_nothing(self):
        self.do_test_various_image_cases(False, False)

    def do_test_various_image_cases(
        self,
        # Whether Events are created upon classifying images; otherwise,
        # annotations have the only record of which classifier last visited.
        # False will simulate images processed before CoralNet 1.7,
        # which is when the Events were introduced.
        create_events: bool,
        # Whether the new classifier changes annotations from the old
        # classifier, thus allowing the new classifier to have attribution in
        # the annotations.
        new_classifier_on_annotations: bool,
    ):

        def mock_classify_msg_all_a(
                self_, runtime, scores, classes, valid_rowcol):
            """Classify any point as A."""
            self_.runtime = runtime
            self_.scores = [
                (row, column, [0.8, 0.2])
                for row, column, _ in scores
            ]
            self_.classes = classes
            self_.valid_rowcol = valid_rowcol
        def mock_classify_msg_all_b(
                self_, runtime, scores, classes, valid_rowcol):
            """Classify any point as B."""
            self_.runtime = runtime
            self_.scores = [
                (row, column, [0.2, 0.8])
                for row, column, _ in scores
            ]
            self_.classes = classes
            self_.valid_rowcol = valid_rowcol

        if new_classifier_on_annotations:
            # Have old and new classifiers make (at least some)
            # different classifications.
            old_classifier_msg_mock = mock_classify_msg_all_a
            new_classifier_msg_mock = mock_classify_msg_all_b
        else:
            # Have old and new classifiers make the same classifications.
            old_classifier_msg_mock = mock_classify_msg_all_a
            new_classifier_msg_mock = mock_classify_msg_all_a

        # This will be classified by the old, then the new classifier.
        img1 = self.upload_image_for_classification()
        # This will be classified by the old classifier.
        img2 = self.upload_image_for_classification()
        # This will be unclassified.
        img3 = self.upload_image_for_classification()

        with mock.patch(
            'spacer.messages.ClassifyReturnMsg.__init__',
            old_classifier_msg_mock,
        ):
            classify(img1, create_event=create_events)
            classify(img2, create_event=create_events)

        # Accept another classifier. Override settings so that 1) we
        # don't need more images to train a new classifier, and 2) we don't
        # need improvement to mark a new classifier as accepted.
        with override_settings(
            NEW_CLASSIFIER_TRAIN_TH=0.0001,
            NEW_CLASSIFIER_IMPROVEMENT_TH=0.0001,
        ):
            self.upload_data_and_train_classifier(new_train_images_count=0)

        with mock.patch(
            'spacer.messages.ClassifyReturnMsg.__init__',
            new_classifier_msg_mock,
        ):
            classify(img1, create_event=create_events)

        if create_events:
            self.assertTrue(
                ClassifyImageEvent.objects.filter(image_id=img1.pk).exists(),
                "img1 classification event should exist (sanity check)")
            self.assertTrue(
                ClassifyImageEvent.objects.filter(image_id=img2.pk).exists(),
                "img2 classification event should exist (sanity check)")
        else:
            self.assertFalse(
                ClassifyImageEvent.objects.filter(
                    image_id__in=[img1.pk, img2.pk]).exists(),
                "img1 and img2 classification events shouldn't exist"
                " (sanity check)")

        # Don't really need to check how many images are queued here, because
        # we'll check specifically which ones were queued after this.
        self.source_check_and_assert_message(
            re.compile(r"Queued \d+ image classification\(s\)"),
        )

        queued_image_ids = Job.objects \
            .filter(job_name='classify_features', status=Job.Status.PENDING) \
            .values_list('arg_identifier', flat=True)
        queued_image_ids = [int(pk) for pk in queued_image_ids]

        self.assertIn(
            img3.pk, queued_image_ids,
            msg="Unclassified image should have been queued")

        if not create_events and not new_classifier_on_annotations:
            # If there's no sign of activity from the new classifier,
            # then all unconfirmed images are queued for classification.
            self.assertIn(
                img2.pk, queued_image_ids,
                msg="Image that was last classified by the previous classifier"
                    " should have been queued")
            self.assertIn(
                img1.pk, queued_image_ids,
                msg="Image that was last classified by the current classifier"
                    " should have been queued")
        else:
            self.assertNotIn(
                img2.pk, queued_image_ids,
                msg="Image that was last classified by the previous classifier"
                    " should not have been queued")
            self.assertNotIn(
                img1.pk, queued_image_ids,
                msg="Image that was last classified by the current classifier"
                    " should not have been queued")

    def test_time_out(self):
        for _ in range(12):
            self.upload_image_for_classification()

        with override_settings(JOB_MAX_MINUTES=-1):
            self.source_check_and_assert_message(
                "Queued 10 image classification(s) (timed out)")

        self.source_check_and_assert_message(
            "Queued 2 image classification(s)")


class ClassifyImageTest(
        BaseTaskTest, JobUtilsMixin, AnnotationHistoryTestMixin):

    @staticmethod
    def image_label_ids(image):
        label_ids = []
        for point in image.point_set.order_by('point_number'):
            label_ids.append(point.annotation.label_id)
        return label_ids

    @staticmethod
    def image_label_codes(image):
        label_codes = []
        for point in image.point_set.order_by('point_number'):
            label_codes.append(point.annotation.label_code)
        return label_codes

    def test_classify_unannotated_image(self):
        """Classify an image where all points are unannotated."""
        self.upload_data_and_train_classifier()

        img = self.upload_image_and_machine_classify()

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

        codes = self.image_label_codes(img)
        label_ids = self.image_label_ids(img)
        classifier = self.source.get_current_classifier()

        event = ClassifyImageEvent.objects.get(image_id=img.pk)
        self.assertEqual(event.source_id, self.source.pk)
        self.assertEqual(event.classifier_id, classifier.pk)
        self.assertDictEqual(
            event.details,
            {
                '1': dict(label=label_ids[0], result='added'),
                '2': dict(label=label_ids[1], result='added'),
                '3': dict(label=label_ids[2], result='added'),
                '4': dict(label=label_ids[3], result='added'),
                '5': dict(label=label_ids[4], result='added'),
            },
        )

        response = self.view_history(self.user, img=img)
        self.assert_history_table_equals(
            response,
            [
                [f'Point 1: {codes[0]}<br/>Point 2: {codes[1]}'
                 f'<br/>Point 3: {codes[2]}<br/>Point 4: {codes[3]}'
                 f'<br/>Point 5: {codes[4]}',
                 f'Robot {classifier.pk}'],
            ]
        )

    def test_score_count_cap(self):
        """
        Score count should be capped by the number of labels or the
        setting for number of scores, whichever is lower.
        """
        # Increase label count from 2 to 5.
        labels = self.create_labels(
            self.user, ['C', 'D', 'E'], "Group2")
        self.create_labelset(self.user, self.source, labels | self.labels)

        def mock_classify_return_msg(
                self_, runtime, scores, classes, valid_rowcol):
            self_.runtime = runtime
            self_.classes = [
                (labels | self.labels).get(name=name).pk
                for name in ['A', 'B', 'C', 'D', 'E']
            ]
            self_.valid_rowcol = valid_rowcol

            # 1 list per point; 1 float score per label per point.
            scores_simple = [
                [0.5, 0.2, 0.15, 0.1, 0.05],
                [0.5, 0.2, 0.15, 0.1, 0.05],
                [0.5, 0.2, 0.15, 0.1, 0.05],
                [0.5, 0.2, 0.15, 0.1, 0.05],
                [0.5, 0.2, 0.15, 0.1, 0.05],
            ]
            self_.scores = []
            for i, (row, column, _) in enumerate(scores):
                self_.scores.append((row, column, scores_simple[i]))

        self.upload_data_and_train_classifier()

        with mock.patch(
            'spacer.messages.ClassifyReturnMsg.__init__', mock_classify_return_msg
        ):

            with override_settings(NBR_SCORES_PER_ANNOTATION=4):
                img = self.upload_image_and_machine_classify()
            for point in Point.objects.filter(image__id=img.id):
                self.assertEqual(
                    point.score_set.count(), 4,
                    "Each point should have 4 scores"
                    " (limited by setting)")

            with override_settings(NBR_SCORES_PER_ANNOTATION=6):
                img = self.upload_image_and_machine_classify()
            for point in Point.objects.filter(image__id=img.id):
                self.assertEqual(
                    point.score_set.count(), 5,
                    "Each point should have 5 scores"
                    " (limited by label count)")

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

        self.upload_data_and_train_classifier()
        clf_1 = self.source.get_current_classifier()

        # Upload, extract, and classify with a particular set of scores
        with mock.patch(
            'spacer.messages.ClassifyReturnMsg.__init__', mock_classify_msg_1
        ):
            img = self.upload_image_and_machine_classify()

        # Accept another classifier.
        with override_settings(
            NEW_CLASSIFIER_TRAIN_TH=0.0001,
            NEW_CLASSIFIER_IMPROVEMENT_TH=0.0001,
        ):
            self.upload_data_and_train_classifier(new_train_images_count=0)

        # Re-classify with a different set of
        # scores so that specific points get their labels changed (and
        # other points don't).
        with mock.patch(
            'spacer.messages.ClassifyReturnMsg.__init__', mock_classify_msg_2
        ):
            run_scheduled_jobs_until_empty()

        clf_2 = self.source.get_current_classifier()
        all_classifiers = self.source.classifier_set.all()
        message = (
            f"clf 1 and 2 IDs: {clf_1.pk}, {clf_2.pk}"
            + " | All classifier IDs: {}".format(
                list(all_classifiers.values_list('pk', flat=True)))
            + "".join([
                f" | pk {clf.pk} details: status={clf.status},"
                f" accuracy={clf.accuracy}, images={clf.nbr_train_images}"
                for clf in all_classifiers])
        )
        self.assertNotEqual(
            clf_1.pk, clf_2.pk,
            f"Should have a new accepted classifier. Debug info: {message}")

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

        label_ids = self.image_label_ids(img)
        event = ClassifyImageEvent.objects.latest('pk')
        self.assertDictEqual(
            event.details,
            {
                '1': dict(label=label_ids[0], result='no change'),
                '2': dict(label=label_ids[1], result='updated'),
                '3': dict(label=label_ids[2], result='updated'),
                '4': dict(label=label_ids[3], result='no change'),
                '5': dict(label=label_ids[4], result='no change'),
            },
        )

        response = self.view_history(self.user, img=img)
        self.assert_history_table_equals(
            response,
            [
                [f'Point 2: B<br/>Point 3: B',
                 f'Robot {clf_2.pk}'],
                [f'Point 1: A<br/>Point 2: A'
                 f'<br/>Point 3: A<br/>Point 4: A'
                 f'<br/>Point 5: A',
                 f'Robot {clf_1.pk}'],
            ]
        )

    def test_classify_partially_confirmed_image(self):
        """
        Classify an image where some, but not all points have confirmed
        annotations.
        """
        self.upload_data_and_train_classifier()

        # Image without annotations
        img = self.upload_image(self.user, self.source)
        # Add partial annotations
        self.add_annotations(self.user, img, {1: 'A'})
        # Extract features
        run_scheduled_jobs_until_empty()
        queue_and_run_collect_spacer_jobs()
        # Classify
        run_scheduled_jobs_until_empty()

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

        label_ids = self.image_label_ids(img)
        event = ClassifyImageEvent.objects.latest('pk')
        self.assertDictEqual(
            event.details,
            {
                '1': dict(label=label_ids[0], result='no change'),
                '2': dict(label=label_ids[1], result='added'),
                '3': dict(label=label_ids[2], result='added'),
                '4': dict(label=label_ids[3], result='added'),
                '5': dict(label=label_ids[4], result='added'),
            },
        )

    def test_classify_confirmed_image(self):
        """Attempt to classify an image where all points are confirmed."""
        self.upload_data_and_train_classifier()

        # Image with annotations
        img = self.upload_image_with_annotations('confirmed.png')
        # Extract features
        run_scheduled_jobs_until_empty()
        queue_and_run_collect_spacer_jobs()
        # Attempt to classify
        run_scheduled_jobs_until_empty()

        for point in Point.objects.filter(image__id=img.id):
            self.assertFalse(
                is_robot_user(point.annotation.user),
                "Image should still have confirmed annotations")
            self.assertFalse(
                point.score_set.exists(), "Points should not have scores")

        # There should be no classify event
        with self.assertRaises(ClassifyImageEvent.DoesNotExist):
            ClassifyImageEvent.objects.latest('pk')

    def test_classify_scores_and_labels_match(self):
        """
        Check that the Scores and the labels assigned by classification are
        consistent with each other.
        """
        self.upload_data_and_train_classifier()

        img = self.upload_image_and_machine_classify()

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
        self.upload_images_for_training()
        # Add one image without annotations, including a duplicate point
        img = self.upload_image_with_dupe_points('has_dupe.png')
        # Extract features
        run_scheduled_jobs_until_empty()
        queue_and_run_collect_spacer_jobs()
        # Train
        run_scheduled_jobs_until_empty()
        queue_and_run_collect_spacer_jobs()
        # Classify
        run_scheduled_jobs_until_empty()

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

        self.upload_data_and_train_classifier()

        # Upload, extract, and classify
        with mock.patch(
            'spacer.messages.ClassifyReturnMsg.__init__', mock_classify_msg
        ):
            img = self.upload_image_and_machine_classify()

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


class AbortCasesTest(BaseTaskTest, JobUtilsMixin):
    """Test cases where the task would abort before reaching the end."""

    def upload_image_and_queue_classification(self):
        # Upload and extract features
        img = self.upload_image_for_classification()
        queue_job('classify_features', img.pk, source_id=self.source.pk)
        return img

    def test_classify_nonexistent_image(self):
        """Try to classify a nonexistent image ID."""
        self.upload_data_and_train_classifier()

        img = self.upload_image_and_queue_classification()
        # Delete img
        image_id = img.pk
        img.delete()

        # Try to classify
        run_scheduled_jobs()

        classify_job = Job.objects.get(job_name='classify_features')
        self.assertEqual(
            f"Image {image_id} does not exist.",
            classify_job.result_message,
            "Job should have the expected error")

    def test_classify_without_features(self):
        """Try to classify an image without features extracted."""
        self.upload_data_and_train_classifier()

        img = self.upload_image_and_queue_classification()
        # Clear features
        clear_features(img)

        # Try to classify
        run_scheduled_jobs()

        classify_job = Job.objects.get(job_name='classify_features')
        self.assertEqual(
            f"Image {img.pk} needs to have features extracted"
            f" before being classified.",
            classify_job.result_message,
            "Job should have the expected error")

    def test_classify_without_classifier(self):
        """Try to classify an image without a classifier for the source."""
        self.upload_data_and_train_classifier()

        img = self.upload_image_and_queue_classification()
        # Delete source's classifier
        self.source.get_current_classifier().delete()

        # Try to classify
        run_scheduled_jobs()

        classify_job = Job.objects.get(job_name='classify_features')
        self.assertEqual(
            f"Image {img.pk} can't be classified;"
            f" its source doesn't have a classifier.",
            classify_job.result_message,
            "Job should have the expected error")

    def test_integrity_error_when_saving_annotations(self):

        class UnexpectedPointOrderError(Exception):
            pass

        def mock_update_annotation(
                point, label, now_confirmed, user_or_robot_version):
            """
            When the save_annotations_ajax view tries to actually save the
            annotations to the DB, this patched function should save the
            annotation for point 1, then raise an IntegrityError for point 2.
            This should make the view return an appropriate
            error message, and should make point 1 get rolled back.
            """
            # This is a simple saving case (for brevity) which works for this
            # particular test.
            new_annotation = Annotation(
                point=point, image=point.image,
                source=point.image.source, label=label,
                user=get_robot_user(),
                robot_version=user_or_robot_version)
            new_annotation.save()

            if point.point_number == 1:
                cache.set('point_1_processed', True)
            if point.point_number == 2:
                if not cache.get('point_1_processed'):
                    # The point order, which the test depends on, isn't as
                    # expected. Raise a non-IntegrityError to fail the test.
                    raise UnexpectedPointOrderError
                # Save another Annotation for this Point, simulating a
                # race condition of some kind.
                # Should get an IntegrityError.
                new_annotation.pk = None
                new_annotation.save()

        self.upload_data_and_train_classifier()

        img = self.upload_image_and_queue_classification()

        # Try to classify
        with mock.patch(
            'annotations.models.Annotation.objects'
            '.update_point_annotation_if_applicable',
            mock_update_annotation
        ):
            do_job('classify_features', img.pk)

        classify_job = Job.objects.get(job_name='classify_features')
        self.assertEqual(
            f"Failed to save annotations for image {img.pk}."
            f" Maybe there was another change happening at the same time"
            f" with the image's points/annotations.",
            classify_job.result_message,
            "Job should have the expected error")

        # Although the error occurred on point 2, nothing should have been
        # saved, including point 1.
        self.assertEqual(
            img.annotation_set.count(), 0,
            "Point 1's annotation should have been rolled back"
        )

    def test_row_col_mismatch_when_saving_annotations(self):

        def mock_add_annotations(*args, **kwargs):
            raise RowColumnMismatchError

        self.upload_data_and_train_classifier()

        img = self.upload_image_and_queue_classification()

        # Try to classify
        with mock.patch(
            'vision_backend.task_helpers.add_annotations',
            mock_add_annotations
        ):
            do_job('classify_features', img.pk)

        classify_job = Job.objects.get(job_name='classify_features')
        self.assertEqual(
            f"Failed to save annotations for image {img.pk}."
            f" Maybe there was another change happening at the same time"
            f" with the image's points/annotations.",
            classify_job.result_message,
            "Job should have the expected error")

    def test_integrity_error_when_saving_scores(self):

        def mock_add_scores(*args, **kwargs):
            """
            We're lazier than the save-annotations test here: just directly
            raise an IntegrityError.
            """
            raise IntegrityError

        self.upload_data_and_train_classifier()

        img = self.upload_image_and_queue_classification()

        # Try to classify
        with mock.patch(
            'vision_backend.task_helpers.add_scores',
            mock_add_scores
        ):
            do_job('classify_features', img.pk)

        classify_job = Job.objects.get(job_name='classify_features')
        self.assertEqual(
            f"Failed to save scores for image {img.pk}."
            f" Maybe there was another change happening at the same time"
            f" with the image's points.",
            classify_job.result_message,
            "Job should have the expected error")

    def test_row_col_mismatch_when_saving_scores(self):

        def mock_add_scores(*args, **kwargs):
            raise RowColumnMismatchError

        self.upload_data_and_train_classifier()

        img = self.upload_image_and_queue_classification()

        # Try to classify
        with mock.patch(
            'vision_backend.task_helpers.add_scores',
            mock_add_scores
        ):
            do_job('classify_features', img.pk)

        classify_job = Job.objects.get(job_name='classify_features')
        self.assertEqual(
            f"Failed to save scores for image {img.pk}."
            f" Maybe there was another change happening at the same time"
            f" with the image's points.",
            classify_job.result_message,
            "Job should have the expected error")
