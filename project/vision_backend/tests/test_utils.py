import random

import numpy as np

from lib.tests.utils import BaseTest, ClientTest
from vision_backend import utils

from images.models import Source
from labels.models import Label, LabelGroup, LocalLabel


class TestLabelSetMapper(ClientTest):
    """
    Test labelset_mapper
    """

    @classmethod
    def setUpTestData(cls):
        super(TestLabelSetMapper, cls).setUpTestData()

        cls.user = cls.create_user()

        cls.source = cls.create_source(
            cls.user, visibility=Source.VisibilityTypes.PRIVATE)

        cls.create_labels(cls.user, ['A', 'B', 'C'], 'GroupA', default_codes = ['a', 'b', 'c'])
        cls.create_labels(cls.user, ['AA', 'BB', 'CC'], 'GroupB', default_codes = ['aa', 'bb', 'cc'])
        cls.create_labelset(cls.user, cls.source, Label.objects.filter())
        


    def test_full(self):
        pklist = []
        pklist.append(Label.objects.get(name = 'A').pk)
        pklist.append(Label.objects.get(name = 'B').pk)
        classmap, classnames = utils.labelset_mapper('full', pklist, self.source)
        
        # classmap is always identity for the full labelset
        for i in range(2):
            self.assertEqual(classmap[i], i)
        
        self.assertEqual('A (a)', classnames[0])
        self.assertFalse('B' in classnames[0])
        
        self.assertEqual(len(classnames), 2)

    def test_full_inverse(self):  
        pklist = []
        pklist.append(Label.objects.get(name = 'B').pk)
        pklist.append(Label.objects.get(name = 'A').pk) 
        classmap, classnames = utils.labelset_mapper('full', pklist, self.source)
        
        # classmap is always identity for the full labelset
        for i in range(2):
            self.assertEqual(classmap[i], i)
        
        self.assertEqual('A (a)', classnames[1])
        self.assertFalse('B' in classnames[1])
        
        self.assertEqual(len(classnames), 2)

    def test_full_skip(self):
        pklist = []
        pklist.append(Label.objects.get(name = 'C').pk)
        pklist.append(Label.objects.get(name = 'A').pk)
        classmap, classnames = utils.labelset_mapper('full', pklist, self.source)
        
        # classmap is always identity for the full labelset
        for i in range(2):
            self.assertEqual(classmap[i], i)
        
        self.assertEqual('C (c)', classnames[0])
        self.assertEqual('A (a)', classnames[1])
        self.assertFalse('B' in classnames[0])
        self.assertFalse('A' in classnames[0])

        self.assertEqual(len(classnames), 2)

    def test_func(self):
        pklist = []
        pklist.append(Label.objects.get(name = 'A').pk)
        pklist.append(Label.objects.get(name = 'B').pk)

        classmap, classnames = utils.labelset_mapper('func', pklist, self.source)
        self.assertEqual(len(classnames), 1)
        self.assertEqual(len(classmap.keys()), 2)
        self.assertEqual(classmap[0], 0)
        self.assertEqual(classmap[1], 0)

        self.assertTrue('GroupA' in classnames[0])

        pklist = []
        pklist.append(Label.objects.get(name = 'A').pk)
        pklist.append(Label.objects.get(name = 'AA').pk)
        
        classmap, classnames = utils.labelset_mapper('func', pklist, self.source)
        self.assertEqual(len(classnames), 2)
        self.assertEqual(len(classmap.keys()), 2)
        self.assertEqual(classmap[0], 0)
        self.assertEqual(classmap[1], 1)

        self.assertEqual('GroupA', classnames[0])
        self.assertEqual('GroupB', classnames[1])

        pklist = []
        pklist.append(Label.objects.get(name = 'AA').pk)
        pklist.append(Label.objects.get(name = 'A').pk)

        classmap, classnames = utils.labelset_mapper('func', pklist, self.source)
        self.assertEqual(len(classnames), 2)
        self.assertEqual(len(classmap.keys()), 2)
        self.assertEqual(classmap[0], 0)
        self.assertEqual(classmap[1], 1)

        self.assertEqual('GroupB', classnames[0])
        self.assertEqual('GroupA', classnames[1])


        pklist = []
        pklist.append(Label.objects.get(name = 'A').pk)
        pklist.append(Label.objects.get(name = 'B').pk)
        pklist.append(Label.objects.get(name = 'AA').pk)

        classmap, classnames = utils.labelset_mapper('func', pklist, self.source)
        self.assertEqual(len(classnames), 2)
        self.assertEqual(len(classmap.keys()), 3)
        self.assertEqual(classmap[0], 0)
        self.assertEqual(classmap[1], 0)
        self.assertEqual(classmap[2], 1)

        self.assertEqual('GroupA', classnames[0])
        self.assertEqual('GroupB', classnames[1])

        pklist = []
        pklist.append(Label.objects.get(name = 'AA').pk)
        pklist.append(Label.objects.get(name = 'A').pk)
        pklist.append(Label.objects.get(name = 'B').pk)

        classmap, classnames = utils.labelset_mapper('func', pklist, self.source)
        self.assertEqual(len(classnames), 2)
        self.assertEqual(len(classmap.keys()), 3)
        self.assertEqual(classmap[0], 0)
        self.assertEqual(classmap[1], 1)
        self.assertEqual(classmap[2], 1)

        self.assertEqual('GroupB', classnames[0])
        self.assertEqual('GroupA', classnames[1])


    

        
        





class LabelMapTester(BaseTest):
    """
    Test map_labels
    """

    def test_simple(self):
        labelmap = {
            1: 10
        }
        org = [1, 1 , 1]
        new = utils.map_labels(org, labelmap)
        for member in new:
            self.assertEqual(member, 10)

    def test_missing(self):
        labelmap = {
            1: 10
        }
        org = [1, 3, 1]
        new = utils.map_labels(org, labelmap)
        self.assertEqual(new[0], 10)
        self.assertEqual(new[1], -1)
        self.assertEqual(new[2], 10)

    def test_nomap(self):
        org = [1, 1 , 1]
        new = utils.map_labels(org, dict())
        for member in new:
            self.assertEqual(member, -1)



class AlleviateTester(BaseTest):
    """
    Test get_alleviate
    """

    def test_error_input(self):
        
        self.assertRaises(ValueError, utils.get_alleviate, [1], [1, 2], [2])
        self.assertRaises(ValueError, utils.get_alleviate, [1, 2], [1], [2])
        self.assertRaises(ValueError, utils.get_alleviate, [1], [1], [1, 2])
        self.assertRaises(ValueError, utils.get_alleviate, [], [], [])


    def test_short(self):
        accs, ratios, ths = utils.get_alleviate([1], [1], [1])
        self.assertEqual(3, len(accs))

    def test_medium(self):
        k = 100
        gt = random.sample(range(k), k)
        est = random.sample(range(k), k)
        scores = np.ones(k, dtype = np.int)

        accs, ratios, ths = utils.get_alleviate(gt, est, scores)
        self.assertEqual(k + 2, len(accs))
        self.assertEqual(ratios[0], 100)
        self.assertEqual(ratios[-1], 0)

    def test_long(self):
        for k in [248, 249, 250, 300, 3000]:
            gt = random.sample(range(k), k)
            est = random.sample(range(k), k)
            scores = np.ones(k, dtype = np.int)

            accs, ratios, ths = utils.get_alleviate(gt, est, scores)
            self.assertEqual(250, len(accs))