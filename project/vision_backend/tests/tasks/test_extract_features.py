from unittest import mock

from django.conf import settings
from django.core.files.storage import get_storage_class
from django.test import override_settings
from spacer.data_classes import ImageFeatures
from spacer.exceptions import RowColumnMismatchError

from errorlogs.tests.utils import ErrorReportTestMixin
from jobs.tasks import run_scheduled_jobs, run_scheduled_jobs_until_empty
from jobs.tests.utils import JobUtilsMixin, queue_and_run_job, run_pending_job
from lib.tests.utils import EmailAssertionsMixin
from .utils import BaseTaskTest, queue_and_run_collect_spacer_jobs


class ExtractFeaturesTest(BaseTaskTest, JobUtilsMixin):

    def test_source_check(self):
        self.upload_image(self.user, self.source)
        self.upload_image(self.user, self.source)

        # Should have queued a source check after uploading
        run_pending_job('check_source', self.source.pk)
        self.assert_job_result_message(
            'check_source',
            "Queued 2 feature extraction(s)")

        self.upload_image(self.user, self.source)

        run_pending_job('check_source', self.source.pk)
        # Should not re-queue the other extractions
        self.assert_job_result_message(
            'check_source',
            "Queued 1 feature extraction(s)")

        queue_and_run_job(
            'check_source', self.source.pk,
            source_id=self.source.pk)
        self.assert_job_result_message(
            'check_source',
            "Waiting for feature extraction(s) to finish")

    @override_settings(JOB_MAX_MINUTES=-1)
    def test_source_check_time_out(self):
        for _ in range(12):
            self.upload_image(self.user, self.source)

        run_pending_job('check_source', self.source.pk)
        self.assert_job_result_message(
            'check_source',
            "Queued 10 feature extraction(s) (timed out)")

        queue_and_run_job(
            'check_source', self.source.pk,
            source_id=self.source.pk)
        self.assert_job_result_message(
            'check_source',
            "Queued 2 feature extraction(s)")

    def test_source_check_unprocessable_image(self):
        image1 = self.upload_image(self.user, self.source)
        image1.unprocessable_reason = "Exceeds point limit"
        image1.save()

        run_pending_job('check_source', self.source.pk)
        self.assert_job_result_message(
            'check_source',
            "Can't train first classifier: Not enough annotated images for"
            " initial training",
            assert_msg="Shouldn't queue extraction for the"
                       " unprocessable image",
        )

        self.upload_image(self.user, self.source)
        run_pending_job('check_source', self.source.pk)
        self.assert_job_result_message(
            'check_source',
            "Queued 1 feature extraction(s)",
            assert_msg="Should still queue extraction for other images",
        )

    def test_success(self):
        # After an image upload, features are ready to be submitted.
        img = self.upload_image(self.user, self.source)

        # Extract features.
        run_scheduled_jobs_until_empty()

        self.assertExistsInStorage(
            settings.FEATURE_VECTOR_FILE_PATTERN.format(
                full_image_path=img.original_file.name))

        # With LocalQueue, the result should be
        # available for collection immediately.
        queue_and_run_collect_spacer_jobs()

        self.assertTrue(
            img.features.extracted, msg="Extracted boolean should be set")
        self.assertTrue(
            img.features.has_rowcols, msg="has_rowcols should be True")

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

    @override_settings(SPACER={'MAX_IMAGE_PIXELS': 100})
    def test_resolution_too_large(self):
        # Upload image.
        img1 = self.upload_image(
            self.user, self.source, image_options=dict(width=10, height=10))
        # Upload too-large image.
        img2 = self.upload_image(
            self.user, self.source, image_options=dict(width=10, height=11))
        # Extract features + process result.
        run_scheduled_jobs_until_empty()
        queue_and_run_collect_spacer_jobs()

        # Let the next source-check get past the training and classification
        # checks.
        robot = self.create_robot(self.source)
        self.add_robot_annotations(robot, img1)

        # Check source again.
        run_scheduled_jobs_until_empty()

        img2.features.refresh_from_db()
        self.assertFalse(img2.features.extracted)
        self.assert_job_result_message(
            'check_source',
            "At least one image has too large of a resolution to extract"
            f" features (example: image ID {img2.pk})."
            f" Otherwise, the source seems to be all caught up."
            f" Not enough annotated images for initial training")


class AbortCasesTest(
    BaseTaskTest, EmailAssertionsMixin, ErrorReportTestMixin, JobUtilsMixin,
):
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
        self.upload_images_for_training()
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

    def do_test_spacer_error(self, raise_error):
        # Upload image.
        self.upload_image(self.user, self.source)
        # Check source.
        run_scheduled_jobs()

        # Submit feature extraction, with a spacer function mocked to
        # throw an error.
        with mock.patch('spacer.tasks.extract_features', raise_error):
            run_scheduled_jobs()

        # Collect feature extraction.
        queue_and_run_collect_spacer_jobs()

    def test_spacer_priority_error(self):
        """Spacer error that's not in the non-priority categories."""

        def raise_error(*args):
            raise ValueError("A spacer error")
        self.do_test_spacer_error(raise_error)

        self.assert_job_result_message(
            'extract_features',
            "ValueError: A spacer error")

        self.assert_error_log_saved(
            "ValueError",
            "A spacer error",
        )
        self.assert_latest_email(
            "Spacer job failed: extract_features",
            ["ValueError: A spacer error"],
        )

    def test_spacer_assertion_error_no_message(self):
        """
        Another priority error type, and a special case for parsing
        the error info (due to having no message).
        """
        def raise_error(*args):
            assert False
        self.do_test_spacer_error(raise_error)

        self.assert_job_result_message(
            'extract_features',
            "AssertionError")

        self.assert_error_log_saved(
            "AssertionError",
            "",
        )
        self.assert_latest_email(
            "Spacer job failed: extract_features",
            ["AssertionError"],
        )

    def test_row_column_mismatch_error(self):
        """These errors aren't considered priority."""
        def raise_error(*args):
            raise RowColumnMismatchError("Row-column positions don't match")
        self.do_test_spacer_error(raise_error)

        self.assert_job_result_message(
            'extract_features',
            "spacer.exceptions.RowColumnMismatchError:"
            " Row-column positions don't match")

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
