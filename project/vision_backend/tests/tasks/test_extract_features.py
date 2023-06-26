from unittest import mock

from django.conf import settings
from django.core.files.storage import get_storage_class
import spacer.config as spacer_config
from spacer.data_classes import ImageFeatures
from spacer.exceptions import SpacerInputError

from errorlogs.tests.utils import ErrorReportTestMixin
from jobs.tasks import run_scheduled_jobs, run_scheduled_jobs_until_empty
from jobs.tests.utils import JobUtilsMixin
from .utils import BaseTaskTest, queue_and_run_collect_spacer_jobs


class ExtractFeaturesTest(BaseTaskTest, JobUtilsMixin):

    def test_success(self):
        # After an image upload, features are ready to be submitted.
        img = self.upload_image(self.user, self.source)

        # Extract features.
        run_scheduled_jobs_until_empty()

        self.assert_job_result_message(
            'check_source',
            "Tried to queue feature extraction(s)")

        self.assertExistsInStorage(
            settings.FEATURE_VECTOR_FILE_PATTERN.format(
                full_image_path=img.original_file.name))

        # With LocalQueue, the result should be
        # available for collection immediately.
        queue_and_run_collect_spacer_jobs()

        # Features should be successfully extracted.
        self.assertTrue(img.features.extracted)

    def test_multiple(self):
        img1 = self.upload_image(self.user, self.source)
        img2 = self.upload_image(self.user, self.source)
        img3 = self.upload_image(self.user, self.source)

        # Extract features + collect results.
        run_scheduled_jobs_until_empty()
        queue_and_run_collect_spacer_jobs()

        self.assertTrue(img1.features.extracted)
        self.assertTrue(img2.features.extracted)
        self.assertTrue(img3.features.extracted)

    def test_with_dupe_points(self):
        """
        The image to have features extracted has two points with the same
        row/column.
        """

        # Upload.
        img = self.upload_image_with_dupe_points('1.png')
        # Extract features + process result.
        run_scheduled_jobs_until_empty()
        queue_and_run_collect_spacer_jobs()

        self.assertTrue(img.features.extracted, "Features should be extracted")

        # Ensure the features are of the uploaded points, without dupes.
        storage = get_storage_class()()
        feature_loc = storage.spacer_data_loc(
            settings.FEATURE_VECTOR_FILE_PATTERN.format(
                full_image_path=img.original_file.name))
        features = ImageFeatures.load(feature_loc)
        rowcols = [(f.row, f.col) for f in features.point_features]
        self.assertListEqual(
            self.rowcols_with_dupes_included, sorted(rowcols),
            "Feature rowcols should match the actual points including dupes")


class AbortCasesTest(BaseTaskTest, ErrorReportTestMixin, JobUtilsMixin):
    """
    Test cases where the task or collection would abort before reaching the
    end.
    """
    def test_training_in_progress(self):
        """
        Try to extract features while training for the same source is in
        progress.
        """
        # Provide enough data for training. Extract features.
        self.upload_images_for_training(
            train_image_count=spacer_config.MIN_TRAINIMAGES,
            val_image_count=1)
        run_scheduled_jobs_until_empty()
        queue_and_run_collect_spacer_jobs()

        # Train a classifier.
        run_scheduled_jobs_until_empty()

        # Upload another image.
        self.upload_image(self.user, self.source)

        # Try to submit feature extraction.
        run_scheduled_jobs_until_empty()

        self.assert_job_result_message(
            'check_source',
            f"Feature extraction(s) ready, but not"
            f" submitted due to training in progress")

    def test_nonexistent_image(self):
        """Try to extract features for a nonexistent image ID."""
        # To get a nonexistent image ID, upload an image, get its ID, then
        # delete the image.
        img = self.upload_image(self.user, self.source)

        # Check source, but don't run feature extraction yet.
        run_scheduled_jobs()

        image_id = img.pk
        img.delete()

        # Try to extract features.
        run_scheduled_jobs()

        self.assert_job_result_message(
            'extract_features',
            f"Image {image_id} does not exist.")

    def test_image_deleted_during_extract(self):
        # Upload image.
        img = self.upload_image(self.user, self.source)
        # Submit feature extraction.
        run_scheduled_jobs_until_empty()

        # Delete image.
        image_id = img.pk
        img.delete()

        # Collect feature extraction.
        queue_and_run_collect_spacer_jobs()

        self.assert_job_result_message(
            'extract_features',
            f"Image {image_id} doesn't exist anymore.")

    def test_spacer_error(self):
        # Upload image.
        self.upload_image(self.user, self.source)
        # Check source.
        run_scheduled_jobs()

        # Submit feature extraction, with a spacer function mocked to
        # throw an error.
        def raise_error(*args):
            raise ValueError("A spacer error")
        with mock.patch('spacer.tasks.extract_features', raise_error):
            run_scheduled_jobs()

        # Collect feature extraction.
        queue_and_run_collect_spacer_jobs()

        self.assert_job_result_message(
            'extract_features',
            "ValueError: A spacer error")

        self.assert_error_log_saved(
            "ValueError",
            "A spacer error",
        )
        self.assert_error_email(
            "Spacer job failed: extract_features",
            ["ValueError: A spacer error"],
        )

    def test_spacer_input_error(self):
        # Upload image.
        self.upload_image(self.user, self.source)
        # Check source.
        run_scheduled_jobs()

        # Extract features, with a spacer function mocked to
        # throw a SpacerInputError, which is less critical than other
        # spacer errors.
        def raise_error(*args):
            raise SpacerInputError("A spacer input error")
        with mock.patch('spacer.tasks.extract_features', raise_error):
            run_scheduled_jobs()
        queue_and_run_collect_spacer_jobs()

        self.assert_job_result_message(
            'extract_features',
            "spacer.exceptions.SpacerInputError: A spacer input error")

        self.assert_no_error_log_saved()
        self.assert_no_email()

    def test_rowcols_changed_during_extract(self):
        # Upload image.
        img = self.upload_image(self.user, self.source)
        # Ensure we know one of the point's row and column.
        point = img.point_set.all()[0]
        point.row = 1
        point.column = 1
        point.save()
        # Submit feature extraction.
        run_scheduled_jobs_until_empty()

        # Change the point's row and column.
        point.row = 2
        point.column = 3
        point.save()

        # Collect feature extraction.
        queue_and_run_collect_spacer_jobs()

        self.assert_job_result_message(
            'extract_features',
            f"Row-col data for {img} has changed"
            f" since this task was submitted.")
