import json
from pathlib import Path
from unittest import mock

from django.core.management.base import CommandError
from spacer.data_classes import ImageFeatures

from jobs.models import Job
from jobs.tasks import run_scheduled_jobs_until_empty
from jobs.utils import schedule_job
from lib.storage_backends import get_storage_manager
from lib.tests.utils import ManagementCommandTest
from ..models import Features
from .tasks.utils import TaskTestMixin


class MockOpenFactory:
    """
    Create a mock of the builtin function open().
    """
    def __init__(self, directory):
        self.directory = directory

    def __call__(self, filepath, *args, **kwargs):
        # Use the input filepath's filename, but use the directory
        # specified in __init__().
        filename = Path(filepath).name
        directory = Path(self.directory)
        filepath = directory / filename
        return open(filepath, *args, **kwargs)


class CheckSourceTest(ManagementCommandTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user = cls.create_user()
        cls.source_1 = cls.create_source(cls.user)
        cls.source_2 = cls.create_source(cls.user)
        cls.source_3 = cls.create_source(cls.user)
        cls.source_4 = cls.create_source(cls.user)

    def test_one_source(self):
        stdout_text, _ = self.call_command_and_get_output(
            'vision_backend', 'vb_check_source', args=[self.source_1.pk])
        self.assertIn(
            f"Source checks have been scheduled for the"
            f" 1 source(s) requested.",
            stdout_text)

        job_details = {
            (job.job_name, job.arg_identifier, job.status)
            for job in Job.objects.all()
        }
        self.assertSetEqual(
            job_details,
            {
                ('check_source', str(self.source_1.pk), Job.Status.PENDING),
            },
            "Should schedule the appropriate job",
        )

    def test_multiple_sources(self):
        stdout_text, _ = self.call_command_and_get_output(
            'vision_backend', 'vb_check_source',
            args=[self.source_1.pk, self.source_2.pk, self.source_3.pk])
        self.assertIn(
            f"Source checks have been scheduled for the"
            f" 3 source(s) requested.",
            stdout_text)

        job_details = {
            (job.job_name, job.arg_identifier, job.status)
            for job in Job.objects.all()
        }
        self.assertSetEqual(
            job_details,
            {
                ('check_source', str(self.source_1.pk), Job.Status.PENDING),
                ('check_source', str(self.source_2.pk), Job.Status.PENDING),
                ('check_source', str(self.source_3.pk), Job.Status.PENDING),
            },
            "Should schedule the appropriate jobs",
        )


class CheckAllSourcesTest(ManagementCommandTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)
        cls.source2 = cls.create_source(cls.user)
        cls.source3 = cls.create_source(cls.user)

    def test(self):
        schedule_job('check_source', self.source2.pk,
            source_id=self.source2.pk)

        # This should schedule sources 1 and 3
        stdout_text, _ = self.call_command_and_get_output(
            'vision_backend', 'vb_check_all_sources')
        self.assertEqual(
            stdout_text,
            f"Source checks have been scheduled for 2 source(s)."
            f" (The other sources already had checks scheduled.)")

        # If these lines don't get errors, then the expected
        # scheduled jobs exist
        Job.objects.get(
            job_name='check_source', arg_identifier=self.source.pk,
            status=Job.Status.PENDING)
        Job.objects.get(
            job_name='check_source', arg_identifier=self.source2.pk,
            status=Job.Status.PENDING)
        Job.objects.get(
            job_name='check_source', arg_identifier=self.source3.pk,
            status=Job.Status.PENDING)


class ResetFeaturesTest(ManagementCommandTest, TaskTestMixin):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user = cls.create_user()

        cls.source_1 = cls.create_source(cls.user)
        cls.image_1a = cls.upload_image(cls.user, cls.source_1)
        cls.image_1b = cls.upload_image(cls.user, cls.source_1)

        cls.source_2 = cls.create_source(cls.user)
        cls.image_2a = cls.upload_image(cls.user, cls.source_2)
        cls.image_2b = cls.upload_image(cls.user, cls.source_2)

        cls.source_3 = cls.create_source(cls.user)
        cls.image_3a = cls.upload_image(cls.user, cls.source_3)

        # Extract features
        run_scheduled_jobs_until_empty()
        cls.do_collect_spacer_jobs()
        # Let remaining check_source jobs run (they should have nothing to do)
        run_scheduled_jobs_until_empty()

    def assert_extracted(self, image):
        self.assertTrue(Features.objects.get(image=image).extracted)

    def assert_not_extracted(self, image):
        self.assertFalse(Features.objects.get(image=image).extracted)

    def test_source_ids(self):
        stdout_text, _ = self.call_command_and_get_output(
            'vision_backend', 'vb_reset_features',
            args=['source_ids', self.source_1.pk, self.source_2.pk],
        )

        self.assertIn(
            f"Initiating feature resets for source {self.source_1.pk}"
            f" \"{self.source_1.name}\" (2 image(s))...",
            stdout_text,
            "Should have expected output for source 1",
        )
        self.assertIn(
            f"Initiating feature resets for source {self.source_2.pk}"
            f" \"{self.source_2.name}\" (2 image(s))...",
            stdout_text,
            "Should have expected output for source 2",
        )

        # Applicable feature flags should be cleared
        self.assert_not_extracted(self.image_1a)
        self.assert_not_extracted(self.image_1b)
        self.assert_not_extracted(self.image_2a)
        self.assert_not_extracted(self.image_2b)
        self.assert_extracted(self.image_3a)

        pending_job_details = {
            (job.job_name, job.arg_identifier)
            for job in Job.objects.filter(status=Job.Status.PENDING)
        }
        self.assertSetEqual(
            pending_job_details,
            {
                ('check_source', str(self.source_1.pk)),
                ('check_source', str(self.source_2.pk)),
            },
            "Should schedule the appropriate jobs",
        )

    def test_image_ids(self):
        stdout_text, _ = self.call_command_and_get_output(
            'vision_backend', 'vb_reset_features',
            args=['image_ids', self.image_1a.pk, self.image_2b.pk],
        )

        self.assertIn(
            f"Initiating feature reset for image {self.image_1a.pk}...",
            stdout_text,
            "Should have expected output for image 1a",
        )
        self.assertIn(
            f"Initiating feature reset for image {self.image_2b.pk}...",
            stdout_text,
            "Should have expected output for image 2b",
        )

        # Applicable feature flags should be cleared
        self.assert_not_extracted(self.image_1a)
        self.assert_extracted(self.image_1b)
        self.assert_extracted(self.image_2a)
        self.assert_not_extracted(self.image_2b)
        self.assert_extracted(self.image_3a)

        pending_job_details = {
            (job.job_name, job.arg_identifier)
            for job in Job.objects.filter(status=Job.Status.PENDING)
        }
        self.assertSetEqual(
            pending_job_details,
            {
                ('check_source', str(self.source_1.pk)),
                ('check_source', str(self.source_2.pk)),
            },
            "Should schedule the appropriate jobs",
        )

    def test_invalid_mode(self):
        with self.assertRaises(CommandError) as context:
            self.call_command_and_get_output(
                'vision_backend', 'vb_reset_features',
                args=['some_mode', 1, 2],
            )
        self.assertEqual(
            "Error: argument mode: invalid choice: 'some_mode'"
            " (choose from 'source_ids', 'image_ids')",
            context.exception.args[0],
            "Should raise the appropriate error",
        )


class InspectExtractedFeaturesTest(ManagementCommandTest, TaskTestMixin):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user = cls.create_user()

        cls.source_1 = cls.create_source(cls.user)
        cls.image_1a = cls.upload_image(cls.user, cls.source_1)
        cls.image_1b = cls.upload_image(cls.user, cls.source_1)

        cls.source_2 = cls.create_source(cls.user)
        cls.image_2a = cls.upload_image(cls.user, cls.source_2)
        cls.image_2b = cls.upload_image(cls.user, cls.source_2)

        cls.source_3 = cls.create_source(cls.user)
        cls.image_3a = cls.upload_image(cls.user, cls.source_3)

    def call_command(self, *args):

        storage_manager = get_storage_manager()
        temp_dir = storage_manager.create_temp_dir()

        # Mock open() to write to a temp directory that we can
        # clean up more reliably.
        # Need to mock open() in two different files.
        with mock.patch(
            'vision_backend.management.commands'
            '.vb_inspect_extracted_features.open',
            MockOpenFactory(temp_dir)
        ):
            with mock.patch(
                'vision_backend.management.commands.utils.open',
                MockOpenFactory(temp_dir)
            ):
                stdout_text, _ = self.call_command_and_get_output(
                    'vision_backend', 'vb_inspect_extracted_features',
                    args=args,
                )

        with open(Path(temp_dir, 'inspect_features.log')) as f:
            features_log_content = f.read()

        try:
            with open(Path(temp_dir, 'feature_errors.json')) as f:
                errors_json = json.load(f)
        except FileNotFoundError:
            errors_json = None

        storage_manager.remove_temp_dir(temp_dir)

        return stdout_text, features_log_content, errors_json

    def test_no_features(self):
        stdout_text, features_log_content, errors_json = self.call_command(
            'image_ids', '--ids', self.image_1a.pk,
        )

        self.assertIsNone(errors_json)
        self.assertIn("No errors found", stdout_text)

    def test_features_ok(self):
        # Extract features normally.
        run_scheduled_jobs_until_empty()
        self.do_collect_spacer_jobs()

        stdout_text, features_log_content, errors_json = self.call_command(
            'image_ids', '--ids', self.image_1a.pk,
        )

        self.assertIsNone(errors_json)
        self.assertIn("No errors found", stdout_text)

    def test_features_missing_file(self):
        # Mark as extracted without actually generating features.
        self.image_1a.features.extracted = True
        self.image_1a.features.save()

        stdout_text, features_log_content, errors_json = self.call_command(
            'image_ids', '--ids', self.image_1a.pk,
        )

        errors = dict(errors_json[str(self.source_1.pk)])
        self.assertTrue(
            errors[self.image_1a.pk].startswith('FileNotFoundError')
        )

        self.assertIn(
            f"Errors per source:"
            f"\n{self.source_1.pk}: 1"
            f"\nErrors written to feature_errors.json.",
            stdout_text
        )

    def test_bad_feature_dim(self):
        # Extract features normally.
        run_scheduled_jobs_until_empty()
        self.do_collect_spacer_jobs()

        # Modify features to have a mismatching feature_dim attribute.
        feature_loc = self.image_1a.features.data_loc
        features = ImageFeatures.load(feature_loc)
        features.feature_dim += 1
        features.store(feature_loc)

        stdout_text, features_log_content, errors_json = self.call_command(
            'image_ids', '--ids', self.image_1a.pk,
        )

        errors = dict(errors_json[str(self.source_1.pk)])
        self.assertEqual(
            errors[self.image_1a.pk],
            "AssertionError()",
        )

        self.assertIn(
            f"Errors per source:"
            f"\n{self.source_1.pk}: 1"
            f"\nErrors written to feature_errors.json.",
            stdout_text
        )

    def test_rowcol_mismatch(self):
        # Extract features normally.
        run_scheduled_jobs_until_empty()
        self.do_collect_spacer_jobs()

        # Change a point without clearing features.
        point = self.image_1a.point_set.get(point_number=1)
        if point.row == 1:
            point.row = 2
        else:
            point.row = 1
        point.save()

        stdout_text, features_log_content, errors_json = self.call_command(
            'image_ids', '--ids', self.image_1a.pk,
        )

        errors = dict(errors_json[str(self.source_1.pk)])
        self.assertEqual(
            errors[self.image_1a.pk],
            "Feature rowcols don't match the DB rowcols.",
        )

        self.assertIn(
            f"Errors per source:"
            f"\n{self.source_1.pk}: 1"
            f"\nErrors written to feature_errors.json.",
            stdout_text
        )

    def test_legacy_ok(self):
        # Extract features normally.
        run_scheduled_jobs_until_empty()
        self.do_collect_spacer_jobs()

        # Change features to the legacy format.
        feature_loc = self.image_1a.features.data_loc
        features = ImageFeatures.load(feature_loc)
        features_legacy = ImageFeatures.deserialize(
            [pf.data for pf in features.point_features]
        )
        features_legacy.store(feature_loc)

        stdout_text, features_log_content, errors_json = self.call_command(
            'image_ids', '--ids', self.image_1a.pk,
        )

        self.assertIsNone(errors_json)
        self.assertIn("No errors found", stdout_text)

    def test_legacy_count_mismatch(self):
        # Extract features normally.
        run_scheduled_jobs_until_empty()
        self.do_collect_spacer_jobs()

        # Change features to the legacy format and change the length.
        feature_loc = self.image_1a.features.data_loc
        features = ImageFeatures.load(feature_loc)
        data = [pf.data for pf in features.point_features]
        # Append a duplicate of the first point feature.
        data.append(data[0])
        features_legacy = ImageFeatures.deserialize(data)
        features_legacy.store(feature_loc)

        stdout_text, features_log_content, errors_json = self.call_command(
            'image_ids', '--ids', self.image_1a.pk,
        )

        errors = dict(errors_json[str(self.source_1.pk)])
        self.assertEqual(
            errors[self.image_1a.pk],
            "Legacy feature rowcols don't match the number of DB rowcols.",
        )

        self.assertIn(
            f"Errors per source:"
            f"\n{self.source_1.pk}: 1"
            f"\nErrors written to feature_errors.json.",
            stdout_text
        )

    def test_image_ids(self):
        stdout_text, features_log_content, errors_json = self.call_command(
            'image_ids', '--ids', self.image_1a.pk, self.image_2b.pk,
        )

        self.assertIn(
            f"Inspecting image {self.image_1a.pk}", features_log_content)
        self.assertNotIn(
            f"Inspecting image {self.image_1b.pk}", features_log_content)
        self.assertNotIn(
            f"Inspecting image {self.image_2a.pk}", features_log_content)
        self.assertIn(
            f"Inspecting image {self.image_2b.pk}", features_log_content)
        self.assertNotIn(
            f"Inspecting image {self.image_3a.pk}", features_log_content)

    def test_source_ids(self):
        stdout_text, features_log_content, errors_json = self.call_command(
            'source_ids', '--ids', self.source_1.pk, self.source_2.pk,
        )

        self.assertIn(
            f"Inspecting \"{self.source_1.name}\", ID {self.source_1.pk}"
            f" [1/2] with 2 images",
            features_log_content)
        self.assertIn(
            f"Inspecting \"{self.source_2.name}\", ID {self.source_2.pk}"
            f" [2/2] with 2 images",
            features_log_content)
        self.assertNotIn(
            f"Inspecting \"{self.source_3.name}\", ID {self.source_3.pk}",
            features_log_content)

    def test_all_sources(self):
        stdout_text, features_log_content, errors_json = self.call_command(
            'all_sources',
        )

        self.assertIn(
            f"Inspecting \"{self.source_1.name}\", ID {self.source_1.pk}"
            f" [1/3] with 2 images",
            features_log_content)
        self.assertIn(
            f"Inspecting \"{self.source_2.name}\", ID {self.source_2.pk}"
            f" [2/3] with 2 images",
            features_log_content)
        self.assertIn(
            f"Inspecting \"{self.source_3.name}\", ID {self.source_3.pk}"
            f" [3/3] with 1 images",
            features_log_content)

    def test_skip_to(self):
        stdout_text, features_log_content, errors_json = self.call_command(
            'all_sources', '--skip_to', self.source_2.pk,
        )

        self.assertNotIn(
            f"Inspecting \"{self.source_1.name}\", ID {self.source_1.pk}",
            features_log_content)
        self.assertIn(
            f"Inspecting \"{self.source_2.name}\", ID {self.source_2.pk}"
            f" [1/2] with 2 images",
            features_log_content)
        self.assertIn(
            f"Inspecting \"{self.source_3.name}\", ID {self.source_3.pk}"
            f" [2/2] with 1 images",
            features_log_content)

    def test_multiple_errors(self):
        # Get error situations on all images.
        # We mark each as extracted without actually generating features.
        for image in [
            self.image_1a, self.image_1b, self.image_2a, self.image_2b,
            self.image_3a,
        ]:
            image.features.extracted = True
            image.features.save()

        stdout_text, features_log_content, errors_json = self.call_command(
            'all_sources',
        )

        source_1_errors = errors_json[str(self.source_1.pk)]
        self.assertEqual(len(source_1_errors), 2)
        source_2_errors = errors_json[str(self.source_2.pk)]
        self.assertEqual(len(source_2_errors), 2)
        source_3_errors = errors_json[str(self.source_3.pk)]
        self.assertEqual(len(source_3_errors), 1)

        self.assertIn(
            f"Errors per source:"
            f"\n{self.source_1.pk}: 2"
            f"\n{self.source_2.pk}: 2"
            f"\n{self.source_3.pk}: 1"
            f"\nErrors written to feature_errors.json.",
            stdout_text
        )

    def test_do_correct(self):
        # Extract features
        run_scheduled_jobs_until_empty()
        self.do_collect_spacer_jobs()
        # Let remaining check_source jobs run (they should have nothing to do)
        run_scheduled_jobs_until_empty()

        # Induce mismatching feature_dim attributes on 2 images.
        for image in [self.image_1a, self.image_2b]:
            feature_loc = image.features.data_loc
            features = ImageFeatures.load(feature_loc)
            features.feature_dim += 1
            features.store(feature_loc)

        # First, no corrections
        self.call_command(
            'all_sources',
        )

        # Should have scheduled no jobs
        self.assertFalse(Job.objects.filter(status=Job.Status.PENDING).exists())

        # Then, with corrections
        self.call_command(
            'all_sources', '--do_correct',
        )

        # Now there should be jobs scheduled
        self.assertTrue(Job.objects.filter(status=Job.Status.PENDING).exists())

        pending_job_details = {
            (job.job_name, job.arg_identifier)
            for job in Job.objects.filter(status=Job.Status.PENDING)
        }
        self.assertSetEqual(
            pending_job_details,
            {
                ('check_source', str(self.source_1.pk)),
                ('check_source', str(self.source_2.pk)),
            },
            "Should schedule the appropriate jobs",
        )


class SubmitTrainTest(ManagementCommandTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user = cls.create_user()
        cls.source_1 = cls.create_source(cls.user)
        cls.source_2 = cls.create_source(cls.user)

    def test(self):
        stdout_text, _ = self.call_command_and_get_output(
            'vision_backend', 'vb_submit_train', args=[self.source_1.pk])
        self.assertIn(
            f"Training has been scheduled for this source.",
            stdout_text)

        job_details = {
            (job.job_name, job.arg_identifier, job.source_id, job.status)
            for job in Job.objects.all()
        }
        self.assertSetEqual(
            job_details,
            {
                ('train_classifier',
                 str(self.source_1.pk),
                 self.source_1.pk,
                 Job.Status.PENDING),
            },
            "Should schedule the appropriate job",
        )
