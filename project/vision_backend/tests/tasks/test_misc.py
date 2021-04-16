from datetime import timedelta
from unittest import mock

from django.core import mail
from django.core.urlresolvers import reverse
from django.test import override_settings
from django.utils import timezone

from annotations.models import Annotation
from images.models import Image
from lib.tests.utils import BaseTest, ClientTest
from vision_backend.models import BatchJob, Score, Classifier
import vision_backend.task_helpers as th
from vision_backend.tasks import (
    clean_up_old_batch_jobs, collect_all_jobs, reset_backend_for_source,
    reset_classifiers_for_source, warn_about_stuck_jobs)
from vision_backend.tests.tasks.utils import BaseTaskTest, MockImage


class TestJobTokenEncode(BaseTest):

    def test_encode_one(self):

        job_token = th.encode_spacer_job_token([4])
        self.assertIn('4', job_token)

    def test_encode_three(self):
        job_token = th.encode_spacer_job_token([4, 5, 6])
        self.assertIn('4', job_token)
        self.assertIn('5', job_token)
        self.assertIn('6', job_token)

    def test_round_trip(self):
        pks_in = [4, 5, 6]
        job_token = th.encode_spacer_job_token(pks_in)
        pks_out = th.decode_spacer_job_token(job_token)
        self.assertEqual(pks_in, pks_out)


@override_settings(SPACER_QUEUE_CHOICE='vision_backend.queues.LocalQueue')
class ResetTaskTest(BaseTaskTest):

    def test_reset_classifiers_for_source(self):

        # Classify image and verify that it worked

        self.upload_data_and_train_classifier()
        img = self.upload_image_and_machine_classify(self.user, self.source)

        classifier = self.source.get_latest_robot()
        self.assertIsNotNone(classifier, "Should have a classifier")
        classifier_id = classifier.pk

        self.assertTrue(img.features.extracted, "img should have features")
        self.assertTrue(img.features.classified, "img should be classified")
        self.assertGreater(
            Score.objects.filter(image=img).count(), 0,
            "img should have scores")
        self.assertGreater(
            Annotation.objects.filter(image=img).count(), 0,
            "img should have annotations")

        # Reset classifiers
        with mock.patch('images.models.Image.valset', MockImage.valset):
            reset_classifiers_for_source(self.source.pk)

        # Verify that classifier-related objects were cleared, but not features

        self.assertRaises(
            Classifier.DoesNotExist,
            callableObj=Classifier.objects.get, pk=classifier_id,
            msg="Classifier should be deleted")

        img.features.refresh_from_db()
        self.assertTrue(img.features.extracted, "img SHOULD have features")
        self.assertFalse(img.features.classified, "img shouldn't be classified")
        self.assertEqual(
            Score.objects.filter(image=img).count(), 0,
            "img shouldn't have scores")
        self.assertEqual(
            Annotation.objects.filter(image=img).count(), 0,
            "img shouldn't have annotations")

        # Classification should be re-done after collecting jobs (note that
        # this single call can set off a chain of jobs and collections)

        collect_all_jobs()

        img.features.refresh_from_db()
        self.assertTrue(img.features.classified, "img should be classified")
        self.assertGreater(
            Score.objects.filter(image=img).count(), 0,
            "img should have scores")
        self.assertGreater(
            Annotation.objects.filter(image=img).count(), 0,
            "img should have annotations")

    def test_reset_backend_for_source(self):

        # Classify image and verify that it worked

        self.upload_data_and_train_classifier()
        img = self.upload_image_and_machine_classify(self.user, self.source)

        classifier = self.source.get_latest_robot()
        self.assertIsNotNone(classifier, "Should have a classifier")
        classifier_id = classifier.pk

        self.assertTrue(img.features.extracted, "img should have features")
        self.assertTrue(img.features.classified, "img should be classified")
        self.assertGreater(
            Score.objects.filter(image=img).count(), 0,
            "img should have scores")
        self.assertGreater(
            Annotation.objects.filter(image=img).count(), 0,
            "img should have annotations")

        # Reset backend
        with mock.patch('images.models.Image.valset', MockImage.valset):
            reset_backend_for_source(self.source.pk)

        # Verify that backend objects were cleared

        self.assertRaises(
            Classifier.DoesNotExist,
            callableObj=Classifier.objects.get, pk=classifier_id,
            msg="Classifier should be deleted")

        img.features.refresh_from_db()
        self.assertFalse(img.features.extracted, "img shouldn't have features")
        self.assertFalse(img.features.classified, "img shouldn't be classified")
        self.assertEqual(
            Score.objects.filter(image=img).count(), 0,
            "img shouldn't have scores")
        self.assertEqual(
            Annotation.objects.filter(image=img).count(), 0,
            "img shouldn't have annotations")

        # Backend objects should be re-created after collecting jobs

        collect_all_jobs()

        img.features.refresh_from_db()
        self.assertTrue(img.features.extracted, "img should have features")
        self.assertTrue(img.features.classified, "img should be classified")
        self.assertGreater(
            Score.objects.filter(image=img).count(), 0,
            "img should have scores")
        self.assertGreater(
            Annotation.objects.filter(image=img).count(), 0,
            "img should have annotations")

    def test_point_change_cleanup(self):
        """
        If we generate new points, features must be reset.
        """
        img = self.upload_image(self.user, self.source)
        img.features.extracted = True
        img.features.classified = True
        img.features.save()

        self.assertTrue(Image.objects.get(id=img.id).features.extracted)
        self.assertTrue(Image.objects.get(id=img.id).features.classified)

        self.client.force_login(self.user)
        url = reverse('image_regenerate_points', args=[img.id])
        self.client.post(url)

        # Now features should be reset
        self.assertFalse(Image.objects.get(id=img.id).features.extracted)
        self.assertFalse(Image.objects.get(id=img.id).features.classified)


class BatchJobCleanupTest(ClientTest):
    """
    Test cleanup of old AWS Batch jobs.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()

    def test_job_selection(self):
        """
        Only jobs eligible for cleanup should be cleaned up.
        """
        # More than one job too new to be cleaned up.

        job = BatchJob(job_token='new')
        job.save()

        job = BatchJob(job_token='29 days ago')
        job.save()
        job.create_date = timezone.now() - timedelta(days=29)
        job.save()

        # More than one job old enough to be cleaned up.

        job = BatchJob(job_token='31 days ago')
        job.save()
        job.create_date = timezone.now() - timedelta(days=31)
        job.save()

        job = BatchJob(job_token='32 days ago')
        job.save()
        job.create_date = timezone.now() - timedelta(days=32)
        job.save()

        clean_up_old_batch_jobs()

        self.assertTrue(
            BatchJob.objects.filter(job_token='new').exists(),
            "Shouldn't clean up new job")
        self.assertTrue(
            BatchJob.objects.filter(job_token='29 days ago').exists(),
            "Shouldn't clean up 29 day old job")
        self.assertFalse(
            BatchJob.objects.filter(job_token='31 days ago').exists(),
            "Shouldn't clean up 31 day old job")
        self.assertFalse(
            BatchJob.objects.filter(job_token='32 days ago').exists(),
            "Shouldn't clean up 32 day old job")


class WarnAboutStuckJobsTest(ClientTest):
    """
    Test warning about AWS Batch jobs that haven't completed in a timely
    fashion.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()

    def test_job_selection_by_date(self):
        """
        Only warn about jobs between 5 and 6 days old, and warn once per job.
        """
        job = BatchJob.objects.create(job_token='1', batch_token='4d 23h ago')
        job.create_date = timezone.now() - timedelta(days=4, hours=23)
        job.save()

        job = BatchJob.objects.create(job_token='2', batch_token='5d 1h ago')
        job.create_date = timezone.now() - timedelta(days=5, hours=1)
        job.save()

        job = BatchJob.objects.create(job_token='3', batch_token='5d 23h ago')
        job.create_date = timezone.now() - timedelta(days=5, hours=23)
        job.save()

        job = BatchJob.objects.create(job_token='4', batch_token='6d 1h ago')
        job.create_date = timezone.now() - timedelta(days=6, hours=1)
        job.save()

        warn_about_stuck_jobs()

        self.assertEqual(len(mail.outbox), 2)
        subjects = [sent_email.subject for sent_email in mail.outbox]
        self.assertIn(
            "[CoralNet] Job 5d 1h ago not completed after 5 days.", subjects)
        self.assertIn(
            "[CoralNet] Job 5d 23h ago not completed after 5 days.", subjects)

    def test_job_selection_by_status(self):
        """
        Only warn about non-completed jobs.
        """
        job = BatchJob.objects.create(
            job_token='1', batch_token='PENDING', status='PENDING')
        job.create_date = timezone.now() - timedelta(days=5, hours=1)
        job.save()

        job = BatchJob.objects.create(
            job_token='2', batch_token='SUCCEEDED', status='SUCCEEDED')
        job.create_date = timezone.now() - timedelta(days=5, hours=1)
        job.save()

        job = BatchJob.objects.create(
            job_token='3', batch_token='RUNNING', status='RUNNING')
        job.create_date = timezone.now() - timedelta(days=5, hours=1)
        job.save()

        job = BatchJob.objects.create(
            job_token='4', batch_token='FAILED', status='FAILED')
        job.create_date = timezone.now() - timedelta(days=5, hours=1)
        job.save()

        warn_about_stuck_jobs()

        self.assertEqual(len(mail.outbox), 2)
        subjects = [sent_email.subject for sent_email in mail.outbox]
        self.assertIn(
            "[CoralNet] Job PENDING not completed after 5 days.", subjects)
        self.assertIn(
            "[CoralNet] Job RUNNING not completed after 5 days.", subjects)
