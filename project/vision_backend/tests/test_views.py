# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from unittest import skip

from django.urls import reverse

from export.tests.utils import BaseExportTest
from labels.models import Label
from lib.tests.utils import BasePermissionTest, ClientTest


class BackendViewPermissions(BasePermissionTest):

    def test_backend_main(self):
        url = reverse('backend_main', args=[self.source.pk])
        template = 'vision_backend/backend_main.html'

        self.source_to_private()
        self.assertPermissionLevel(url, self.SOURCE_VIEW, template=template)
        self.source_to_public()
        self.assertPermissionLevel(url, self.SIGNED_OUT, template=template)

    @skip(
        "Skip as long as backend_overview requires Redis"
        " (in which case Travis can't pass this test).")
    def test_backend_overview(self):
        # Requires at least 1 image
        self.upload_image(self.user, self.source)

        url = reverse('backend_overview')
        template = 'vision_backend/overview.html'

        self.assertPermissionLevel(
            url, self.SUPERUSER, template=template,
            deny_type=self.REQUIRE_LOGIN)

    def test_cm_test(self):
        url = reverse('cm_test')
        template = 'vision_backend/cm_test.html'

        self.assertPermissionLevel(
            url, self.SUPERUSER, template=template,
            deny_type=self.REQUIRE_LOGIN)


class BackendMainTest(ClientTest):

    @classmethod
    def setUpTestData(cls):
        super(BackendMainTest, cls).setUpTestData()

        cls.user = cls.create_user()

        cls.source = cls.create_source(cls.user)
        cls.create_labels(cls.user, ['A', 'B'], 'Group1')
        cls.create_labels(cls.user, ['C'], 'Group2')
        labels = Label.objects.all()
        cls.create_labelset(cls.user, cls.source, labels)
        cls.valres_classes = [
            labels.get(name=name).pk for name in ['A', 'B', 'C']]

        cls.url = reverse('backend_main', args=[cls.source.pk])

    def test_no_robot(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)

        self.assertNotContains(response, '<div id="cm"')
        self.assertContains(
            response, "This source does not have an automated classifier yet.")

    def test_confusion_matrix(self):
        robot = self.create_robot(self.source)
        valres = dict(
            classes=self.valres_classes,
            gt=[0, 0, 0, 0, 0, 0, 1, 1, 1, 1],
            est=[0, 0, 1, 1, 1, 1, 1, 1, 1, 0],
            scores=[.8]*10,
        )

        # Add valres to the session so that we don't have to create it in S3.
        #
        # "Be careful: To modify the session and then save it,
        # it must be stored in a variable first (because a new SessionStore
        # is created every time this property is accessed)"
        # http://stackoverflow.com/a/4454671/
        session = self.client.session
        session['valres'] = valres
        session['ccpk'] = robot.pk
        session.save()

        self.client.force_login(self.user)
        response = self.client.get(self.url)

        # Confusion matrix element should be on the page
        self.assertContains(response, '<div id="cm"')
        self.assertNotContains(
            response, "This source does not have an automated classifier yet.")

        # Check the confusion matrix context var
        # A: 2 classed as A, 4 classed as B (33% / 67%)
        # B: 1 classed as A, 3 classed as B (25% / 75%)
        # C: 0
        # Total: 10 points, 5 (50%) correctly classed
        context_cm = response.context['cm']
        self.assertListEqual(
            context_cm['data_'],
            [
                [0, 0, 0], [0, 1, 25], [0, 2, 33],
                [1, 0, 0], [1, 1, 75], [1, 2, 67],
                [2, 0, 0], [2, 1,  0], [2, 2,  0],
            ]
        )
        self.assertEqual(
            context_cm['xlabels'],
            '["A (A)", "B (B)", "C (C)"]')
        self.assertEqual(
            context_cm['ylabels'],
            '["C (C) [n:0]", "B (B) [n:4]", "A (A) [n:6]"]')
        self.assertEqual(
            context_cm['title_'],
            '"Confusion matrix for full labelset (acc:50.0, n: 10)"')
        self.assertEqual(context_cm['css_height'], 500)
        self.assertEqual(context_cm['css_width'], 600)

    def test_confusion_matrix_many_labels(self):
        source = self.create_source(self.user)

        # '0', ..., '51'
        label_names = [str(n) for n in range(0, 51+1)]
        labels = self.create_labels(self.user, label_names, 'NumberGroup')
        self.create_labelset(self.user, source, labels)

        robot = self.create_robot(source)
        # Every label twice, except '30' and '31' which appear once.
        # This gives us 50 'most common' labels and 2 labels which will be
        # grouped into 'OTHER'.
        annotations_as_label_indices = list(range(0, 51+1)) * 2
        annotations_as_label_indices.remove(30)
        annotations_as_label_indices.remove(31)
        valres = dict(
            classes=[labels.get(name=name).pk for name in label_names],
            gt=annotations_as_label_indices,
            est=annotations_as_label_indices,
            scores=[.8]*102,
        )

        session = self.client.session
        session['valres'] = valres
        session['ccpk'] = robot.pk
        session.save()

        self.client.force_login(self.user)
        response = self.client.get(reverse('backend_main', args=[source.pk]))

        context_cm = response.context['cm']

        # Cut from 52 labels to 50 labels + 1 'OTHER' label
        self.assertEqual(len(context_cm['data_']), 51*51)

        self.assertIn('0 (0)', context_cm['xlabels'])
        self.assertIn('51 (51)', context_cm['xlabels'])
        self.assertIn('OTHER', context_cm['xlabels'])
        self.assertNotIn('30 (30)', context_cm['xlabels'])
        self.assertNotIn('31 (31)', context_cm['xlabels'])

        self.assertIn('0 (0)', context_cm['ylabels'])
        self.assertIn('51 (51)', context_cm['ylabels'])
        self.assertIn('OTHER', context_cm['ylabels'])
        self.assertNotIn('30 (30)', context_cm['ylabels'])
        self.assertNotIn('31 (31)', context_cm['ylabels'])


class BackendMainConfusionMatrixExportTest(BaseExportTest):

    @classmethod
    def setUpTestData(cls):
        super(BackendMainConfusionMatrixExportTest, cls).setUpTestData()

        cls.user = cls.create_user()

        cls.source = cls.create_source(cls.user)
        cls.create_labels(cls.user, ['A', 'B'], 'Group1')
        cls.create_labels(cls.user, ['C'], 'Group2')
        labels = Label.objects.all()
        cls.create_labelset(cls.user, cls.source, labels)
        cls.valres_classes = [
            labels.get(name=name).pk for name in ['A', 'B', 'C']]

        cls.url = reverse('backend_main', args=[cls.source.pk])

    def test_export_basic(self):
        robot = self.create_robot(self.source)
        valres = dict(
            classes=self.valres_classes,
            gt=[0, 0, 0, 0, 0, 0, 1, 1, 1, 1],
            est=[0, 0, 1, 1, 1, 1, 1, 1, 1, 0],
            scores=[.8]*10,
        )

        # Add valres to the session so that we don't have to create it in S3.
        session = self.client.session
        session['valres'] = valres
        session['ccpk'] = robot.pk
        session.save()

        self.client.force_login(self.user)
        response = self.client.post(
            self.url, data=dict(export_cm="Export confusion matrix"))

        expected_lines = [
            'A (A),2,4,0',
            'B (B),1,3,0',
            'C (C),0,0,0',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_export_with_confidence_threshold(self):
        robot = self.create_robot(self.source)
        valres = dict(
            classes=self.valres_classes,
            gt=[0, 0, 0, 0, 0, 0, 1, 1, 1, 1],
            est=[0, 0, 1, 1, 1, 1, 1, 1, 1, 0],
            scores=[.9, .9, .9, .8, .8, .8, .8, .7, .7, .7],
        )
        session = self.client.session
        session['valres'] = valres
        session['ccpk'] = robot.pk
        session.save()

        self.client.force_login(self.user)
        response = self.client.post(
            self.url + '?confidence_threshold=75',
            data=dict(export_cm="Export confusion matrix"))

        expected_lines = [
            'A (A),2,4,0',
            'B (B),0,1,0',
            'C (C),0,0,0',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_export_in_functional_groups_mode(self):
        robot = self.create_robot(self.source)

        # 0 and 1 are in Group1; 2 is in Group2. Being in functional groups
        # mode means we don't care if gt/est are 0/0, 0/1, 1/0, or 1/1. Those
        # are all matches for Group1.
        valres = dict(
            classes=self.valres_classes,
            gt=[0, 0, 0, 1, 1, 1, 2, 2, 2, 2],
            est=[0, 1, 2, 0, 1, 2, 0, 1, 1, 2],
            scores=[.8]*10,
        )
        session = self.client.session
        session['valres'] = valres
        session['ccpk'] = robot.pk
        session.save()

        self.client.force_login(self.user)
        response = self.client.post(
            self.url + '?labelmode=func',
            data=dict(export_cm="Export confusion matrix"))

        expected_lines = [
            'Group1,4,2',
            'Group2,3,1',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_export_with_unicode(self):
        robot = self.create_robot(self.source)
        valres = dict(
            classes=self.valres_classes,
            gt=[0, 0, 0, 0, 0, 0, 1, 1, 1, 1],
            est=[0, 0, 1, 1, 1, 1, 1, 1, 1, 0],
            scores=[.8]*10,
        )
        session = self.client.session
        session['valres'] = valres
        session['ccpk'] = robot.pk
        session.save()

        local_label_a = self.source.labelset.get_labels().get(code='A')
        local_label_a.code = 'あ'
        local_label_a.save()

        self.client.force_login(self.user)
        response = self.client.post(
            self.url, data=dict(export_cm="Export confusion matrix"))

        expected_lines = [
            'A (あ),2,4,0',
            'B (B),1,3,0',
            'C (C),0,0,0',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)
