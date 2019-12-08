# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.core.files.base import ContentFile
from django.shortcuts import resolve_url

from export.tests.utils import BaseExportTest
from lib.tests.utils import BasePermissionTest
from labels.models import Label, LocalLabel
from labels.test_labels import LabelTest


class PermissionTest(BasePermissionTest):

    def test_export_labelset_private_source(self):
        url = resolve_url(
            'export_labelset', self.private_source.pk)
        self.assertPermissionDenied(url, None)
        self.assertPermissionDenied(url, self.user_outsider)
        self.assertPermissionGranted(url, self.user_viewer)
        self.assertPermissionGranted(url, self.user_editor)
        self.assertPermissionGranted(url, self.user_admin)

    def test_export_labelset_public_source(self):
        url = resolve_url(
            'export_labelset', self.public_source.pk)
        self.assertPermissionGranted(url, None)
        self.assertPermissionGranted(url, self.user_outsider)
        self.assertPermissionGranted(url, self.user_viewer)
        self.assertPermissionGranted(url, self.user_editor)
        self.assertPermissionGranted(url, self.user_admin)


class GeneralTest(BaseExportTest, LabelTest):
    """
    General tests for the labelset-export-to-CSV view.
    """
    @classmethod
    def setUpTestData(cls):
        super(GeneralTest, cls).setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)
        cls.export_url = resolve_url('export_labelset', cls.source.pk)

        # Create labels and group
        group = cls.create_label_group("Group")
        cls.labels = dict(
            A=cls.create_label(cls.user, "Label A", 'A', group),
            B=cls.create_label(cls.user, "Label B", 'B', group),
            C=cls.create_label(cls.user, "Label C", 'C', group),
        )

    def test_basic(self):
        # Create labelset
        self.create_labelset(self.user, self.source, Label.objects.filter(
            default_code__in=['A', 'C']))
        # Custom code
        local_c = LocalLabel.objects.get(
            labelset=self.source.labelset, code='C')
        local_c.code = 'Coral'
        local_c.save()

        # Export and check
        response = self.client.get(self.export_url)
        expected_lines = [
            'Label ID,Short Code',
            '{id_A},A'.format(id_A=self.labels['A'].pk),
            '{id_C},Coral'.format(id_C=self.labels['C'].pk),
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_unicode(self):
        """Test that non-ASCII characters don't cause issues."""
        # Create labelset
        self.create_labelset(self.user, self.source, Label.objects.filter(
            default_code__in=['A', 'C']))
        # Custom code
        local_a = LocalLabel.objects.get(
            labelset=self.source.labelset, code='A')
        local_a.code = 'あ'
        local_a.save()

        # Export and check
        response = self.client.get(self.export_url)
        # Lines are sorted by short code
        expected_lines = [
            'Label ID,Short Code',
            '{id_A},あ'.format(id_A=self.labels['A'].pk),
            '{id_C},C'.format(id_C=self.labels['C'].pk),
        ]
        self.assert_csv_content_equal(
            response.content.decode('utf-8'), expected_lines)

    def test_upload_and_export(self):
        """Test that we can upload a labelset CSV and then export the same
        CSV."""
        # Upload labelset
        content = ''
        csv_lines = [
            'Label ID,Short Code',
            '{id_A},A'.format(id_A=self.labels['A'].pk),
            '{id_C},Coral'.format(id_C=self.labels['C'].pk),
        ]
        for line in csv_lines:
            content += (line + '\n')
        csv_file = ContentFile(content, name='labelset.csv')

        self.client.force_login(self.user)
        self.client.post(
            resolve_url('labelset_import_preview_ajax', self.source.pk),
            {'csv_file': csv_file},
        )
        self.client.post(
            resolve_url('labelset_import_ajax', self.source.pk),
        )

        # Export and check
        response = self.client.get(self.export_url)
        self.assert_csv_content_equal(response.content, csv_lines)
