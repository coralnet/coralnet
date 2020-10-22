import numpy as np
from django.core.urlresolvers import reverse
from django.test import override_settings
from django.conf import settings
from spacer.config import MIN_TRAINIMAGES
from spacer.messages import ClassifyReturnMsg
from spacer.data_classes import ValResults, ImageLabels

import vision_backend.task_helpers as th
from accounts.utils import is_robot_user
from annotations.models import Annotation
from images.model_utils import PointGen
from images.models import Image, Point
from django.core.files.storage import get_storage_class
from lib.tests.utils import BaseTest, ClientTest
from vision_backend.models import Score, Classifier
from vision_backend.tasks import \
    classify_image, \
    collect_all_jobs, \
    reset_after_labelset_change, \
    submit_classifier

# Create and annotate sufficient nbr images.
# Since 1/8 of images go to val, we need to add a few more to
# make sure there are enough train images.
MIN_IMAGES = int(MIN_TRAINIMAGES * (1+1/8) + 1)


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
class ResetTaskTest(ClientTest):

    @classmethod
    def setUpTestData(cls):
        super(ResetTaskTest, cls).setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)

        labels = cls.create_labels(cls.user,
                                   ['A', 'B', 'C', 'D', 'E', 'F', 'G'],
                                   "Group1")

        cls.create_labelset(cls.user, cls.source, labels.filter(
            name__in=['A', 'B', 'C', 'D', 'E', 'F', 'G'])
        )

    def test_labelset_change_cleanup(self):
        """
        If the labelset is changed, the whole backend must be reset.
        """

        # Create some dummy classifiers
        Classifier(source=self.source).save()
        Classifier(source=self.source).save()

        self.assertEqual(Classifier.objects.filter(
            source=self.source).count(), 2)

        # Create some dummy scores
        img = self.upload_image(self.user, self.source)

        # Pre-fetch label objects
        label_objs = self.source.labelset.get_globals()

        # Check number of points per image
        nbr_points = Point.objects.filter(image=img).count()

        # Fake creation of scores.
        scores = []
        for i in range(nbr_points):
            scores.append(np.random.rand(label_objs.count()))

        return_msg = ClassifyReturnMsg(
            runtime=0.0,
            scores=[(0, 0, [float(s) for s in scrs]) for scrs in scores],
            classes=[label.pk for label in label_objs],
            valid_rowcol=False,
        )

        th.add_scores(img.pk, return_msg, label_objs)

        expected_nbr_scores = min(5, label_objs.count())
        self.assertEqual(Score.objects.filter(image=img).count(),
                         nbr_points * expected_nbr_scores)

        # Fake that the image is classified
        img.features.classified = True
        img.features.save()
        self.assertTrue(Image.objects.get(id=img.id).features.classified)

        # Now, reset the source.
        reset_after_labelset_change(self.source.id)

        self.assertEqual(Classifier.objects.filter(
            source=self.source).count(), 0)
        self.assertEqual(Score.objects.filter(image=img).count(), 0)
        self.assertFalse(Image.objects.get(id=img.id).features.classified)

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


@override_settings(SPACER_QUEUE_CHOICE='vision_backend.queues.LocalQueue')
class ClassifyUtilsTest(ClientTest):
    """Test helper/utility functions used by the classify-image task."""

    @classmethod
    def setUpTestData(cls):
        super(ClassifyUtilsTest, cls).setUpTestData()

        cls.user = cls.create_user()
        cls.points_per_image = 3
        cls.source = cls.create_source(
            cls.user,
            point_generation_type=PointGen.Types.SIMPLE,
            simple_number_of_points=cls.points_per_image,
        )

        cls.labels = cls.create_labels(
            cls.user, ['A', 'B', 'C', 'D'], "Group1")
        cls.create_labelset(cls.user, cls.source, cls.labels)
        # Make the order predictable so that we can specify scores easily
        cls.labels.order_by('default_code')

    @classmethod
    def classify(cls, img, classifier=None, scores=None):
        if not classifier:
            classifier = Classifier(source=cls.source, valid=True)
            classifier.save()
        if not scores:
            scores = [
                np.random.rand(cls.labels.count())
                for _ in range(cls.points_per_image)]

        return_msg = ClassifyReturnMsg(
            runtime=0.0,
            scores=[(0, 0, [float(s) for s in scrs]) for scrs in scores],
            classes=[label.pk for label in cls.labels],
            valid_rowcol=False,
        )

        th.add_scores(img.pk, return_msg, cls.labels)
        th.add_annotations(img.pk, return_msg, cls.labels, classifier)
        img.features.extracted = True
        img.features.classified = True
        img.features.save()

    def test_classify_for_unannotated_image(self):
        """Classify an image which has no annotations yet."""
        img = self.upload_image(self.user, self.source)
        self.classify(img)

        # Should have only robot annotations
        for ann in Annotation.objects.filter(image_id=img.id):
            self.assertTrue(is_robot_user(ann.user))

    def test_classify_for_unconfirmed_image(self):
        """Classify an image where all points have unconfirmed annotations.
        We'll assume we have a robot which is better than the previous (it's
        not _add_annotations()'s job to determine this)."""
        img = self.upload_image(self.user, self.source)

        classifier_1 = Classifier(source=self.source, valid=True)
        classifier_1.save()
        scores = [
            [0.8, 0.5, 0.5, 0.5],  # Point 1: A
            [0.5, 0.5, 0.5, 0.8],  # Point 2: D
            [0.5, 0.8, 0.5, 0.5],  # Point 3: B
        ]
        self.classify(img, classifier=classifier_1, scores=scores)

        classifier_2 = Classifier(source=self.source, valid=True)
        classifier_2.save()
        scores = [
            [0.6, 0.6, 0.7, 0.6],  # Point 1: C
            [0.6, 0.6, 0.6, 0.7],  # Point 2: D (same as before)
            [0.7, 0.6, 0.6, 0.6],  # Point 3: A
        ]
        self.classify(img, classifier=classifier_2, scores=scores)

        # Should have only robot annotations, with point 2 still being from
        # classifier 1
        for ann in Annotation.objects.filter(image_id=img.id):
            # Should be robot
            self.assertTrue(is_robot_user(ann.user))
            if ann.point.point_number == 2:
                self.assertTrue(ann.robot_version.pk == classifier_1.pk)
            else:
                self.assertTrue(ann.robot_version.pk == classifier_2.pk)

    def test_classify_for_partially_confirmed_image(self):
        """Classify an image where some, but not all points have confirmed
        annotations."""
        img = self.upload_image(self.user, self.source)
        # Human annotations
        self.add_annotations(self.user, img, {1: 'A'})
        # Robot annotations
        self.classify(img)

        for ann in Annotation.objects.filter(image_id=img.id):
            if ann.point.point_number == 1:
                # Should still be human
                self.assertFalse(is_robot_user(ann.user))
            else:
                # Should be robot
                self.assertTrue(is_robot_user(ann.user))

    def test_classify_for_fully_confirmed_image(self):
        """Classify an image where all points have confirmed annotations."""
        img = self.upload_image(self.user, self.source)
        # Human annotations
        self.add_annotations(
            self.user, img, {1: 'A', 2: 'B', 3: 'C'})
        # Robot annotations
        self.classify(img)

        # Should have only human annotations
        for ann in Annotation.objects.filter(image_id=img.id):
            self.assertFalse(is_robot_user(ann.user))

    def test_classify_scores_and_labels_match(self):
        img = self.upload_image(self.user, self.source)
        self.classify(img)

        # Check that the max score label matches the annotation label.
        for point in Point.objects.filter(image=img):
            ann = point.annotation
            scores = Score.objects.filter(point=point)
            posteriors = [score.score for score in scores]
            self.assertEqual(scores[int(np.argmax(posteriors))].label, ann.label)


@override_settings(SPACER_QUEUE_CHOICE='vision_backend.queues.LocalQueue')
class ExtractFeaturesTest(ClientTest):

    @classmethod
    def setUpTestData(cls):
        super(ExtractFeaturesTest, cls).setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)

    def test_success(self):
        # After an image upload, features are ready to be submitted.
        img = self.upload_image(self.user, self.source)

        storage = get_storage_class()()

        self.assertTrue(storage.exists(
            settings.FEATURE_VECTOR_FILE_PATTERN.format(
                full_image_path=img.original_file.name)))

        # Then assuming we're using the mock backend, the result should be
        # available for collection immediately.
        collect_all_jobs()

        # Features should be successfully extracted.
        self.assertTrue(img.features.extracted)


@override_settings(SPACER_QUEUE_CHOICE='vision_backend.queues.LocalQueue')
@override_settings(MIN_NBR_ANNOTATED_IMAGES=1)
class TrainClassifierTest(ClientTest):

    @classmethod
    def setUpTestData(cls):
        super(TrainClassifierTest, cls).setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user,
            point_generation_type=PointGen.Types.SIMPLE,
            simple_number_of_points=5)

        labels = cls.create_labels(cls.user, ['A', 'B'], "Group1")
        cls.create_labelset(cls.user, cls.source, labels)

        for i in range(MIN_IMAGES):
            img = cls.upload_image(cls.user, cls.source)
            cls.add_annotations(
                cls.user, img, {1: 'A', 2: 'B', 3: 'A', 4: 'A', 5: 'B'})

        collect_all_jobs()

    def test_train_success(self):
        # Create a classifier
        job_msg = submit_classifier(self.source.id)

        # This source should now have a classifier (though not trained yet)
        self.assertTrue(
            Classifier.objects.filter(source=self.source).count() > 0)

        # Process training result
        collect_all_jobs()

        # Now we should have a trained classifier whose accuracy is the best so
        # far (due to having no previous classifiers), and thus it should have
        # been marked as valid
        latest_classifier = self.source.get_latest_robot()
        self.assertTrue(latest_classifier.valid)

        # Also check that the actual classifier is created in storage.
        storage = get_storage_class()()
        self.assertTrue(storage.exists(
            settings.ROBOT_MODEL_FILE_PATTERN.format(pk=latest_classifier.pk)))

        # And that the val results are stored.
        self.assertTrue(storage.exists(
            settings.ROBOT_MODEL_VALRESULT_PATTERN.format(
                pk=latest_classifier.pk)))

        # Check that the point-counts in val_res is equal to val_data.
        val_res = ValResults.load(job_msg.tasks[0].valresult_loc)
        val_data = ImageLabels.load(job_msg.tasks[0].valdata_loc)
        self.assertEqual(len(val_res.gt),
                         len(val_data) * val_data.samples_per_image)


@override_settings(SPACER_QUEUE_CHOICE='vision_backend.queues.LocalQueue')
@override_settings(MIN_NBR_ANNOTATED_IMAGES=1)
class ClassifyImageTest(ClientTest):

    @classmethod
    def setUpTestData(cls):
        super(ClassifyImageTest, cls).setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user,
            point_generation_type=PointGen.Types.SIMPLE,
            simple_number_of_points=5)

        labels = cls.create_labels(cls.user, ['A', 'B'], "Group1")
        cls.create_labelset(cls.user, cls.source, labels)

        # Two images with features
        for i in range(MIN_IMAGES):
            img = cls.upload_image(cls.user, cls.source)
            cls.add_annotations(
                cls.user, img, {1: 'A', 2: 'B', 3: 'A', 4: 'A', 5: 'B'})

        # Add one more without annotations
        cls.img = cls.upload_image(cls.user, cls.source)
        collect_all_jobs()

        # Train classifier
        submit_classifier(cls.source.id)
        collect_all_jobs()

    def test_classify_unannotated_image(self):
        classify_image(self.img.id)

        self.assertEqual(
            Annotation.objects.filter(image__id=self.img.id).count(), 5)
