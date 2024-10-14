from unittest import mock

from django.conf import settings
from django.test import override_settings
from spacer.exceptions import RowColumnMismatchError

from errorlogs.tests.utils import ErrorReportTestMixin
from jobs.tasks import run_scheduled_jobs, run_scheduled_jobs_until_empty
from jobs.tests.utils import do_job
from lib.tests.utils import EmailAssertionsMixin
from ...common import Extractors
from .utils import (
    BaseTaskTest, do_collect_spacer_jobs, source_check_is_scheduled)


class ExtractFeaturesTest(BaseTaskTest):

    def test_source_check(self):
        self.upload_image(self.user, self.source)
        self.upload_image(self.user, self.source)

        self.assertTrue(
            source_check_is_scheduled(self.source.pk),
            "Should have scheduled a source check after uploading")
        self.source_check_and_assert(
            "Scheduled 2 feature extraction(s)", expected_hidden=False)

        self.upload_image(self.user, self.source)

        self.assertTrue(
            source_check_is_scheduled(self.source.pk),
            "Should have scheduled a source check after uploading")
        self.source_check_and_assert(
            "Scheduled 1 feature extraction(s)", expected_hidden=False,
            assert_msg="Should not redo the other extractions")

        self.source_check_and_assert(
            "Waiting for feature extraction(s) to finish",
            expected_hidden=True)

    @override_settings(JOB_MAX_MINUTES=-1)
    def test_source_check_time_out(self):
        for _ in range(12):
            self.upload_image(self.user, self.source)

        self.source_check_and_assert(
            "Scheduled 10 feature extraction(s) (timed out)")

        self.source_check_and_assert(
            "Scheduled 2 feature extraction(s)")

    def test_source_check_unprocessable_image(self):
        image1 = self.upload_image(self.user, self.source)
        image1.unprocessable_reason = "Exceeds point limit"
        image1.save()

        self.source_check_and_assert(
            "Can't train first classifier: Not enough annotated images for"
            " initial training",
            expected_hidden=True,
            assert_msg="Shouldn't schedule extraction for the"
                       " unprocessable image",
        )

        self.upload_image(self.user, self.source)
        self.source_check_and_assert(
            "Scheduled 1 feature extraction(s)",
            expected_hidden=False,
            assert_msg="Should still schedule extraction for other images",
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
        do_collect_spacer_jobs()

        self.assertTrue(
            img.features.extracted, msg="Extracted boolean should be set")
        self.assertEqual(
            img.features.extractor, Extractors.DUMMY.value,
            msg="Extractor field should be set")
        self.assertTrue(
            img.features.has_rowcols, msg="has_rowcols should be True")

    def test_multiple(self):
        img1 = self.upload_image(self.user, self.source)
        img2 = self.upload_image(self.user, self.source)
        img3 = self.upload_image(self.user, self.source)

        # Extract features + collect results.
        run_scheduled_jobs_until_empty()
        do_collect_spacer_jobs()

        self.assertTrue(img1.features.extracted)
        self.assertTrue(img2.features.extracted)
        self.assertTrue(img3.features.extracted)

    def test_source_check_after_finishing(self):
        img1 = self.upload_image(self.user, self.source)
        img2 = self.upload_image(self.user, self.source)
        img3 = self.upload_image(self.user, self.source)

        do_job('check_source', self.source.pk)
        do_job('extract_features', img1.pk)
        do_collect_spacer_jobs()
        self.assertTrue(img1.features.extracted)
        self.assertFalse(
            source_check_is_scheduled(self.source.pk),
            msg="Source check shouldn't be scheduled since there are"
                " still incomplete extract jobs")

        do_job('extract_features', img2.pk)
        do_collect_spacer_jobs()
        self.assertTrue(img2.features.extracted)
        self.assertFalse(
            source_check_is_scheduled(self.source.pk),
            msg="Source check shouldn't be scheduled since there are"
                " still incomplete extract jobs")

        do_job('extract_features', img3.pk)
        do_collect_spacer_jobs()
        self.assertTrue(img3.features.extracted)
        self.assertTrue(
            source_check_is_scheduled(self.source.pk),
            msg="Source check should be scheduled since this is the"
                " last extract job")

    def test_with_dupe_points(self):
        """
        The image to have features extracted has two points with the same
        row/column.
        """

        # Upload.
        img = self.upload_image_with_dupe_points('1.png')
        # Extract features + process result.
        run_scheduled_jobs_until_empty()
        do_collect_spacer_jobs()

        self.assertTrue(img.features.extracted, "Features should be extracted")

        # Ensure the features are of the uploaded points, without dupes.
        features = img.features.load()
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
        do_collect_spacer_jobs()

        # Let the next source-check get past the training and classification
        # checks.
        robot = self.create_robot(self.source)
        self.add_robot_annotations(robot, img1)

        # Check source again.
        run_scheduled_jobs_until_empty()

        img2.features.refresh_from_db()
        self.assertFalse(img2.features.extracted)
        self.source_check_and_assert(
            "At least one image has too large of a resolution to extract"
            f" features (example: image ID {img2.pk})."
            f" Otherwise, the source seems to be all caught up."
            f" Not enough annotated images for initial training",
            expected_hidden=True,
        )


class AbortCasesTest(
    BaseTaskTest, EmailAssertionsMixin, ErrorReportTestMixin,
):
    """
    Test cases where the task or collection would abort before reaching the
    end.
    """
    def test_classification_not_configured_at_source_check(self):
        self.source.trains_own_classifiers = False
        self.source.deployed_classifier = None
        self.source.save()

        self.upload_image(self.user, self.source)

        # Try to submit feature extraction.
        run_scheduled_jobs_until_empty()

        self.source_check_and_assert(
            "Machine classification isn't configured for this source",
            expected_hidden=True,
        )

    def test_training_in_progress(self):
        """
        Try to extract features while training for the same source is in
        progress.
        """
        # Provide enough data for training. Extract features.
        self.upload_images_for_training()
        run_scheduled_jobs_until_empty()
        do_collect_spacer_jobs()

        # Train a classifier.
        run_scheduled_jobs_until_empty()

        # Upload another image.
        self.upload_image(self.user, self.source)

        # Try to submit feature extraction.
        run_scheduled_jobs_until_empty()

        self.source_check_and_assert(
            f"Feature extraction(s) ready, but not"
            f" submitted due to training in progress",
            expected_hidden=True,
        )

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

    def test_classification_not_configured_at_extract(self):
        image = self.upload_image(self.user, self.source)

        self.source.trains_own_classifiers = False
        self.source.deployed_classifier = None
        self.source.save()

        # Try to extract features.
        do_job('extract_features', image.pk, source_id=self.source.pk)

        self.assert_job_result_message(
            'extract_features',
            "No feature extractor configured for this source.")

    def test_image_deleted_during_extract(self):
        # Upload image.
        img = self.upload_image(self.user, self.source)
        # Submit feature extraction.
        run_scheduled_jobs_until_empty()

        # Delete image.
        image_id = img.pk
        img.delete()

        # Collect feature extraction.
        do_collect_spacer_jobs()

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
        do_collect_spacer_jobs()

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

    @override_settings(EMAIL_SIZE_SOFT_LIMIT=10000)
    def test_spacer_priority_error_within_size_limit(self):
        """
        Priority error with a job result that's not so long as to require
        truncation.
        """
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
            body_not_contains=["...(truncated)"],
        )

    @override_settings(EMAIL_SIZE_SOFT_LIMIT=50)
    def test_spacer_priority_error_exceeding_size_limit(self):
        """
        Priority error with a job result that's long enough to require
        truncation.
        """
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
            ["...(truncated)"],
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
        do_collect_spacer_jobs()

        self.assert_job_result_message(
            'extract_features',
            f"Row-col data for {img} has changed"
            f" since this task was submitted.")

    def test_extractor_changed_during_extract(self):
        # Upload image.
        self.upload_image(self.user, self.source)
        # Submit feature extraction.
        run_scheduled_jobs_until_empty()

        # Collect feature extraction.
        # The task extractor should be dummy (due to FORCE_DUMMY_EXTRACTOR
        # being True outside of the below context manager) while the
        # source extractor is EfficientNet.
        with override_settings(FORCE_DUMMY_EXTRACTOR=False):
            do_collect_spacer_jobs()

        self.assert_job_result_message(
            'extract_features',
            f"Feature extractor selection has changed since this task"
            f" was submitted.")
