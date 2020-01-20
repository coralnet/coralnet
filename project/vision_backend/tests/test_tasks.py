import numpy as np

from django.urls import reverse

from lib.tests.utils import ClientTest

from images.models import Image, Point
from images.model_utils import PointGen
from annotations.models import Annotation
from accounts.utils import is_robot_user
from vision_backend.models import Score, Classifier
from vision_backend.tasks import reset_after_labelset_change

import vision_backend.task_helpers as th


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
        th._add_scores(img.pk, scores, label_objs)

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

    def test_point_change_clenup(self):
        """
        If we genereate new point, features must be reset.
        """
        img = self.upload_image(self.user, self.source)
        img.features.extracted = True
        img.features.classified = True
        img.features.save()

        self.assertTrue(Image.objects.get(id=img.id).features.extracted)
        self.assertTrue(Image.objects.get(id=img.id).features.classified)

        self.client.force_login(self.user)
        url = reverse('image_detail', kwargs=dict(image_id=img.id))
        data = dict(
            regenerate_point_locations="Any arbitrary string goes here"
        )
        self.client.post(url, data)

        # Now features should be reset
        self.assertFalse(Image.objects.get(id=img.id).features.extracted)
        self.assertFalse(Image.objects.get(id=img.id).features.classified)


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
        th._add_scores(img.pk, scores, cls.labels)
        th._add_annotations(img.pk, scores, cls.labels, classifier)
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
            self.assertEqual(scores[np.argmax(posteriors)].label, ann.label)
