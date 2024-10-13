from unittest import mock

from django.conf import settings
from django.core.files.storage import default_storage
from django.test import override_settings
from spacer.data_classes import ValResults

from errorlogs.tests.utils import ErrorReportTestMixin
from images.model_utils import PointGen
from jobs.models import Job
from jobs.tasks import run_scheduled_jobs, run_scheduled_jobs_until_empty
from jobs.tests.utils import do_job, JobUtilsMixin
from jobs.utils import get_or_create_job, start_job
from lib.tests.utils import EmailAssertionsMixin
from ...common import Extractors
from ...models import Classifier
from ...queues import get_queue_class
from ...task_helpers import handle_spacer_result
from .utils import (
    BaseTaskTest, do_collect_spacer_jobs, source_check_is_scheduled)


def mock_training_results(
    acc_custom=None, pc_accs_custom=None,
    ref_accs_custom=None, runtime_custom=None,
):
    def mock_return_msg(self, acc, pc_accs, ref_accs, runtime):
        self.acc = acc_custom or acc
        self.pc_accs = pc_accs_custom or pc_accs
        self.ref_accs = ref_accs_custom or ref_accs
        self.runtime = runtime_custom or runtime
    return mock.patch(
        'spacer.messages.TrainClassifierReturnMsg.__init__', mock_return_msg)


class TrainClassifierTest(BaseTaskTest, JobUtilsMixin):

    def test_source_check(self):
        # Provide enough data for training. Extract features.
        self.upload_images_for_training()
        run_scheduled_jobs_until_empty()
        do_collect_spacer_jobs()

        job, created = get_or_create_job('check_source', self.source.pk)
        self.assertFalse(created, "Should have scheduled a source check")
        start_job(job)
        self.assert_job_result_message(
            'check_source',
            "Scheduled training")

        do_job(
            'check_source', self.source.pk,
            source_id=self.source.pk)
        self.assert_job_result_message(
            'check_source',
            "Waiting for training to finish")

    def test_success(self):
        # Provide enough data for training. Extract features.
        val_image_count = 1
        self.upload_images_for_training(
            train_image_count=3, val_image_count=val_image_count)
        run_scheduled_jobs_until_empty()
        do_collect_spacer_jobs()

        # Train a classifier
        run_scheduled_jobs_until_empty()

        # This source should now have a classifier (though training hasn't
        # been collected yet)
        self.assertTrue(
            Classifier.objects.filter(source=self.source).count() > 0)

        # Collect training. Use mock to determine return message details.
        with mock_training_results(
            acc_custom=0.52,
            ref_accs_custom=[
                0.39, 0.46, 0.5, 0.51, 0.52,
                0.523, 0.522, 0.5224, 0.5223, 0.5223,
            ],
            runtime_custom=90,
        ):
            do_collect_spacer_jobs()

        # Now we should have a trained classifier whose accuracy is the best so
        # far (due to having no previous classifiers), and thus it should have
        # been marked as accepted.
        classifier = self.source.classifier_set.latest('pk')
        self.assertEqual(classifier.status, Classifier.ACCEPTED)
        # Classifier acceptance is immaterial to Job success, but still,
        # should have succeeded.
        self.assertEqual(classifier.train_job.status, Job.Status.SUCCESS)

        # Check other fields.
        self.assertEqual(classifier.nbr_train_images, 3 + 1)
        self.assertEqual(classifier.runtime_train, 90)
        self.assertEqual(classifier.accuracy, 0.52)
        self.assertEqual(
            classifier.epoch_ref_accuracy,
            '[3900, 4600, 5000, 5100, 5200, 5230, 5220, 5224, 5223, 5223]')

        # Also check that the actual classifier is created in storage.
        self.assertTrue(default_storage.exists(
            settings.ROBOT_MODEL_FILE_PATTERN.format(pk=classifier.pk)))

        # And that the val results are stored.
        valresult_path = settings.ROBOT_MODEL_VALRESULT_PATTERN.format(
            pk=classifier.pk)
        self.assertTrue(default_storage.exists(valresult_path))

        # Check that the point-count in val_res is what it should be.
        val_res = ValResults.load(
            default_storage.spacer_data_loc(valresult_path))
        points_per_image = PointGen.from_db_value(
            self.source.default_point_generation_method).total_points
        self.assertEqual(
            len(val_res.gt),
            val_image_count * points_per_image)

        self.assert_job_result_message(
            'train_classifier',
            f"New classifier accepted: {classifier.pk}")

        self.assert_job_persist_value('train_classifier', True)

        self.source.refresh_from_db()
        self.assertEqual(
            self.source.deployed_classifier.pk, classifier.pk,
            msg="Should auto-populate deployed_classifier",
        )

    @override_settings(
        TRAINING_MIN_IMAGES=3,
        NEW_CLASSIFIER_TRAIN_TH=1.1,
        NEW_CLASSIFIER_IMPROVEMENT_TH=1.01,
    )
    def test_train_second_classifier(self):
        """
        Accept a second classifier in a source which already has an accepted
        classifier.
        """
        # Provide enough data for training. Extract features.
        self.upload_images_for_training()
        run_scheduled_jobs_until_empty()
        do_collect_spacer_jobs()
        # Submit classifier.
        run_scheduled_jobs_until_empty()

        # Collect classifier.
        do_collect_spacer_jobs()

        clf_1 = self.source.last_accepted_classifier

        # Upload enough additional images for the next training to happen.
        self.upload_images_for_training(
            train_image_count=2, val_image_count=0)
        # Extract features.
        run_scheduled_jobs_until_empty()
        do_collect_spacer_jobs()
        # Submit classifier.
        run_scheduled_jobs_until_empty()

        # Collect classifier. Use mock to ensure a high enough accuracy
        # improvement to consider the classifier accepted.
        with mock_training_results(
            acc_custom=0.57,
            pc_accs_custom=[0.5],
        ):
            do_collect_spacer_jobs()

        clf_2 = self.source.last_accepted_classifier

        self.assertNotEqual(clf_1.pk, clf_2.pk, "Should have a new classifier")
        self.assertEqual(
            clf_2.status, Classifier.ACCEPTED, "Should be accepted")
        self.assertEqual(clf_2.nbr_train_images, clf_1.nbr_train_images + 2)

        self.source.refresh_from_db()
        self.assertEqual(
            self.source.deployed_classifier.pk, clf_2.pk,
            msg="Should auto-populate deployed_classifier"
        )

    def test_train_on_confirmed_only(self):
        def upload_image_without_annotations(filename):
            return self.upload_image(
                self.user, self.source, image_options=dict(filename=filename))

        def upload_image_with_machine_annotations(filename):
            image = upload_image_without_annotations(filename)
            classifier = Classifier(
                source=self.source,
                nbr_train_images=1,
                status=Classifier.ACCEPTED,
            )
            classifier.save()
            self.add_robot_annotations(classifier, image)
            return image

        self.upload_image_with_annotations('train1.png')
        self.upload_image_with_annotations('train2.png')
        upload_image_without_annotations('train3.png')
        upload_image_with_machine_annotations('train4.png')
        upload_image_with_machine_annotations('train5.png')

        upload_image_with_machine_annotations('val1.png')
        upload_image_with_machine_annotations('val2.png')
        upload_image_without_annotations('val3.png')
        self.upload_image_with_annotations('val4.png')

        # Sanity check
        self.assertEqual(self.source.image_set.confirmed().count(), 3)
        self.assertEqual(self.source.image_set.unconfirmed().count(), 4)
        self.assertEqual(self.source.image_set.unclassified().count(), 2)

        # Extract features.
        run_scheduled_jobs_until_empty()
        do_collect_spacer_jobs()
        # Submit classifier.
        run_scheduled_jobs_until_empty()

        pending_classifier = self.source.classifier_set.latest('pk')
        self.assertEqual(
            pending_classifier.nbr_train_images, 3,
            msg="Classification should be submitted with only 3 images")

    def test_source_check_after_finishing(self):
        # Provide enough data for training. Extract features.
        self.upload_images_for_training()
        run_scheduled_jobs_until_empty()
        do_collect_spacer_jobs()
        # Submit classifier.
        run_scheduled_jobs_until_empty()

        self.assertFalse(source_check_is_scheduled(self.source.pk))

        # Collect classifier.
        do_collect_spacer_jobs()

        self.assertTrue(
            source_check_is_scheduled(self.source.pk),
            msg="Source check should be scheduled after collecting training")

    def test_with_dupe_points(self):
        """
        Training data has two points with the same row/column.
        Training should complete as normal, and returned results shouldn't
        de-dupe the dupe points.
        """

        # Upload annotated images, some with dupe points
        images_with_dupe_point = dict(
            val=self.upload_image_with_dupe_points(
                'val.png', with_labels=True),
            # Uploading ref.png before train.png should allow ref.png to be
            # picked for the ref set, and train.png for the train set
            ref=self.upload_image_with_dupe_points(
                'ref.png', with_labels=True),
            train=self.upload_image_with_dupe_points(
                'train.png', with_labels=True),
        )

        # Extract features
        run_scheduled_jobs_until_empty()
        do_collect_spacer_jobs()
        # Train classifier; call internal job-collection methods to
        # get access to the job return msg.
        run_scheduled_jobs_until_empty()
        queue = get_queue_class()()
        job_return_msg = queue.collect_job(queue.get_collectable_jobs()[0])[0]
        handle_spacer_result(job_return_msg)
        spacer_task = job_return_msg.original_job.tasks[0]

        # Check each data set

        for set_name in ['train', 'ref', 'val']:

            labels_data = spacer_task.labels[set_name]
            feature_location = \
                images_with_dupe_point[set_name].features.data_loc
            image_labels_data = labels_data[feature_location.key]
            self.assertEqual(
                len(self.rowcols_with_dupes_included), len(image_labels_data),
                f"{set_name} data count should include dupe points")
            rowcols = [
                (row, col) for row, col, label in image_labels_data]
            self.assertListEqual(
                self.rowcols_with_dupes_included, sorted(rowcols),
                f"{set_name} data rowcols should include dupe points")

        # Check valresults

        val_res = ValResults.load(spacer_task.valresult_loc)
        self.assertEqual(
            len(self.rowcols_with_dupes_included), len(val_res.gt),
            "Valresults count should include dupe points")

        # Check that there's an accepted classifier.

        latest_classifier = self.source.classifier_set.latest('pk')
        self.assertEqual(latest_classifier.status, Classifier.ACCEPTED)


@override_settings(
    TRAINING_MIN_IMAGES=3,
    # 3 -> 4 is sufficient for retrain; 4 -> 6 also is; 4 -> 5 isn't
    NEW_CLASSIFIER_TRAIN_TH=1.3,
    NEW_CLASSIFIER_IMPROVEMENT_TH=1.01,
)
class RetrainLogicTest(BaseTaskTest, JobUtilsMixin):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        # Prepare training images + features, and train one classifier.
        # This one should always stay accepted, so there's at least one
        # accepted during this class's tests.
        cls.upload_images_for_training(train_image_count=2, val_image_count=1)
        run_scheduled_jobs_until_empty()
        do_collect_spacer_jobs()
        run_scheduled_jobs_until_empty()
        do_collect_spacer_jobs()
        first_classifier = cls.source.last_accepted_classifier
        assert first_classifier.status == Classifier.ACCEPTED

        # Another classifier. Tests can change the status of this one to try
        # different 'previous classifier status' cases.
        cls.upload_images_for_training(train_image_count=1, val_image_count=0)
        run_scheduled_jobs_until_empty()
        do_collect_spacer_jobs()
        run_scheduled_jobs_until_empty()
        with mock_training_results(
            acc_custom=0.57,
            pc_accs_custom=[0.5],
        ):
            do_collect_spacer_jobs()

        cls.previous_classifier = cls.source.last_accepted_classifier
        assert cls.previous_classifier.status == Classifier.ACCEPTED

    def do_test_retrain_logic(
        self, previous_status, meets_retrain_threshold,
        expect_retrain, expected_source_check_result,
    ):

        self.previous_classifier.status = previous_status
        self.previous_classifier.save()

        if meets_retrain_threshold:
            self.upload_images_for_training(
                train_image_count=2, val_image_count=0)
        else:
            self.upload_images_for_training(
                train_image_count=1, val_image_count=0)

        # Extract features.
        run_scheduled_jobs_until_empty()
        do_collect_spacer_jobs()
        # Check source.
        run_scheduled_jobs()
        # Submit classifier.
        run_scheduled_jobs()

        classifier = self.source.classifier_set.latest('pk')
        if expect_retrain:
            self.assertNotEqual(
                classifier.pk, self.previous_classifier.pk,
                "Should have created a new classifier (though not trained yet")
        else:
            self.assertEqual(
                classifier.pk, self.previous_classifier.pk,
                "Should not have created a new classifier")

        self.assert_job_result_message(
            'check_source', expected_source_check_result)

    def test_previous_accepted_and_below_threshold(self):
        self.do_test_retrain_logic(
            Classifier.ACCEPTED, False, False,
            "Source seems to be all caught up."
            " Need 6 annotated images for next training, and currently have 5",
        )

    def test_previous_accepted_and_above_threshold(self):
        self.do_test_retrain_logic(
            Classifier.ACCEPTED, True, True,
            "Scheduled training",
        )

    def test_previous_rejected_and_below_threshold(self):
        self.do_test_retrain_logic(
            Classifier.REJECTED_ACCURACY, False, False,
            "Source seems to be all caught up."
            " Need 6 annotated images for next training, and currently have 5",
        )

    def test_previous_rejected_and_above_threshold(self):
        self.do_test_retrain_logic(
            Classifier.REJECTED_ACCURACY, True, True,
            "Scheduled training",
        )

    def test_previous_lacking_unique_and_below_threshold(self):
        self.do_test_retrain_logic(
            Classifier.LACKING_UNIQUE_LABELS, False, False,
            "Source seems to be all caught up."
            " Need 6 annotated images for next training, and currently have 5",
        )

    def test_previous_lacking_unique_and_above_threshold(self):
        self.do_test_retrain_logic(
            Classifier.LACKING_UNIQUE_LABELS, True, True,
            "Scheduled training",
        )

    def test_previous_pending_and_below_threshold(self):
        """
        In practice, this case should indeed say "Scheduled training" but should
        in fact defer to the training that's already in progress for this
        source, since creating another training would be creating a duplicate
        active job (which isn't allowed).
        """
        self.do_test_retrain_logic(
            Classifier.TRAIN_PENDING, False, True,
            "Scheduled training",
        )

    def test_previous_errored_and_below_threshold(self):
        """
        If previous got an error, then we're still due for a new classifier,
        even if the next threshold hasn't been met.
        """
        self.do_test_retrain_logic(
            Classifier.TRAIN_ERROR, False, True,
            "Scheduled training",
        )


class AbortCasesTest(
    BaseTaskTest, EmailAssertionsMixin, ErrorReportTestMixin, JobUtilsMixin,
):
    """
    Test cases (besides retrain logic) where the train task or collection would
    abort before reaching the end.
    """
    def test_training_disabled_at_source_check(self):
        """
        Try to schedule training for a source which has training disabled.
        """
        # Ensure the source is otherwise ready for training.
        self.upload_images_for_training()
        # Extract features
        run_scheduled_jobs_until_empty()
        do_collect_spacer_jobs()

        # Create a classifier in another source.
        other_source = self.create_source(self.user)
        self.create_labelset(self.user, other_source, self.labels)
        classifier = self.create_robot(other_source)

        # Disable training, opting to deploy the existing classifier instead.
        self.source.trains_own_classifiers = False
        self.source.deployed_classifier = classifier
        self.source.save()

        # Check source
        run_scheduled_jobs_until_empty()

        self.assert_job_result_message(
            'check_source',
            f"Source seems to be all caught up."
            f" Source has training disabled"
        )

    def test_below_minimum_images(self):
        """
        Try to train while below the minimum number of images needed for first
        training.
        """
        # Prepare some training images + features.
        self.upload_images_for_training()
        run_scheduled_jobs_until_empty()
        do_collect_spacer_jobs()

        # But set CoralNet's requirement 1 higher than that image count.
        min_images = self.source.image_set.count() + 1

        with override_settings(TRAINING_MIN_IMAGES=min_images):
            # Check source
            run_scheduled_jobs_until_empty()

        self.assert_job_result_message(
            'check_source',
            f"Can't train first classifier:"
            f" Not enough annotated images for initial training"
        )

    def test_training_disabled_at_train_task(self):
        """
        Try to start training for a source which has training disabled.
        """
        # Ensure the source is otherwise ready for training.
        self.upload_images_for_training()
        # Extract features
        run_scheduled_jobs_until_empty()
        do_collect_spacer_jobs()

        # Create a classifier in another source.
        other_source = self.create_source(self.user)
        self.create_labelset(self.user, other_source, self.labels)
        classifier = self.create_robot(other_source)

        # Disable training, opting to deploy the existing classifier instead.
        self.source.trains_own_classifiers = False
        self.source.deployed_classifier = classifier
        self.source.save()

        # Try to train
        do_job('train_classifier', self.source.pk, source_id=self.source.pk)

        self.assert_job_failure_message(
            'train_classifier',
            "Training is disabled for this source"
        )

    def test_train_invalid_rowcol(self):

        train_images, _ = self.upload_images_for_training(
            train_image_count=2,
            val_image_count=1,
        )

        # Extract features normally.
        run_scheduled_jobs_until_empty()
        do_collect_spacer_jobs()

        # Say one training image's features are legacy format.
        train_image = train_images[0]
        train_image.features.has_rowcols = False
        train_image.features.save()

        # Try to train.
        do_job('train_classifier', self.source.pk, source_id=self.source.pk)
        self.assert_job_failure_message(
            'train_classifier',
            "This source has 1 feature vector(s) without rows/columns,"
            " and this is no longer accepted for training."
            " Feature extractions will be redone to fix this.")
        train_image.features.refresh_from_db()
        self.assertFalse(
            train_image.features.extracted, "Features should be reset")

    def test_val_invalid_rowcol(self):

        _, val_images = self.upload_images_for_training(
            train_image_count=2,
            val_image_count=3,
        )

        # Extract features normally.
        run_scheduled_jobs_until_empty()
        do_collect_spacer_jobs()

        # Say at least one validation image's features are legacy format.
        for image in [val_images[0], val_images[1]]:
            image.features.has_rowcols = False
            image.features.save()

        # Try to train.
        do_job('train_classifier', self.source.pk, source_id=self.source.pk)
        self.assert_job_failure_message(
            'train_classifier',
            "This source has 2 feature vector(s) without rows/columns,"
            " and this is no longer accepted for training."
            " Feature extractions will be redone to fix this.")
        for image in [val_images[0], val_images[1]]:
            image.features.refresh_from_db()
            self.assertFalse(
                image.features.extracted, "Features should be reset")

    def test_feature_format_mismatch(self):

        train_images, val_images = self.upload_images_for_training(
            train_image_count=2,
            val_image_count=1,
        )

        # Extract features normally.
        run_scheduled_jobs_until_empty()
        do_collect_spacer_jobs()

        # Say at least one image's features are a different extractor format.
        for image in [train_images[0], val_images[0]]:
            image.features.extractor = Extractors.VGG16.value
            image.features.save()

        # Try to train.
        do_job('train_classifier', self.source.pk, source_id=self.source.pk)
        self.assert_job_failure_message(
            'train_classifier',
            "This source has 2 feature vector(s) which don't match"
            " the source's feature format."
            " Feature extractions will be redone to fix this.")
        for image in [train_images[0], val_images[0]]:
            image.features.refresh_from_db()
            self.assertFalse(
                image.features.extracted, "Features should be reset")

    def do_lacking_unique_labels_test(self, uploads):
        for filename, annotations in uploads:
            img = self.upload_image(
                self.user, self.source, image_options=dict(filename=filename))
            self.add_annotations(
                self.user, img, annotations)
        # Extract features.
        run_scheduled_jobs_until_empty()
        do_collect_spacer_jobs()

        # Try to train classifier.
        run_scheduled_jobs_until_empty()

        classifier = self.source.classifier_set.latest('pk')
        self.assertEqual(
            classifier.status, Classifier.LACKING_UNIQUE_LABELS,
            msg="Classifier status should be correct")

        self.assert_job_failure_message(
            'train_classifier',
            f"Classifier {classifier.pk} [Source: {self.source.name}"
            f" [{self.source.pk}]] was declined training, because there"
            f" weren't enough annotations of at least 2 different labels.")

        self.assertFalse(
            self.source.ready_to_train()[0],
            msg="Source should not immediately be considered for retraining")

    def test_train_ref_one_common_label(self):
        """
        Try to train when the train and ref sets only have 1 label in common.
        """
        uploads = [
            # First 'train' image will end up in the reference set
            ('train1.png', {1: 'A', 2: 'A', 3: 'A', 4: 'A', 5: 'A'}),
            # This will end up in the train set
            ('train2.png', {1: 'A', 2: 'B', 3: 'A', 4: 'A', 5: 'B'}),
            # Val set, but doesn't matter in this case
            ('val1.png', {1: 'A', 2: 'B', 3: 'A', 4: 'A', 5: 'B'}),
        ]
        self.do_lacking_unique_labels_test(uploads)

    def test_trainref_val_zero_common_labels(self):
        """
        Try to train when the train+ref sets and the val set have 0 labels
        in common.
        """
        uploads = [
            # First 'train' image will end up in the reference set
            ('train1.png', {1: 'B', 2: 'A', 3: 'B', 4: 'A', 5: 'C'}),
            # This will end up in the train set.
            # Train+ref = A and B in common. So the check that train+ref has
            # at least 2 classes will pass.
            ('train2.png', {1: 'A', 2: 'B', 3: 'A', 4: 'A', 5: 'B'}),
            # Val set. Only has C, thus nothing in common with train+ref
            # (even though ref by itself has C).
            ('val1.png', {1: 'C', 2: 'C', 3: 'C', 4: 'C', 5: 'C'}),
        ]
        self.do_lacking_unique_labels_test(uploads)

    def test_spacer_error(self):
        # Prepare training images + features.
        self.upload_images_for_training()
        run_scheduled_jobs_until_empty()
        do_collect_spacer_jobs()

        # Submit training, with a spacer function mocked to
        # throw an error.
        def raise_error(*args):
            raise ValueError("A spacer error")
        with mock.patch('spacer.tasks.train_classifier', raise_error):
            run_scheduled_jobs_until_empty()

        # Collect training.
        do_collect_spacer_jobs()

        self.assert_job_failure_message(
            'train_classifier',
            "ValueError: A spacer error")

        self.assert_job_persist_value('train_classifier', False)

        self.assert_error_log_saved(
            "ValueError",
            "A spacer error",
        )
        self.assert_latest_email(
            "Spacer job failed: train_classifier",
            ["ValueError: A spacer error"],
        )

    def test_classifier_deleted_before_collection(self):
        """
        Run the train task, then delete the classifier from the DB, then
        try to collect the train result.
        """
        self.upload_images_for_training()
        # Extract features.
        run_scheduled_jobs_until_empty()
        do_collect_spacer_jobs()
        # Train classifier.
        run_scheduled_jobs_until_empty()

        # Delete classifier.
        classifier = self.source.classifier_set.latest('pk')
        classifier_id = classifier.pk
        classifier.delete()

        # Collect training.
        do_collect_spacer_jobs()

        self.assert_job_failure_message(
            'train_classifier',
            f"Classifier {classifier_id} doesn't exist anymore.")

    @override_settings(
        TRAINING_MIN_IMAGES=3,
        NEW_CLASSIFIER_TRAIN_TH=1.1,
        # Need 50% -> 75%
        NEW_CLASSIFIER_IMPROVEMENT_TH=1.5,
    )
    def test_classifier_rejected(self):
        """
        Run the train task, then collect the classifier and find that it's
        not enough of an improvement over the previous.
        """
        # Train one classifier.
        self.upload_images_for_training()
        run_scheduled_jobs_until_empty()
        do_collect_spacer_jobs()
        run_scheduled_jobs_until_empty()
        with mock_training_results(
            acc_custom=0.5,
            pc_accs_custom=[],
        ):
            do_collect_spacer_jobs()

        # Upload enough additional images for the next training to happen.
        self.upload_images_for_training(
            train_image_count=2, val_image_count=0)
        run_scheduled_jobs_until_empty()
        do_collect_spacer_jobs()
        run_scheduled_jobs_until_empty()

        # Collect classifier. Use mock to ensure a low enough accuracy
        # improvement to reject the classifier.
        with mock_training_results(
            acc_custom=0.74,
            pc_accs_custom=[0.5],
        ):
            do_collect_spacer_jobs()

        classifier = self.source.classifier_set.latest('pk')
        self.assertEqual(classifier.status, Classifier.REJECTED_ACCURACY)

        self.assert_job_result_message(
            'train_classifier',
            f"Not accepted as the source's new classifier."
            f" Highest accuracy among previous classifiers"
            f" on the latest dataset: {0.5:.2f},"
            f" threshold to accept new: {0.75:.2f},"
            f" accuracy from this training: {0.74:.2f}")

        self.assert_job_persist_value('train_classifier', True)


class TrainRefValSetsTest(BaseTaskTest):

    def prep_images(
        self, train_image_count=0, val_image_count=0, points_per_image=2,
    ):
        self.source.default_point_generation_method = \
            PointGen(type='simple', points=points_per_image).db_value
        self.source.save()
        self.upload_images_for_training(
            train_image_count=train_image_count,
            val_image_count=val_image_count,
            # As long as there are at least 2 points per image, this will
            # ensure each image has at least 2 unique labels.
            annotation_scheme='cycle',
        )

    def do_test(self, expected_set_sizes):
        # Extract features.
        run_scheduled_jobs_until_empty()
        do_collect_spacer_jobs()

        # Train classifier.
        with mock.patch(
                'spacer.messages.TrainClassifierMsg.__init__') as mock_init:
            run_scheduled_jobs_until_empty()
        labels = mock_init.call_args.kwargs['labels']
        for set_name in ['train', 'ref', 'val']:
            self.assertEqual(
                len(labels[set_name]), expected_set_sizes[set_name],
                msg=f"{set_name} set should have the expected image count",
            )

    def test_minimum(self):
        self.prep_images(
            train_image_count=2,
            val_image_count=1,
        )
        self.do_test(dict(train=1, ref=1, val=1))

    def test_max_with_1_ref(self):
        self.prep_images(
            train_image_count=10,
            val_image_count=1,
        )
        self.do_test(dict(train=9, ref=1, val=1))

    def test_min_with_2_ref(self):
        self.prep_images(
            train_image_count=11,
            val_image_count=1,
        )
        self.do_test(dict(train=9, ref=2, val=1))

    @override_settings(TRAINING_BATCH_LABEL_COUNT=4)
    def test_mod_10_within_batch_size(self):
        self.prep_images(
            train_image_count=11,
            val_image_count=1,
        )
        self.do_test(dict(train=9, ref=2, val=1))

    @override_settings(TRAINING_BATCH_LABEL_COUNT=3)
    def test_mod_10_over_batch_size(self):
        self.prep_images(
            train_image_count=11,
            val_image_count=1,
        )
        self.do_test(dict(train=10, ref=1, val=1))


class LabelFilteringTest(BaseTaskTest):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.source.default_point_generation_method = \
            PointGen(type='simple', points=3).db_value
        cls.source.save()

    def test_annotations_not_in_training_labelset(self):
        # This image will go into ref, and will get annotated with A and B.
        self.upload_images_for_training(
            train_image_count=1,
            val_image_count=0,
            annotation_scheme='cycle',
            label_codes=['A', 'B'],
        )
        # This image will go into train, and will get annotated with A, B, C
        # (1 each).
        # Since ref doesn't have C, the C will be left out of training.
        self.upload_images_for_training(
            train_image_count=1,
            val_image_count=0,
            annotation_scheme='cycle',
            label_codes=['A', 'B', 'C'],
        )
        # Val image doesn't matter for this test.
        self.upload_images_for_training(
            train_image_count=0,
            val_image_count=1,
        )

        # Extract features normally.
        run_scheduled_jobs_until_empty()
        do_collect_spacer_jobs()

        # Try to train.
        job = do_job(
            'train_classifier', self.source.pk, source_id=self.source.pk)

        # Call internal job-collection methods to
        # get access to the job return msg.
        queue = get_queue_class()()
        job_return_msg = queue.collect_job(queue.get_collectable_jobs()[0])[0]
        training_task_labels = job_return_msg.original_job.tasks[0].labels
        self.assertEqual(len(training_task_labels.ref), 1)
        self.assertEqual(
            training_task_labels.ref.label_count, 3,
            msg="Ref should have all of its annotations"
        )
        self.assertEqual(len(training_task_labels.train), 1)
        self.assertEqual(
            training_task_labels.train.label_count, 2,
            msg="Train should have one annotation filtered out"
        )
        handle_spacer_result(job_return_msg)

        job.refresh_from_db()
        self.assertEqual(
            job.status, Job.Status.SUCCESS,
            "Training should have succeeded, indicating no issues"
            " loading features for the training, despite the"
            " filtered-out annotation")
