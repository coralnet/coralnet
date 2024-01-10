from copy import copy
import json

import numpy as np


class ConfMatrix:
    """
    This class can build and display a confusion matrix.
    """

    def __init__(self, nclasses, labelset=None):
        self.nclasses = nclasses
        self.labelset = labelset
        self.cm = np.zeros((nclasses, nclasses), dtype=int)

    def add(self, gtlabels, estlabels):
        """
        This method adds data to the confusion matrix

        Takes
        gtlabels: array of ground truth labels
        estlabels: array of estimated labels of SAME SIZE as gtlabels
        """

        if not len(gtlabels) == len(estlabels):
            raise Exception(
                'input gtlabels and estlabels must have the same length')
        for (gtl, estl) in zip(gtlabels, estlabels):
            assert gtl > -1 and estl > -1, 'label index must be positive'
            self.cm[gtl, estl] += 1

    def add_select(self, gtlabels, estlabels, scores, th):
        """
        Calls add but only for scores above a certain threshold.
        """
        gt = [g for (g, s) in zip(gtlabels, scores) if s > th]
        est = [e for (e, s) in zip(estlabels, scores) if s > th]
        self.add(gt, est)

    def sort(self, sort_index=None):
        """
        Sorts the confusion matrix from the most prevalent to the least
        prevalent class.
        """
        if sort_index is None:
            totals = self.cm.sum(axis=1)
            sort_index = np.argsort(totals)[::-1]

        # Some black-magix indexing to get the permutations correct.
        tmp = np.arange(self.cm.shape[0])
        cmperm = np.arange(self.cm.shape[0])
        cmperm[sort_index] = tmp

        # The order of the labelset also changes.
        new_labelset = list(np.asarray(self.labelset)[sort_index])

        # Use collapse to do the actual work.
        self.collapse(cmperm, new_labelset)

    def cut(self, newsize):
        """
        Merges the self.classes - newsize last classes to a bucket class called
        OTHER.
        """
        cmperm = np.concatenate((
            np.arange(newsize, dtype=np.uint16),
            np.ones(self.nclasses - newsize, dtype=np.uint16) * newsize))
        self.collapse(cmperm, self.labelset)
        self.labelset = self.labelset[:newsize]
        self.nclasses = newsize + 1
        self.labelset = self.labelset[:newsize] + ['OTHER']

    def collapse(self, collapsemap, new_labelset):
        """
        This nifty method allows the confusion matrix to be collapsed so that
        class i is assigned to new class collapsemap[i]. Since this changes
        the confmatrix, a new labelset must also be provided.
        """

        collapsemap = np.asarray(collapsemap)
        cmin = self.cm
        nnew = max(collapsemap) + 1
        cmint = np.zeros((self.nclasses, nnew))  # intermediate representation
        cmout = np.zeros((nnew, nnew))

        for i in range(nnew):
            cmint[:, i] = np.sum(cmin[:, collapsemap == i], axis=1)

        for i in range(nnew):
            cmout[i, :] = np.sum(cmint[collapsemap == i, :], axis=0)

        self.labelset = new_labelset
        self.cm = cmout

    def render_for_heatmap(self):
        """
        Prepares confmatrix to be rendered by the highcharts.heatmap class.
        """

        cm = self.cm
        rowsums = cm.sum(axis=1)
        # normalizer is different than the actual rowsums only b/c we want to
        # avoid division by zero.
        normalizer = copy(rowsums)
        normalizer[normalizer == 0] = 1

        # normalize
        cm = cm / normalizer[:, np.newaxis]

        # render data to required format.
        cm_render = []
        for col in range(cm.shape[1]):
            for row in range(cm.shape[0]):
                cm_render.append(
                    [col, row, int(round(cm[cm.shape[0]-1-row, col]*100))])

        # This is a hack which enables us to show the class totals in the row
        # titles. (there is no support for this in highcharts.heatmap)
        classes_with_rowsums = [
            '{} [n:{}]'.format(classname, int(rowsum))
            for rowsum, classname in zip(rowsums, self.labelset)
        ][::-1]

        return (
            cm_render,
            json.dumps(self.labelset),
            json.dumps(classes_with_rowsums),
        )

    def get_accuracy(self, cm=None):
        """
        Calculates accuracy and Cohens Kappa from the confusion matrix
        """
        if cm is None:
            cm = self.cm

        acc = np.sum(np.diagonal(cm))/np.sum(cm)

        # probability of the ground truth to predict each class
        pgt = cm.sum(axis=1) / np.sum(cm)
        # probability of the estimates to predict each class
        pest = cm.sum(axis=0) / np.sum(cm)
        # probability of randomly guessing the same thing!
        pe = np.sum(pgt * pest)

        if pe == 1:
            cok = 1
        else:
            cok = (acc - pe) / (1 - pe)  # cohens kappa!

        return acc, cok

    def get_class_accuracy(self, cm=None):
        """
        Returns accuracy per class.
        """

        if cm is None:
            cm = self.cm

        cok = np.zeros(self.nclasses)
        acc = np.zeros(self.nclasses)
        for i in range(self.nclasses):
            collapsemap = np.zeros(self.nclasses, dtype=np.uint8)
            collapsemap[i] = 1
            cmtemp = self.collapse(collapsemap)
            (acc[i], cok[i]) = self.get_accuracy(cm=cmtemp)
        return acc, cok

    def get_class_recalls(self):
        """
        returns recall per class.
        """
        cm = self.cm
        totals = cm.sum(axis=1)
        totals[totals == 0] = 1
        cm = cm / totals[:, np.newaxis]
        return np.diag(cm)

    def get_class_precisions(self):
        """
        returns precision per class.
        """
        cm = self.cm
        totals = cm.sum(axis=0)
        totals[totals == 0] = 1
        cm = cm / totals[:, np.newaxis]
        return np.diag(cm)

    def get_class_f1(self):
        """
        returns the f1 score per class.
        """
        recalls = self.get_class_recalls()
        precisions = self.get_class_precisions()
        f1s_denominator = precisions + recalls
        f1s_denominator[f1s_denominator == 0] = 1
        f1s = 2 * np.multiply(recalls, precisions) / f1s_denominator
        return f1s
