import json
import random
import string

from lib.tests.utils import BaseTest
from vision_backend.confmatrix import ConfMatrix


class ConfMatrixBasics(BaseTest):
    """
    Test the ConfMatrix class.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

    @staticmethod
    def makelabelset(k):
        """Example: if k = 5, this returns ['a', 'b', 'c', 'd', 'e']"""
        return list(string.ascii_lowercase)[:k]

    def test_add(self):
        cm = ConfMatrix(2)
        cm.add([0, 1], [1, 0])
        self.assertEqual(cm.cm[0, 0], 0)

    def test_add_bad_input(self):
        cm = ConfMatrix(2)
        with self.assertRaises(ValueError):
            cm.add([0, 1], [1, 0, 1])

    def test_simple(self):
        k = 50
        gt = random.sample(range(k), 50)
        est = random.sample(range(k), 50)

        cm = ConfMatrix(k)
        cm.add(gt, est)
        self.assertEqual(sum(sum(cm.cm)), 50)

    def test_input(self):
        k = 50
        gt = random.sample(range(k), 50)
        est = random.sample(range(k), 50)
        est[0] = 100

        cm = ConfMatrix(k)
        self.assertRaises(IndexError, cm.add, gt, est)

        est[0] = -1

        cm = ConfMatrix(k)
        self.assertRaises(AssertionError, cm.add, gt, est)

    def test_empty_labels(self):
        gt = random.sample(range(10, 60), 50)
        est = random.sample(range(10, 60), 50)

        cm = ConfMatrix(100)
        cm.add(gt, est)
        self.assertEqual(sum(sum(cm.cm)), 50)

    def test_sort_simple(self):
        gt = [0, 1, 1]
        est = [0, 1, 1]

        cm = ConfMatrix(2, labelset=self.makelabelset(2))
        cm.add(gt, est)
        
        self.assertEqual(cm.cm[1, 1], 2)
        self.assertEqual(cm.labelset[0], 'a')
        
        cm.sort()
        self.assertEqual(cm.cm[0, 0], 2)
        self.assertEqual(cm.labelset[0], 'b')

    def test_sort_more_complicated(self):
        gt = [0, 0, 0, 1, 1, 1, 1, 1, 2, 3, 3]
        est = [0, 0, 0, 1, 1, 1, 0, 0, 2, 3, 3]

        cm = ConfMatrix(4, labelset=self.makelabelset(4))
        cm.add(gt, est)
        
        self.assertEqual(cm.cm[1, 1], 3)
        self.assertEqual(cm.cm[3, 3], 2)
        self.assertEqual(cm.cm[1, 0], 2)
        self.assertEqual(cm.labelset, ['a', 'b', 'c', 'd'])

        cm.sort()
        self.assertEqual(cm.cm[0, 0], 3)
        self.assertEqual(cm.cm[2, 2], 2)
        self.assertEqual(cm.cm[0, 1], 2)
        self.assertEqual(cm.labelset, ['b', 'a', 'd', 'c'])

    def test_cut(self):
        gt = [0, 0, 0, 1, 1, 1, 1, 1, 2, 3, 3]
        est = [0, 0, 0, 1, 1, 1, 0, 0, 2, 3, 3]

        cm = ConfMatrix(4, labelset=self.makelabelset(4))
        cm.add(gt, est)
        self.assertEqual(sum(sum(cm.cm[2:, 2:])), 3)
        cm.cut(2)
        self.assertEqual(cm.cm[2, 2], 3)

    def test_render_for_heatmap(self):
        gt = [0, 0, 0, 0, 0, 1, 1, 1, 1]
        est = [0, 0, 1, 1, 1, 1, 1, 1, 0]

        cm = ConfMatrix(2, labelset=self.makelabelset(2))
        cm.add(gt, est)
        data, xlabels, ylabels = cm.render_for_heatmap()

        self.assertListEqual(
            data,
            [
                # Bottom left of CM; gt b which have est a
                [0, 0, 25],
                # Top left; gt a which have est a
                [0, 1, 40],
                # Bottom right; gt b which have est b
                [1, 0, 75],
                # Top right; gt a which have est b
                [1, 1, 60],
            ],
        )
        self.assertEqual(xlabels, json.dumps(['a', 'b']))
        self.assertEqual(
            ylabels, json.dumps(['b [n:4]', 'a [n:5]']))

    def test_get_accuracy(self):
        gt = [0, 0, 0, 0, 0, 1, 1, 1, 1]
        est = [0, 0, 1, 1, 1, 1, 1, 1, 0]

        cm = ConfMatrix(2, labelset=self.makelabelset(2))
        cm.add(gt, est)
        accuracy, cohens_kappa = cm.get_accuracy()

        # 5 of 9 estimated labels match ground truth
        self.assertAlmostEqual(accuracy, 0.5555556)
        # cm = [2 3
        #       1 3]
        # pe = (((2+1)/9) * ((2+3)/9)) + (((3+3)/9) * ((1+3)/9)) = 0.48148148
        # cohens_kappa = (5/9 - 0.48148148) / (1 - 0.48148148)
        self.assertAlmostEqual(cohens_kappa, 0.1428571)
