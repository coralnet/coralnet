from unittest import mock

from django.core.cache import cache
from django.db.utils import IntegrityError
from django.test import override_settings
import numpy as np

from accounts.utils import get_robot_user, is_robot_user
from annotations.models import Annotation
from annotations.tests.utils import AnnotationHistoryTestMixin
from images.models import Point
from jobs.models import Job
from jobs.tasks import run_scheduled_jobs, run_scheduled_jobs_until_empty
from jobs.utils import schedule_job
from jobs.tests.utils import do_job
from ...common import Extractors
from ...exceptions import RowColumnMismatchError
from ...models import Classifier, ClassifyImageEvent, Score
from ...utils import clear_features
from .utils import (
    BaseTaskTest, do_collect_spacer_jobs, source_check_is_scheduled)


def noop(*args, **kwargs):
    pass


class SourceCheckTest(BaseTaskTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.upload_data_and_train_classifier()

    def test_basic(self):
        self.upload_image_for_classification()
        self.upload_image_for_classification()
        self.source_check_and_assert(
            "Scheduled 2 image classification(s)", expected_hidden=False)
        self.source_check_and_assert(
            "Waiting for image classification(s) to finish",
            expected_hidden=True,
        )

    def test_do_not_schedule_again(self):
        img1 = self.upload_image_for_classification()
        img2 = self.upload_image_for_classification()
        self.source_check_and_assert("Scheduled 2 image classification(s)")

        self.upload_image_for_classification()

        img1.refresh_from_db()
        img2.refresh_from_db()
        img1.annoinfo.refresh_from_db()
        img2.annoinfo.refresh_from_db()
        self.assertFalse(
            any([img1.annoinfo.classified, img2.annoinfo.classified]),
            msg="First 2 classifications shouldn't have run yet (sanity check)",
        )

        self.source_check_and_assert(
            "Scheduled 1 image classification(s)",
            assert_msg="Should not redo the original 2 classifications",
        )

    def test_schedule_check_after_last_classification(self):
        """
        After the current classifier seems to have gone over all
        classifiable images, another source-check should be scheduled
        to confirm whether the source is all caught up. That's useful
        to know when looking at job/backend dashboards.
        """
        image_1 = self.upload_image_for_classification()
        image_2 = self.upload_image_for_classification()
        self.source_check_and_assert(
            "Scheduled 2 image classification(s)")

        do_job('classify_features', image_1.pk, source_id=self.source.pk)
        self.assertFalse(
            source_check_is_scheduled(self.source.pk),
            msg="Should not schedule a check after classifying just 1 image",
        )
        do_job('classify_features', image_2.pk, source_id=self.source.pk)
        self.assertTrue(
            source_check_is_scheduled(self.source.pk),
            msg="Should schedule a check after classifying both images",
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
            source_check_is_scheduled(self.source.pk),
            msg="Should not schedule a check after classifying just 1 image,"
                " even if the other image was handled by the previous"
                " classifier",
        )
        do_job('classify_features', image_2.pk, source_id=self.source.pk)
        self.assertTrue(
            source_check_is_scheduled(self.source.pk),
            msg="Should schedule a check after classifying both images",
        )

    def test_can_still_classify_with_training_disabled(self):
        """
        Should be able to skip over the training part of the source check
        and proceed to classification, if training's disabled and there's
        a deployed classifier.
        """
        other_source = self.create_source(
            self.user,
            trains_own_classifiers=False,
            deployed_classifier=self.source.last_accepted_classifier.pk,
        )

        image = self.upload_image(self.user, other_source)
        # Extract features
        do_job('extract_features', image.pk, source_id=other_source.pk)
        do_collect_spacer_jobs()

        self.assertIsNone(other_source.last_accepted_classifier)
        self.source_check_and_assert(
            "Scheduled 1 image classification(s)", source=other_source)

    def test_time_out(self):
        for _ in range(12):
            self.upload_image_for_classification()

        with override_settings(JOB_MAX_MINUTES=-1):
            self.source_check_and_assert(
                "Scheduled 10 image classification(s) (timed out)")

        self.source_check_and_assert(
            "Scheduled 2 image classification(s)")


class SourceCheckImageCasesTest(BaseTaskTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        # Accept a classifier.
        cls.classifier_1 = cls.upload_data_and_train_classifier()

        # Accept another classifier. Override settings so that 1) we
        # don't need more images to train a new classifier, and 2) we don't
        # need improvement to mark a new classifier as accepted.
        with override_settings(
            NEW_CLASSIFIER_TRAIN_TH=0.0001,
            NEW_CLASSIFIER_IMPROVEMENT_TH=0.0001,
        ):
            cls.classifier_2 = cls.upload_data_and_train_classifier(
                new_train_images_count=0)

        cls.img1 = cls.upload_image_for_classification()
        cls.img2 = cls.upload_image_for_classification()
        cls.img3 = cls.upload_image_for_classification()

    def classify(
        self,
        images,
        # Classifier to use.
        classifier,
        # What label the classifier will use for labeling all the points.
        # The main factor for differing source-check behavior is whether
        # the labels are the same or different from one classifier to the
        # next, thus changing whether the next current classifier
        # has attribution in the annotations.
        label,
        # Whether Events are created upon classifying images; otherwise,
        # annotations have the only record of which classifier last visited.
        # False will simulate images processed before CoralNet 1.7,
        # which is when the Events were introduced.
        create_events: bool,
    ):

        self.source.trains_own_classifiers = False
        self.source.deployed_classifier = classifier
        self.source.save()

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

        if label == 'A':
            msg_mock = mock_classify_msg_all_a
        elif label == 'B':
            msg_mock = mock_classify_msg_all_b
        else:
            raise ValueError(f"Unsupported label: {label}")

        with mock.patch(
            'spacer.messages.ClassifyReturnMsg.__init__', msg_mock,
        ):
            for image in images:

                if create_events:

                    do_job('classify_features', image.pk)

                    self.assertTrue(
                        ClassifyImageEvent.objects.filter(
                            image_id=image.pk).exists(),
                        "Classification event should exist (sanity check)")

                else:

                    with mock.patch.object(ClassifyImageEvent, 'save', noop):
                        do_job('classify_features', image.pk)

                    self.assertFalse(
                        ClassifyImageEvent.objects.filter(
                            image_id=image.pk).exists(),
                        "Classification event shouldn't exist (sanity check)")

    def source_check_and_assert_scheduled_classifications(
        self, classifier, images
    ):
        self.source.trains_own_classifiers = False
        self.source.deployed_classifier = classifier
        self.source.save()

        self.source_check_and_assert(
            f"Scheduled {len(images)} image classification(s)")

        scheduled_image_ids = Job.objects \
            .filter(job_name='classify_features', status=Job.Status.PENDING) \
            .values_list('arg_identifier', flat=True)
        scheduled_image_ids = [int(pk) for pk in scheduled_image_ids]

        for image in images:
            self.assertIn(image.pk, scheduled_image_ids)

    def test_new_classifier_on_events_and_annotations(self):
        self.classify(
            [self.img1, self.img2],
            self.classifier_1,
            'A',
            create_events=True,
        )
        self.classify(
            [self.img1],
            self.classifier_2,
            'B',
            create_events=True,
        )
        self.source_check_and_assert_scheduled_classifications(
            self.classifier_2, [self.img3])

    def test_new_classifier_on_events_only(self):
        self.classify(
            [self.img1, self.img2], self.classifier_1,
            'A', create_events=True,
        )
        self.classify(
            [self.img1], self.classifier_2,
            'A', create_events=True,
        )
        self.source_check_and_assert_scheduled_classifications(
            self.classifier_2, [self.img3])

    def test_new_classifier_on_annotations_only(self):
        self.classify(
            [self.img1, self.img2], self.classifier_1,
            'A', create_events=False,
        )
        self.classify(
            [self.img1], self.classifier_2,
            'B', create_events=False,
        )
        self.source_check_and_assert_scheduled_classifications(
            self.classifier_2, [self.img3])

    def test_new_classifier_on_nothing(self):
        self.classify(
            [self.img1, self.img2], self.classifier_1,
            'A', create_events=False,
        )
        self.classify(
            [self.img1], self.classifier_2,
            'A', create_events=False,
        )
        self.source_check_and_assert_scheduled_classifications(
            self.classifier_2, [self.img1, self.img2, self.img3])

    def test_old_classifier_on_events_only(self):
        self.classify(
            [self.img1, self.img2], self.classifier_1,
            'A', create_events=True,
        )
        self.classify(
            [self.img1], self.classifier_2,
            'A', create_events=True,
        )
        self.source_check_and_assert_scheduled_classifications(
            self.classifier_1, [self.img1, self.img2, self.img3])

    def test_old_classifier_on_annotations_only(self):
        self.classify(
            [self.img1, self.img2], self.classifier_1,
            'A', create_events=False,
        )
        self.classify(
            [self.img1], self.classifier_2,
            'B', create_events=False,
        )
        self.source_check_and_assert_scheduled_classifications(
            self.classifier_1, [self.img1, self.img2, self.img3])

    def test_old_classifier_on_nothing(self):
        self.classify(
            [self.img1, self.img2], self.classifier_1,
            'A', create_events=False,
        )
        self.classify(
            [self.img1], self.classifier_2,
            'A', create_events=False,
        )
        self.source_check_and_assert_scheduled_classifications(
            self.classifier_1, [self.img3])


class ClassifyImageTest(BaseTaskTest, AnnotationHistoryTestMixin):

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
        classifier = self.upload_data_and_train_classifier()

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

        clf_1 = self.upload_data_and_train_classifier()

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
            clf_2 = self.upload_data_and_train_classifier(
                new_train_images_count=0)

        # Re-classify with a different set of
        # scores so that specific points get their labels changed (and
        # other points don't).
        with mock.patch(
            'spacer.messages.ClassifyReturnMsg.__init__', mock_classify_msg_2
        ):
            run_scheduled_jobs_until_empty()

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
        do_collect_spacer_jobs()
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
        # TODO: Point 1 here is actually the classifier's label
        #  rather than the previously-confirmed label, which is not
        #  what was intended, and perhaps misleading. The logic needs to
        #  be revisited.
        # self.assertDictEqual(
        #     event.details,
        #     {
        #         '1': dict(label=label_ids[0], result='no change'),
        #         '2': dict(label=label_ids[1], result='added'),
        #         '3': dict(label=label_ids[2], result='added'),
        #         '4': dict(label=label_ids[3], result='added'),
        #         '5': dict(label=label_ids[4], result='added'),
        #     },
        # )

    def test_classify_confirmed_image(self):
        """Attempt to classify an image where all points are confirmed."""
        self.upload_data_and_train_classifier()

        # Image with annotations
        img = self.upload_image_with_annotations('confirmed.png')
        # Extract features
        run_scheduled_jobs_until_empty()
        do_collect_spacer_jobs()
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

        for point in img.point_set.all():
            ann = point.annotation
            scores = Score.objects.filter(point=point)
            posteriors = [score.score for score in scores]
            self.assertEqual(
                scores[int(np.argmax(posteriors))].label, ann.label,
                "Max score label should match the annotation label."
                " Posteriors: {}".format(posteriors))

    def test_use_old_classifier_from_this_source(self):
        clf_1 = self.upload_data_and_train_classifier()

        # Accept another classifier.
        with override_settings(
            NEW_CLASSIFIER_TRAIN_TH=0.0001,
            NEW_CLASSIFIER_IMPROVEMENT_TH=0.0001,
        ):
            clf_2 = self.upload_data_and_train_classifier(
                new_train_images_count=0)
        self.assertNotEqual(clf_1.pk, clf_2.pk)
        self.assertEqual(clf_2.status, Classifier.ACCEPTED)

        # Actually use the first classifier.
        self.source.trains_own_classifiers = False
        self.source.deployed_classifier = clf_1
        self.source.save()

        img = self.upload_image_and_machine_classify()

        points = img.point_set.all()
        self.assertEqual(points.count(), 5)
        for point in points:
            self.assertEqual(
                point.annotation.robot_version_id, clf_1.pk,
                msg="Should classify with the first classifier",
            )

    def test_use_classifier_from_different_source(self):
        # The convenience function to train a classifier for self.source is
        # really nice to have, so we use that and then use the classifier in
        # other_source, instead of having the sources the other way around.
        classifier = self.upload_data_and_train_classifier()

        other_source = self.create_source(
            self.user,
            trains_own_classifiers=False,
            deployed_classifier=classifier.pk,
        )

        # Image without annotations
        image = self.upload_image(self.user, other_source)
        # Extract features
        do_job('extract_features', image.pk, source_id=other_source.pk)
        do_collect_spacer_jobs()
        # Classify image
        do_job('classify_features', image.pk, source_id=other_source.pk)
        image.refresh_from_db()

        points = image.point_set.all()
        self.assertEqual(points.count(), 5)
        for point in points:
            self.assertEqual(
                point.annotation.robot_version_id, classifier.pk,
                msg="Should classify with the deployed classifier",
            )

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
        do_collect_spacer_jobs()
        # Train
        run_scheduled_jobs_until_empty()
        do_collect_spacer_jobs()
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


class AbortCasesTest(BaseTaskTest):
    """Test cases where the task would abort before reaching the end."""

    def upload_image_and_schedule_classification(self):
        # Upload and extract features
        img = self.upload_image_for_classification()
        schedule_job('classify_features', img.pk, source_id=self.source.pk)
        return img

    def test_classify_nonexistent_image(self):
        """Try to classify a nonexistent image ID."""
        self.upload_data_and_train_classifier()

        img = self.upload_image_and_schedule_classification()
        # Delete img
        image_id = img.pk
        img.delete()

        # Try to classify
        run_scheduled_jobs()

        self.assert_job_failure_message(
            'classify_features',
            f"Image {image_id} does not exist.")

    def test_classify_without_features(self):
        """Try to classify an image without features extracted."""
        self.upload_data_and_train_classifier()

        img = self.upload_image_and_schedule_classification()
        # Clear features
        clear_features(img)

        # Try to classify
        run_scheduled_jobs()

        self.assert_job_failure_message(
            'classify_features',
            f"Image {img.pk} needs to have features extracted"
            f" before being classified.")

    def test_no_classifier_at_classify_task(self):
        """Try to classify an image without a classifier for the source."""
        classifier = self.upload_data_and_train_classifier()

        img = self.upload_image_and_schedule_classification()
        # Delete source's classifier
        classifier.delete()

        # Try to classify
        run_scheduled_jobs()

        self.assert_job_failure_message(
            'classify_features',
            f"Image {img.pk} can't be classified;"
            f" its source doesn't have a classifier.")

    def test_feature_format_mismatch(self):
        self.upload_data_and_train_classifier()

        img = self.upload_image_and_schedule_classification()

        # Different extractor from the source's.
        img.features.extractor = Extractors.VGG16.value
        img.features.save()

        # Try to classify.
        run_scheduled_jobs()

        self.assert_job_failure_message(
            'classify_features',
            "This image's features don't match the source's feature format."
            " Feature extraction will be redone to fix this.")

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

        img = self.upload_image_and_schedule_classification()

        # Try to classify
        with mock.patch(
            'annotations.models.Annotation.objects'
            '.update_point_annotation_if_applicable',
            mock_update_annotation
        ):
            do_job('classify_features', img.pk)

        self.assert_job_failure_message(
            'classify_features',
            f"Failed to save annotations for image {img.pk}."
            f" Maybe there was another change happening at the same time"
            f" with the image's points/annotations.")

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

        img = self.upload_image_and_schedule_classification()

        # Try to classify
        with mock.patch(
            'vision_backend.task_helpers.add_annotations',
            mock_add_annotations
        ):
            do_job('classify_features', img.pk)

        self.assert_job_failure_message(
            'classify_features',
            f"Failed to save annotations for image {img.pk}."
            f" Maybe there was another change happening at the same time"
            f" with the image's points/annotations.")

    def test_integrity_error_when_saving_scores(self):

        def mock_add_scores(*args, **kwargs):
            """
            We're lazier than the save-annotations test here: just directly
            raise an IntegrityError.
            """
            raise IntegrityError

        self.upload_data_and_train_classifier()

        img = self.upload_image_and_schedule_classification()

        # Try to classify
        with mock.patch(
            'vision_backend.task_helpers.add_scores',
            mock_add_scores
        ):
            do_job('classify_features', img.pk)

        self.assert_job_failure_message(
            'classify_features',
            f"Failed to save scores for image {img.pk}."
            f" Maybe there was another change happening at the same time"
            f" with the image's points.")

    def test_row_col_mismatch_when_saving_scores(self):

        def mock_add_scores(*args, **kwargs):
            raise RowColumnMismatchError

        self.upload_data_and_train_classifier()

        img = self.upload_image_and_schedule_classification()

        # Try to classify
        with mock.patch(
            'vision_backend.task_helpers.add_scores',
            mock_add_scores
        ):
            do_job('classify_features', img.pk)

        self.assert_job_failure_message(
            'classify_features',
            f"Failed to save scores for image {img.pk}."
            f" Maybe there was another change happening at the same time"
            f" with the image's points.")
