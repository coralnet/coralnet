from unittest import mock

from django.test.utils import override_settings
from django.urls import reverse

from annotations.models import Annotation
from images.models import Image
from jobs.models import Job
from jobs.tasks import run_scheduled_jobs_until_empty
from jobs.utils import queue_job
from lib.tests.utils import ClientTest
from ...models import Score, Classifier
from ...tasks import check_all_sources
from .utils import BaseTaskTest, queue_and_run_collect_spacer_jobs


class ResetTaskTest(BaseTaskTest):

    def test_reset_classifiers_for_source(self):

        # Classify image and verify that it worked

        self.upload_data_and_train_classifier()
        img = self.upload_image_and_machine_classify()

        classifier = self.source.get_current_classifier()
        self.assertIsNotNone(classifier, "Should have a classifier")
        classifier_id = classifier.pk

        self.assertTrue(img.features.extracted, "img should have features")
        self.assertTrue(img.annoinfo.classified, "img should be classified")
        self.assertGreater(
            Score.objects.filter(image=img).count(), 0,
            "img should have scores")
        self.assertGreater(
            Annotation.objects.filter(image=img).count(), 0,
            "img should have annotations")

        # Reset classifiers
        job = queue_job(
            'reset_classifiers_for_source', self.source.pk,
            source_id=self.source.pk)
        run_scheduled_jobs_until_empty()

        job.refresh_from_db()
        self.assertEqual(
            job.status, Job.Status.SUCCESS, "Job should be marked as succeeded")
        self.assertTrue(
            job.persist, "Job should be marked as persistent")

        # Verify that classifier-related objects were cleared, but not features

        with self.assertRaises(
            Classifier.DoesNotExist, msg="Classifier should be deleted"
        ):
            Classifier.objects.get(pk=classifier_id)

        img.features.refresh_from_db()
        img.annoinfo.refresh_from_db()
        self.assertTrue(img.features.extracted, "img SHOULD have features")
        self.assertFalse(img.annoinfo.classified, "img shouldn't be classified")
        self.assertEqual(
            Score.objects.filter(image=img).count(), 0,
            "img shouldn't have scores")
        self.assertEqual(
            Annotation.objects.filter(image=img).count(), 0,
            "img shouldn't have annotations")

        # Train
        run_scheduled_jobs_until_empty()
        queue_and_run_collect_spacer_jobs()
        # Classify
        run_scheduled_jobs_until_empty()

        img.annoinfo.refresh_from_db()
        self.assertTrue(img.annoinfo.classified, "img should be classified")
        self.assertGreater(
            Score.objects.filter(image=img).count(), 0,
            "img should have scores")
        self.assertGreater(
            Annotation.objects.filter(image=img).count(), 0,
            "img should have annotations")

        # Ensure confirmed annotations weren't deleted
        for image in self.source.image_set.exclude(pk=img.pk):
            self.assertTrue(
                image.annotation_set.confirmed().exists(),
                "Confirmed annotations should still exist")
            self.assertTrue(
                image.annoinfo.confirmed,
                "Confirmed image should still be confirmed")

    def test_reset_backend_for_source(self):

        # Classify image and verify that it worked

        self.upload_data_and_train_classifier()
        img = self.upload_image_and_machine_classify()

        classifier = self.source.get_current_classifier()
        self.assertIsNotNone(classifier, "Should have a classifier")
        classifier_id = classifier.pk

        self.assertTrue(img.features.extracted, "img should have features")
        self.assertTrue(img.annoinfo.classified, "img should be classified")
        self.assertGreater(
            Score.objects.filter(image=img).count(), 0,
            "img should have scores")
        self.assertGreater(
            Annotation.objects.filter(image=img).count(), 0,
            "img should have annotations")

        # Reset backend
        job = queue_job(
            'reset_backend_for_source', self.source.pk,
            source_id=self.source.pk)
        run_scheduled_jobs_until_empty()

        job.refresh_from_db()
        self.assertEqual(
            job.status, Job.Status.SUCCESS, "Job should be marked as succeeded")
        self.assertTrue(
            job.persist, "Job should be marked as persistent")

        # Verify that backend objects were cleared

        with self.assertRaises(
            Classifier.DoesNotExist, msg="Classifier should be deleted"
        ):
            Classifier.objects.get(pk=classifier_id)

        img.features.refresh_from_db()
        img.annoinfo.refresh_from_db()
        self.assertFalse(img.features.extracted, "img shouldn't have features")
        self.assertFalse(img.annoinfo.classified, "img shouldn't be classified")
        self.assertEqual(
            Score.objects.filter(image=img).count(), 0,
            "img shouldn't have scores")
        self.assertEqual(
            Annotation.objects.filter(image=img).count(), 0,
            "img shouldn't have annotations")

        # Extract features
        run_scheduled_jobs_until_empty()
        queue_and_run_collect_spacer_jobs()
        # Train
        run_scheduled_jobs_until_empty()
        queue_and_run_collect_spacer_jobs()
        # Classify
        run_scheduled_jobs_until_empty()

        img.features.refresh_from_db()
        img.annoinfo.refresh_from_db()
        self.assertTrue(img.features.extracted, "img should have features")
        self.assertTrue(img.annoinfo.classified, "img should be classified")
        self.assertGreater(
            Score.objects.filter(image=img).count(), 0,
            "img should have scores")
        self.assertGreater(
            Annotation.objects.filter(image=img).count(), 0,
            "img should have annotations")

        # Ensure confirmed annotations weren't deleted
        for image in self.source.image_set.exclude(pk=img.pk):
            self.assertTrue(
                image.annotation_set.confirmed().exists(),
                "Confirmed annotations should still exist")
            self.assertTrue(
                image.annoinfo.confirmed,
                "Confirmed image should still be confirmed")

    def test_point_change_cleanup(self):
        """
        If we generate new points, features must be reset.
        """
        image = self.upload_image(self.user, self.source)
        image.features.extracted = True
        image.features.save()
        robot = self.create_robot(self.source)
        self.add_robot_annotations(robot, image)

        image.features.refresh_from_db()
        image.annoinfo.refresh_from_db()
        self.assertTrue(image.features.extracted, "Should have features")
        self.assertTrue(image.annoinfo.classified, "Should be classified")

        self.client.force_login(self.user)
        url = reverse('image_regenerate_points', args=[image.id])
        self.client.post(url)

        image.features.refresh_from_db()
        image.annoinfo.refresh_from_db()
        self.assertFalse(image.features.extracted, "Should not have features")
        self.assertFalse(image.annoinfo.classified, "Should not be classified")


def call_collect_spacer_jobs():
    queue_job('collect_spacer_jobs')

    class Queue:
        status_counts = dict()
        def collect_jobs(self):
            return []
    return Queue


@override_settings(ENABLE_PERIODIC_JOBS=False)
class CollectSpacerJobsTest(BaseTaskTest):

    @staticmethod
    def run_and_get_result():
        # Note that this may or may not queue a new job instance; perhaps
        # the periodic job was already queued at the end of the previous
        # job's run.
        queue_and_run_collect_spacer_jobs()
        job = Job.objects.filter(
            job_name='collect_spacer_jobs',
            status=Job.Status.SUCCESS).latest('pk')
        return job.result_message

    def test_success(self):
        # Run 2 extract-features jobs.
        self.upload_image(self.user, self.source)
        self.upload_image(self.user, self.source)
        run_scheduled_jobs_until_empty()

        # Collect jobs.
        # The effects of the actual spacer-job collections (e.g. features
        # marked as extracted) don't need to be tested here. That belongs in
        # e.g. feature-extraction tests.
        self.assertEqual(
            self.run_and_get_result(), "Jobs checked/collected: 2 SUCCEEDED")

        # Should be no more to collect.
        self.assertEqual(
            self.run_and_get_result(), "Jobs checked/collected: 0")

    @override_settings(JOB_MAX_MINUTES=-1)
    def test_time_out(self):
        # Run 2 extract-features jobs.
        self.upload_image(self.user, self.source)
        self.upload_image(self.user, self.source)
        run_scheduled_jobs_until_empty()

        # Collect jobs; this should time out after collecting 1st job and
        # before collecting 2nd job (as that's when the 1st time-check is done)
        self.assertEqual(
            self.run_and_get_result(),
            "Jobs checked/collected: 1 SUCCEEDED (timed out)")

        # Running again should collect the other job. It'll still say
        # timed out because it didn't get a chance to check if there were
        # more jobs before timing out.
        self.assertEqual(
            self.run_and_get_result(),
            "Jobs checked/collected: 1 SUCCEEDED (timed out)")

        # Should be no more to collect.
        self.assertEqual(
            self.run_and_get_result(), "Jobs checked/collected: 0")

    def test_no_multiple_runs(self):
        """
        Should block multiple existing runs of this task. That way, no spacer
        job can get collected multiple times.
        """
        # Mock a function called by the task, and make that function
        # attempt to run the task recursively.
        with mock.patch(
            'vision_backend.tasks.get_queue_class', call_collect_spacer_jobs
        ):
            queue_and_run_collect_spacer_jobs()

        self.assertEqual(
            Job.objects.filter(job_name='collect_spacer_jobs').count(), 1,
            "Should not have accepted the second run")


class CheckAllSourcesTest(ClientTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)
        cls.source2 = cls.create_source(cls.user)

    @staticmethod
    def run_and_get_result():
        # Note that this may or may not queue a new job instance; perhaps
        # the periodic job was already queued at the end of the previous
        # job's run.
        queue_job('check_all_sources')
        check_all_sources()
        job = Job.objects.filter(
            job_name='check_all_sources',
            status=Job.Status.SUCCESS).latest('pk')
        return job.result_message

    def test(self):
        self.assertEqual(
            self.run_and_get_result(),
            "Queued checks for 2 source(s)")

        # If these lines don't get errors, then the expected
        # queued jobs exist
        Job.objects.get(
            job_name='check_source', arg_identifier=self.source.pk,
            status=Job.Status.PENDING)
        Job.objects.get(
            job_name='check_source', arg_identifier=self.source2.pk,
            status=Job.Status.PENDING)
