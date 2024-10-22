from unittest import mock

from django.test.utils import override_settings

from annotations.managers import AnnotationQuerySet
from annotations.models import Annotation
from jobs.models import Job
from jobs.tasks import run_scheduled_jobs, run_scheduled_jobs_until_empty
from jobs.tests.utils import do_job, fabricate_job
from jobs.utils import abort_job, schedule_job
from lib.tests.utils import spy_decorator
from ...models import Score, Classifier
from .utils import (
    BaseTaskTest, do_collect_spacer_jobs, source_check_is_scheduled)


class ResetClassifiersForSourceTest(BaseTaskTest):

    def test_main(self):

        # Classify image and verify that it worked

        self.upload_data_and_train_classifier()
        img = self.upload_image_and_machine_classify()

        classifier = self.source.last_accepted_classifier
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

        # Classify probably scheduled a source check; run that so we don't have
        # any incomplete jobs remaining.
        run_scheduled_jobs()

        # Reset classifiers
        job = do_job(
            'reset_classifiers_for_source', self.source.pk,
            source_id=self.source.pk)

        self.assertEqual(
            job.status, Job.Status.SUCCESS, "Job should be marked as succeeded")
        self.assertTrue(
            job.persist, "Job should be marked as persistent")
        self.assertTrue(
            source_check_is_scheduled(self.source.pk),
            msg="Should schedule a check after reset",
        )

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
        do_collect_spacer_jobs()
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

    @override_settings(QUERYSET_CHUNK_SIZE=10)
    def test_chunks(self):

        self.upload_data_and_train_classifier()

        for _ in range(5):
            self.upload_image_and_machine_classify()
        self.assertEqual(
            self.source.annotation_set.unconfirmed().count(), 25,
            "Should have 5x5 = 25 unconfirmed annotations")

        # Finish the scheduled source check.
        run_scheduled_jobs()

        # Reset classifiers, while tracking how many chunks are used when
        # deleting the unconfirmed annotations.
        annotation_delete = spy_decorator(AnnotationQuerySet.delete)
        with mock.patch.object(AnnotationQuerySet, 'delete', annotation_delete):
            do_job(
                'reset_classifiers_for_source', self.source.pk,
                source_id=self.source.pk)
        self.assertEqual(
            annotation_delete.mock_obj.call_count, 3,
            msg="Should require 3 chunks of 10 to delete 25 annotations"
        )

        self.assertEqual(
            self.source.annotation_set.unconfirmed().count(), 0,
            "Should have no unconfirmed annotations left")
        self.assertGreater(
            self.source.annotation_set.confirmed().count(), 0,
            "Should still have confirmed annotations")
        self.assertEqual(
            self.source.classifier_set.count(), 0,
            "Should have no classifier left")

    def test_doesnt_affect_other_sources(self):

        self.upload_data_and_train_classifier()
        self.upload_data_and_train_classifier()
        for _ in range(3):
            self.upload_image_and_machine_classify()

        source_2 = self.create_source(self.user)
        self.create_labelset(self.user, source_2, self.labels)
        self.upload_data_and_train_classifier(source=source_2)
        for _ in range(3):
            self.upload_image_and_machine_classify(source=source_2)

        # Finish self.source's scheduled source check.
        run_scheduled_jobs()
        do_job(
            'reset_classifiers_for_source', self.source.pk,
            source_id=self.source.pk)

        self.assertEqual(
            self.source.annotation_set.unconfirmed().count(), 0,
            "self.source should have no unconfirmed annotations left")
        self.assertEqual(
            self.source.classifier_set.count(), 0,
            "self.source should have no classifier left")

        self.assertGreater(
            source_2.annotation_set.unconfirmed().count(), 0,
            "source_2 should still have unconfirmed annotations")
        self.assertGreater(
            source_2.classifier_set.count(), 0,
            "source_2 should still have a classifier")

    def test_source_check_during_reset(self):
        schedule_job(
            'reset_classifiers_for_source', self.source.pk,
            source_id=self.source.pk)
        self.source_check_and_assert(
            "Waiting for reset job to finish",
            assert_msg="Check shouldn't proceed during reset job")

    def test_reset_during_core_job(self):
        # Make this job start as in-progress so that it's not picked up
        # by run_scheduled_jobs().
        check_job = fabricate_job(
            'check_source', self.source.pk,
            source_id=self.source.pk,
            status=Job.Status.IN_PROGRESS,
        )

        reset_job, _ = schedule_job(
            'reset_classifiers_for_source', self.source.pk,
            source_id=self.source.pk)
        # This should just pick up the reset job.
        run_scheduled_jobs()

        reset_job.refresh_from_db()
        self.assertEqual(
            reset_job.status, Job.Status.PENDING,
            msg="Reset job shouldn't have started due to the incomplete"
                " core job (the source check)")

        # Make the check job no longer active.
        abort_job(check_job.pk)
        # Try the reset job again.
        run_scheduled_jobs()

        reset_job.refresh_from_db()
        self.assertEqual(
            reset_job.status, Job.Status.SUCCESS,
            msg="Reset job should have been able to run this time")


class ResetFeaturesForSourceTest(BaseTaskTest):

    def test_main(self):

        img = self.upload_image(self.user, self.source)
        run_scheduled_jobs_until_empty()
        do_collect_spacer_jobs()
        self.assertTrue(img.features.extracted, "img should have features")

        # Abort the scheduled source check.
        abort_job(self.get_latest_job_by_name('check_source').pk)
        # Reset features
        with self.captureOnCommitCallbacks(execute=True):
            job = do_job(
                'reset_features_for_source', self.source.pk,
                source_id=self.source.pk)

        self.assertEqual(
            job.status, Job.Status.SUCCESS, "Job should be marked as succeeded")
        self.assertTrue(
            source_check_is_scheduled(self.source.pk),
            msg="Should schedule a check after reset",
        )

        # Verify that features were cleared

        img.features.refresh_from_db()
        self.assertFalse(img.features.extracted, "img shouldn't have features")

    def test_source_check_during_reset(self):
        schedule_job(
            'reset_features_for_source', self.source.pk,
            source_id=self.source.pk)
        self.source_check_and_assert(
            "Waiting for reset job to finish",
            assert_msg="Check shouldn't proceed during reset job")

    def test_reset_during_core_job(self):
        # Make this job start as in-progress so that it's not picked up
        # by run_scheduled_jobs().
        check_job = fabricate_job(
            'check_source', self.source.pk,
            source_id=self.source.pk,
            status=Job.Status.IN_PROGRESS,
        )

        reset_job, _ = schedule_job(
            'reset_features_for_source', self.source.pk,
            source_id=self.source.pk)
        # This should just pick up the reset job.
        run_scheduled_jobs()

        reset_job.refresh_from_db()
        self.assertEqual(
            reset_job.status, Job.Status.PENDING,
            msg="Reset job shouldn't have started due to the incomplete"
                " core job (the source check)")

        # Make the check job no longer active.
        abort_job(check_job.pk)
        # Try the reset job again.
        run_scheduled_jobs()

        reset_job.refresh_from_db()
        self.assertEqual(
            reset_job.status, Job.Status.SUCCESS,
            msg="Reset job should have been able to run this time")


def schedule_collect_spacer_jobs():
    schedule_job('collect_spacer_jobs')

    class Queue:
        status_counts = dict()
        def collect_jobs(self):
            return []
    return Queue


@override_settings(ENABLE_PERIODIC_JOBS=False)
class CollectSpacerJobsTest(BaseTaskTest):

    def test_success(self):
        # Run 2 extract-features jobs.
        self.upload_image(self.user, self.source)
        self.upload_image(self.user, self.source)
        run_scheduled_jobs_until_empty()

        # Collect jobs.
        # The effects of the actual spacer-job collections (e.g. features
        # marked as extracted) don't need to be tested here. That belongs in
        # e.g. feature-extraction tests.
        job = do_collect_spacer_jobs()
        self.assertEqual(
            job.result_message, "Jobs checked/collected: 2 SUCCEEDED")
        self.assertFalse(job.hidden)

        # Should be no more to collect.
        job = do_collect_spacer_jobs()
        self.assertEqual(
            job.result_message, "Jobs checked/collected: 0")
        self.assertTrue(job.hidden)

    @override_settings(JOB_MAX_MINUTES=-1)
    def test_time_out(self):
        # Run 2 extract-features jobs.
        self.upload_image(self.user, self.source)
        self.upload_image(self.user, self.source)
        run_scheduled_jobs_until_empty()

        # Collect jobs; this should time out after collecting 1st job and
        # before collecting 2nd job (as that's when the 1st time-check is done)
        self.assertEqual(
            do_collect_spacer_jobs().result_message,
            "Jobs checked/collected: 1 SUCCEEDED (timed out)")

        # Running again should collect the other job. It'll still say
        # timed out because it didn't get a chance to check if there were
        # more jobs before timing out.
        self.assertEqual(
            do_collect_spacer_jobs().result_message,
            "Jobs checked/collected: 1 SUCCEEDED (timed out)")

        # Should be no more to collect.
        self.assertEqual(
            do_collect_spacer_jobs().result_message,
            "Jobs checked/collected: 0")

    def test_no_multiple_runs(self):
        """
        Should block multiple existing runs of this task. That way, no spacer
        job can get collected multiple times.
        """
        # Mock a function called by the task, and make that function
        # attempt to run the task recursively.
        with mock.patch(
            'vision_backend.tasks.get_queue_class', schedule_collect_spacer_jobs
        ):
            do_collect_spacer_jobs()

        self.assertEqual(
            Job.objects.filter(job_name='collect_spacer_jobs').count(), 1,
            "Should not have accepted the second run")
