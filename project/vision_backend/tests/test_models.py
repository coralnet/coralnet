import numpy as np

from django.conf import settings

from lib.tests.utils import ClientTest
from labels.models import Label
from images.models import Source, Point
from vision_backend.models import Score

import vision_backend.task_helpers as th


class ImageInitialStatusTest(ClientTest):
    """
    Check a newly uploaded image's status (as relevant to the vision backend).
    """
    @classmethod
    def setUpTestData(cls):
        super(ImageInitialStatusTest, cls).setUpTestData()

    def test_features_extracted_false(self):
        self.user = self.create_user()
        self.source = self.create_source(self.user)
        self.img1 = self.upload_image(self.user, self.source)
        self.assertFalse(self.img1.features.extracted)


class CascadeDeleteTest(ClientTest):

    @classmethod
    def setUpTestData(cls):
        super(CascadeDeleteTest, cls).setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)
    
        labels = cls.create_labels(cls.user, ['A', 'B', 'C', 'D', 'E', 'F', 'G'], "Group1")

        cls.create_labelset(cls.user, cls.source, labels.filter(
            name__in=['A', 'B', 'C', 'D', 'E', 'F', 'G'])
        )

    def test_point_score_cascade(self):
        """
        If a point is deleted all scores for that point should be deleted.
        """
        img = self.upload_image(self.user, self.source)

        # Pre-fetch label objects
        label_objs = self.source.labelset.get_globals()

        # Check number of points per image
        nbr_points = Point.objects.filter(image = img).count()

        # Fake creation of scores.
        scores = []
        for i in range(nbr_points):
            scores.append(np.random.rand(label_objs.count()))
        th._add_scores(img.pk, scores, label_objs)

        expected_nbr_scores = min(5, label_objs.count())
        self.assertEqual(Score.objects.filter(image = img).count(), nbr_points * expected_nbr_scores)
        
        # remove one point
        points = Point.objects.filter(image = img)
        points[0].delete()

        # Now all scores for that point should be gone.
        self.assertEqual(Score.objects.filter(image = img).count(), (nbr_points - 1) * expected_nbr_scores)