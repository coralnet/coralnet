from datetime import timedelta
from unittest import mock

from django.core.urlresolvers import reverse
from django.test import override_settings
from django.utils import timezone

from annotations.models import Annotation
from images.models import Image
from lib.tests.utils import BaseTest, ClientTest
from vision_backend.models import BatchJob, Score, Classifier
import vision_backend.task_helpers as th
from vision_backend.tasks import (
    alert_batch_jobs_not_succeeded, collect_all_jobs, reset_backend_for_source,
    reset_classifiers_for_source)
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
