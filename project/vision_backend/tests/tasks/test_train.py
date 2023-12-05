import math
from unittest import mock

from django.conf import settings
from django.core.files.storage import get_storage_class
from django.test import override_settings
from spacer.data_classes import ValResults

from errorlogs.tests.utils import ErrorReportTestMixin
from images.model_utils import PointGen
from jobs.tasks import run_scheduled_jobs_until_empty
from jobs.tests.utils import (
    JobUtilsMixin, queue_and_run_job, run_pending_job)
from lib.tests.utils import EmailAssertionsMixin
from ...models import Classifier
from ...queues import get_queue_class
from ...task_helpers import handle_spacer_result
from .utils import BaseTaskTest, queue_and_run_collect_spacer_jobs


class TrainClassifierTest(BaseTaskTest, JobUtilsMixin):

    def test_source_check(self):
        # Provide enough data for training. Extract features.
        self.upload_images_for_training()
        run_scheduled_jobs_until_empty()
        queue_and_run_collect_spacer_jobs()

        run_pending_job('check_source', self.source.pk)
        self.assert_job_result_message(
            'check_source',
            "Queued training")

        queue_and_run_job(
            'check_source', self.source.pk,
            source_id=self.source.pk)
        self.assert_job_result_message(
            'check_source',
            "Waiting for training to finish")

    def test_success(self):
        # Provide enough data for training. Extract features.
        val_image_count = 1
        self.upload_images_for_training(
            val_image_count=val_image_count)
        run_scheduled_jobs_until_empty()
        queue_and_run_collect_spacer_jobs()

        # Train a classifier
        run_scheduled_jobs_until_empty()

        # This source should now have a classifier (though training hasn't
        # been collected yet)
        self.assertTrue(
            Classifier.objects.filter(source=self.source).count() > 0)

        # Collect training
        queue_and_run_collect_spacer_jobs()

        # Now we should have a trained classifier whose accuracy is the best so
        # far (due to having no previous classifiers), and thus it should have
        # been marked as accepted
        latest_classifier = self.source.classifier_set.latest('pk')
        self.assertEqual(latest_classifier.status, Classifier.ACCEPTED)

        # Also check that the actual classifier is created in storage.
        storage = get_storage_class()()
        self.assertTrue(storage.exists(
            settings.ROBOT_MODEL_FILE_PATTERN.format(pk=latest_classifier.pk)))

        # And that the val results are stored.
        valresult_path = settings.ROBOT_MODEL_VALRESULT_PATTERN.format(
            pk=latest_classifier.pk)
        self.assertTrue(storage.exists(valresult_path))

        # Check that the point-count in val_res is what it should be.
        val_res = ValResults.load(storage.spacer_data_loc(valresult_path))
        point_gen_method = PointGen.db_to_args_format(
            self.source.default_point_generation_method)
        points_per_image = point_gen_method['simple_number_of_points']
        self.assertEqual(
            len(val_res.gt),
            val_image_count * points_per_image)

        self.assert_job_result_message(
            'train_classifier',
            f"New classifier accepted: {latest_classifier.pk}")

        self.assert_job_persist_value('train_classifier', True)

    def test_train_second_classifier(self):
        """
        Accept a second classifier in a source which already has an accepted
        classifier.
        """
        def mock_train_msg_1(
                self_, acc, pc_accs, ref_accs, runtime):
            self_.acc = 0.5
            self_.pc_accs = pc_accs
            self_.ref_accs = ref_accs
            self_.runtime = runtime

        def mock_train_msg_2(
                self_, acc, pc_accs, ref_accs, runtime):
            self_.acc = (0.5*settings.NEW_CLASSIFIER_IMPROVEMENT_TH) + 0.001
            self_.pc_accs = [0.5]
            self_.ref_accs = ref_accs
            self_.runtime = runtime

        # Provide enough data for training. Extract features.
        self.upload_images_for_training()
        run_scheduled_jobs_until_empty()
        queue_and_run_collect_spacer_jobs()
        # Submit classifier.
        run_scheduled_jobs_until_empty()

        # Collect classifier. Use mock to specify a particular accuracy.
        with mock.patch(
                'spacer.messages.TrainClassifierReturnMsg.__init__',
                mock_train_msg_1):
            queue_and_run_collect_spacer_jobs()

        clf_1 = self.source.get_current_classifier()

        # Upload enough additional images for the next training to happen.
        old_image_count = settings.TRAINING_MIN_IMAGES + 1
        new_image_count = math.ceil(
            old_image_count*settings.NEW_CLASSIFIER_TRAIN_TH)
        added_image_count = new_image_count - old_image_count
        self.upload_images_for_training(
            train_image_count=added_image_count, val_image_count=0)
        # Extract features.
        run_scheduled_jobs_until_empty()
        queue_and_run_collect_spacer_jobs()
        # Submit classifier.
        run_scheduled_jobs_until_empty()

        # Collect classifier. Use mock to ensure a high enough accuracy
        # improvement to consider the classifier accepted.
        with mock.patch(
                'spacer.messages.TrainClassifierReturnMsg.__init__',
                mock_train_msg_2):
            queue_and_run_collect_spacer_jobs()

        clf_2 = self.source.get_current_classifier()

        self.assertNotEqual(clf_1.pk, clf_2.pk, "Should have a new classifier")
        self.assertGreater(
            clf_2.nbr_train_images, clf_1.nbr_train_images,
            "Second classifier's training-image count should be greater")
        self.assertGreater(
            clf_2.accuracy, clf_1.accuracy,
            "Second classifier's accuracy should be greater")

    def test_with_dupe_points(self):
        """
        Images in the training set and validation set have two points with the
        same row/column.
        """

        # Upload annotated images with dupe points
        val_image_with_dupe_point = self.upload_image_with_dupe_points(
            'val.png', with_labels=True)
        training_image_with_dupe_point = self.upload_image_with_dupe_points(
            'train.png', with_labels=True)
        # Other annotated images to get enough for training
        self.upload_images_for_training(
            train_image_count=settings.TRAINING_MIN_IMAGES-1,
            val_image_count=0)

        # Extract features
        run_scheduled_jobs_until_empty()
        queue_and_run_collect_spacer_jobs()
        # Train classifier; call internal job-collection methods to
        # get access to the job return msg.
        run_scheduled_jobs_until_empty()
        queue = get_queue_class()()
        job_return_msg = queue.collect_job(queue.get_collectable_jobs()[0])[0]
        handle_spacer_result(job_return_msg)
        spacer_task = job_return_msg.original_job.tasks[0]

        # Check training data

        storage = get_storage_class()()
        train_data = spacer_task.train_labels.data
        feature_filepath = settings.FEATURE_VECTOR_FILE_PATTERN.format(
            full_image_path=training_image_with_dupe_point.original_file.name)
        feature_location = storage.spacer_data_loc(feature_filepath)
        image_train_data = train_data[feature_location.key]
        self.assertEqual(
            len(self.rowcols_with_dupes_included), len(image_train_data),
            "Training data count should include dupe points")
        rowcols = [
            (row, col) for row, col, label in image_train_data]
        self.assertListEqual(
            self.rowcols_with_dupes_included, sorted(rowcols),
            "Training data rowcols should include dupe points")

        # Check validation data

        val_data = spacer_task.val_labels.data
        feature_filepath = settings.FEATURE_VECTOR_FILE_PATTERN.format(
            full_image_path=val_image_with_dupe_point.original_file.name)
        feature_location = storage.spacer_data_loc(feature_filepath)
        image_val_data = val_data[feature_location.key]
        self.assertEqual(
            len(self.rowcols_with_dupes_included), len(image_val_data),
            "Validation data count should include dupe points")
        rowcols = [
            (row, col) for row, col, label in image_val_data]
        self.assertListEqual(
            self.rowcols_with_dupes_included, sorted(rowcols),
            "Validation data rowcols should include dupe points")

        # Check valresults

        val_res = ValResults.load(spacer_task.valresult_loc)
        self.assertEqual(
            len(self.rowcols_with_dupes_included), len(val_res.gt),
            "Valresults count should include dupe points")

        # Check that there's an accepted classifier.

        latest_classifier = self.source.classifier_set.latest('pk')
        self.assertEqual(latest_classifier.status, Classifier.ACCEPTED)


class AbortCasesTest(
    BaseTaskTest, EmailAssertionsMixin, ErrorReportTestMixin, JobUtilsMixin,
):
    """
    Test cases where the task or collection would abort before reaching the
    end.
    """
    def test_classification_disabled(self):
        """Try to train for a source which has classification disabled."""
        # Ensure the source is otherwise ready for training.
        self.upload_images_for_training()
        # Extract features
        run_scheduled_jobs_until_empty()
        queue_and_run_collect_spacer_jobs()

        # Disable classification.
        self.source.enable_robot_classifier = False
        self.source.save()

        # Check source
        run_scheduled_jobs_until_empty()

        self.assert_job_result_message(
            'check_source',
            f"Can't train first classifier:"
            f" Source has classifier disabled"
        )

    def test_below_minimum_images(self):
        """
        Try to train while below the minimum number of images needed for first
        training.
        """
        # Prepare some training images + features.
        self.upload_images_for_training()
        run_scheduled_jobs_until_empty()
        queue_and_run_collect_spacer_jobs()

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

    def test_not_enough_train_data_since_last_classifier(self):
        """
        Try to train when there haven't been enough training images added
        since the last training.
        """
        # Prepare training images + features, and train one classifier.
        self.upload_images_for_training()
        run_scheduled_jobs_until_empty()
        queue_and_run_collect_spacer_jobs()
        run_scheduled_jobs_until_empty()
        queue_and_run_collect_spacer_jobs()

        # Attempt to train another classifier without adding more images.
        run_scheduled_jobs_until_empty()

        image_count = self.source.get_current_classifier().nbr_train_images
        threshold = math.ceil(image_count * settings.NEW_CLASSIFIER_TRAIN_TH)
        self.assert_job_result_message(
            'check_source',
            f"Source seems to be all caught up."
            f" Need {threshold} annotated images for next training,"
            f" and currently have {image_count}"
        )

    def test_one_unique_label(self):
        """
        Try to train when the training labelset ends up only having 1 unique
        label.
        """
        # Train data will have 2 unique labels, but val data will only have 1.
        # The intersection of the train data labelset and the val data labelset
        # is the training labelset. That labelset will be size 1 (only A),
        # thus fulfilling our test conditions.
        for _ in range(settings.TRAINING_MIN_IMAGES):
            img = self.upload_image(
                self.user, self.source, image_options=dict(
                    filename=f'train{self.image_count}.png'))
            self.add_annotations(
                self.user, img, {1: 'A', 2: 'B', 3: 'A', 4: 'A', 5: 'B'})
        for _ in range(1):
            img = self.upload_image(
                self.user, self.source, image_options=dict(
                    filename=f'val{self.image_count}.png'))
            self.add_annotations(
                self.user, img, {1: 'A', 2: 'A', 3: 'A', 4: 'A', 5: 'A'})
        # Extract features.
        run_scheduled_jobs_until_empty()
        queue_and_run_collect_spacer_jobs()

        # Try to train classifier.
        run_scheduled_jobs_until_empty()

        classifier = self.source.classifier_set.latest('pk')
        self.assertEqual(
            classifier.status, Classifier.LACKING_UNIQUE_LABELS,
            msg="Classifier status should be correct")

        self.assert_job_result_message(
            'train_classifier',
            f"Classifier {classifier.pk} [Source: {self.source.name}"
            f" [{self.source.pk}]] was declined training, because the"
            f" training labelset ended up only having one unique label."
            f" Training requires at least 2 unique labels.")

        self.assertFalse(
            self.source.need_new_robot()[0],
            msg="Source should not immediately be considered for retraining")

    def test_spacer_error(self):
        # Prepare training images + features.
        self.upload_images_for_training()
        run_scheduled_jobs_until_empty()
        queue_and_run_collect_spacer_jobs()

        # Submit training, with a spacer function mocked to
        # throw an error.
        def raise_error(*args):
            raise ValueError("A spacer error")
        with mock.patch('spacer.tasks.train_classifier', raise_error):
            run_scheduled_jobs_until_empty()

        # Collect training.
        queue_and_run_collect_spacer_jobs()

        self.assert_job_result_message(
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
        queue_and_run_collect_spacer_jobs()
        # Train classifier.
        run_scheduled_jobs_until_empty()

        # Delete classifier.
        classifier = self.source.classifier_set.latest('pk')
        classifier_id = classifier.pk
        classifier.delete()

        # Collect training.
        queue_and_run_collect_spacer_jobs()

        self.assert_job_result_message(
            'train_classifier',
            f"Classifier {classifier_id} doesn't exist anymore.")

    def test_classifier_rejected(self):
        """
        Run the train task, then collect the classifier and find that it's
        not enough of an improvement over the previous.
        """
        def mock_train_msg(
                self_, acc, pc_accs, ref_accs, runtime):
            self_.acc = 0.6
            self_.pc_accs = [0.5]
            self_.ref_accs = ref_accs
            self_.runtime = runtime

        # Train one classifier.
        self.upload_images_for_training()
        run_scheduled_jobs_until_empty()
        queue_and_run_collect_spacer_jobs()
        run_scheduled_jobs_until_empty()
        queue_and_run_collect_spacer_jobs()

        # Upload enough additional images for the next training to happen.
        old_image_count = self.source.get_current_classifier().nbr_train_images
        new_image_count = math.ceil(
            old_image_count*settings.NEW_CLASSIFIER_TRAIN_TH)
        added_image_count = new_image_count - old_image_count
        self.upload_images_for_training(
            train_image_count=added_image_count, val_image_count=0)
        run_scheduled_jobs_until_empty()
        queue_and_run_collect_spacer_jobs()
        run_scheduled_jobs_until_empty()

        with override_settings(NEW_CLASSIFIER_IMPROVEMENT_TH=1.4):
            # Collect classifier. Use mock to specify current and previous
            # classifiers' accuracy.
            with mock.patch(
                    'spacer.messages.TrainClassifierReturnMsg.__init__',
                    mock_train_msg):
                queue_and_run_collect_spacer_jobs()

        classifier = self.source.classifier_set.latest('pk')
        self.assertEqual(classifier.status, Classifier.REJECTED_ACCURACY)

        self.assert_job_result_message(
            'train_classifier',
            f"Not accepted as the source's new classifier."
            f" Highest accuracy among previous classifiers"
            f" on the latest dataset: {0.5:.2f},"
            f" threshold to accept new: {0.5*1.4:.2f},"
            f" accuracy from this training: {0.6:.2f}")

        self.assert_job_persist_value('train_classifier', True)
