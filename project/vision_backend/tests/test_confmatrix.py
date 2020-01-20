import random
import string

from lib.tests.utils import BaseTest
from vision_backend.confmatrix import ConfMatrix


class ConfMatrixBasics(BaseTest):
    """
    Check a newly uploaded image's status (as relevant to the vision backend).
    """
    @classmethod
    def setUpTestData(cls):
        super(ConfMatrixBasics, cls).setUpTestData()

    def makelabelset(self, k):
        return list(string.ascii_lowercase)[:k]

    def test_simple_add(self):

        cm = ConfMatrix(2)
        cm.add([0, 1], [1, 0])
        self.assertEqual(cm.cm[0,0], 0)

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

        cm = ConfMatrix(2, labelset = self.makelabelset(2))
        cm.add(gt, est)
        
        self.assertEqual(cm.cm[1, 1], 2)
        self.assertEqual(cm.labelset[0], 'a')
        
        cm.sort()
        self.assertEqual(cm.cm[0, 0], 2)
        self.assertEqual(cm.labelset[0], 'b')

    def test_sort_more_complicated(self):
        gt = [0, 0, 0, 1, 1, 1, 1, 1, 2, 3, 3]
        est = [0, 0, 0, 1, 1, 1, 0, 0, 2, 3, 3]

        cm = ConfMatrix(4, labelset = self.makelabelset(4))
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

        cm = ConfMatrix(4, labelset = self.makelabelset(4))
        cm.add(gt, est)
        self.assertEqual(sum(sum(cm.cm[2:, 2:])), 3)
        cm.cut(2)
        self.assertEqual(cm.cm[2, 2], 3)	 