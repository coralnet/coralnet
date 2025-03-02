import datetime
import json
from unittest import mock

from django.test.utils import override_settings
from django.urls import reverse

from annotations.managers import AnnotationQuerySet
from annotations.models import Annotation
from jobs.models import Job
from jobs.tasks import run_scheduled_jobs, run_scheduled_jobs_until_empty
from jobs.tests.utils import do_job, fabricate_job
from jobs.utils import abort_job, schedule_job
from lib.tests.utils import DecoratorMock, spy_decorator
from vision_backend_api.tests.utils import DeployTestMixin
from ...models import Score, Classifier
from ...task_helpers import SpacerResultHandler
from .utils import BaseTaskTest, source_check_is_scheduled


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
        self.do_collect_spacer_jobs()
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
        self.do_collect_spacer_jobs()
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


class HandleJobResultsDecoratorMock(DecoratorMock):
    @classmethod
    def after(cls, obj, *args, **kwargs):
        # The target method is called within a transaction.
        # Raising an error after that method's body should make the
        # transaction roll back.
        raise ValueError("Inducing a rollback")


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
        job = self.do_collect_spacer_jobs()
        self.assertEqual(
            job.result_message, "Jobs checked/collected: 2 SUCCEEDED")
        self.assertFalse(job.hidden)

        # Should be no more to collect.
        job = self.do_collect_spacer_jobs()
        self.assertEqual(
            job.result_message, "Jobs checked/collected: 0")
        self.assertTrue(job.hidden)

    @override_settings(JOB_MAX_MINUTES=-1)
    def test_time_out(self):
        # Run 6 extract-features jobs.
        for _ in range(6):
            self.upload_image(self.user, self.source)
        run_scheduled_jobs_until_empty()

        def mock_batcher(items, batch_size):
            # Force a batch size of 3 so that we don't have to create too
            # many jobs for this test.
            batch_size = 3
            index = 0
            while index < len(items):
                yield items[index:index+batch_size]
                index += batch_size

        # Collect jobs, with batch_generator() mocked to have batch size 3.
        # This should time out after collecting 1st job and before
        # collecting 4th job (as that's when the 1st time-check is done)
        with mock.patch('vision_backend.tasks.batch_generator', mock_batcher):
            self.assertEqual(
                self.do_collect_spacer_jobs().result_message,
                "Jobs checked/collected: 3 SUCCEEDED (timed out)")

        # Running again should collect the other jobs. It'll still say
        # timed out because it didn't get a chance to check if there were
        # more jobs before timing out.
        self.assertEqual(
            self.do_collect_spacer_jobs().result_message,
            "Jobs checked/collected: 3 SUCCEEDED (timed out)")

        # Should be no more to collect.
        self.assertEqual(
            self.do_collect_spacer_jobs().result_message,
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
            self.do_collect_spacer_jobs()

        self.assertEqual(
            Job.objects.filter(job_name='collect_spacer_jobs').count(), 1,
            "Should not have accepted the second run")

    def test_transaction(self):
        # Run 2 extract-features jobs.
        image1 = self.upload_image(self.user, self.source)
        image2 = self.upload_image(self.user, self.source)
        run_scheduled_jobs_until_empty()

        # Collect jobs, mocking the part near the end of the transaction
        # to force a rollback.
        handle_method = HandleJobResultsDecoratorMock().get_mock(
            SpacerResultHandler.handle_job_results)
        with mock.patch.object(
            SpacerResultHandler, 'handle_job_results', handle_method
        ):
            job = self.do_collect_spacer_jobs()

        self.assertEqual(
            job.result_message, "ValueError: Inducing a rollback")
        # Jobs' completion should not have been committed.
        self.assertEqual(
            Job.objects.get(
                job_name='extract_features', arg_identifier=image1.pk).status,
            Job.Status.IN_PROGRESS)
        self.assertEqual(
            Job.objects.get(
                job_name='extract_features', arg_identifier=image2.pk).status,
            Job.Status.IN_PROGRESS)

    def test_modify_date(self):
        # Run 2 extract-features jobs.
        image_1 = self.upload_image(self.user, self.source)
        image_2 = self.upload_image(self.user, self.source)
        run_scheduled_jobs_until_empty()

        time_before_collect = datetime.datetime.now(datetime.timezone.utc)

        # Collect.
        self.do_collect_spacer_jobs()
        # The jobs should have had their modify dates updated upon collection.
        # The reason they might not is that this involves a bulk_update(),
        # which does not automatically update auto_now dates.
        job_1 = Job.objects.get(
            job_name='extract_features', arg_identifier=image_1.pk)
        self.assertLess(time_before_collect, job_1.modify_date)
        job_2 = Job.objects.get(
            job_name='extract_features', arg_identifier=image_2.pk)
        self.assertLess(time_before_collect, job_2.modify_date)


class CollectSpacerJobsMultipleTypesTest(BaseTaskTest, DeployTestMixin):

    def test(self):
        """
        Should be able to handle a batch of jobs containing multiple
        types of tasks.
        """
        user = self.create_user(
            username='testuser', password='SamplePassword')

        # source_1: set up to collect deploy API jobs.
        source_1 = self.create_source(user)
        self.create_labelset(user, source_1, self.labels)
        classifier = self.upload_data_and_train_classifier(
            source=source_1, user=user)
        deploy_url = reverse('api:deploy', args=[classifier.pk])
        deploy_request_kwargs = self.get_request_kwargs_for_user(
            'testuser', 'SamplePassword')
        # Come back to this source later.

        # source_2: set up to collect training.
        source_2 = self.create_source(user)
        self.create_labelset(user, source_2, self.labels)
        self.upload_images_for_training(source=source_2, user=user)
        # Extract features.
        run_scheduled_jobs_until_empty()
        self.do_collect_spacer_jobs()
        # Run training.
        run_scheduled_jobs_until_empty()

        # Back to source_1 to finish setting up. From here, don't run
        # collect_spacer_jobs() again until all sources are set up.
        images = [
            dict(type='image', attributes=dict(
                url='URL 1', points=[dict(row=10, column=10)]))]
        data = json.dumps(dict(data=images))
        # Schedule deploy.
        self.client.post(deploy_url, data, **deploy_request_kwargs)
        # Deploy.
        self.run_scheduled_jobs_including_deploy()

        # source_3: set up to collect feature extraction.
        source_3 = self.create_source(user)
        self.create_labelset(user, source_3, self.labels)
        self.upload_image(user, source_3)
        self.upload_image(user, source_3)
        # Run feature extraction.
        run_scheduled_jobs_until_empty()

        # Ensure all that stuff hasn't been collected yet.
        deploy_job = Job.objects.filter(
            job_name='classify_image').latest('pk')
        train_job = Job.objects.get(
            job_name='train_classifier', source_id=source_2.pk)
        extract_jobs = list(Job.objects.filter(
            job_name='extract_features', source_id=source_3.pk))
        self.assertEqual(len(extract_jobs), 2)
        for job in [deploy_job, train_job] + extract_jobs:
            self.assertEqual(job.status, Job.Status.IN_PROGRESS)

        # Now collect.
        self.do_collect_spacer_jobs()
        # 1 deploy, 1 train, 2 extract
        self.assert_job_result_message(
            'collect_spacer_jobs', "Jobs checked/collected: 4 SUCCEEDED")
        # Should all be done.
        for job in [deploy_job, train_job] + extract_jobs:
            job.refresh_from_db()
            self.assertEqual(job.status, Job.Status.SUCCESS)
