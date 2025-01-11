# Most annotation-history-related assertions are in the tests
# for views which update annotations (annotation tool, CSV upload, etc.)
# This test module is for miscellaneous annotation history tests.

from django.urls import reverse
from django.utils.html import escape as html_escape

from lib.tests.utils import BasePermissionTest, ClientTest
from .utils import AnnotationHistoryTestMixin


class PermissionTest(BasePermissionTest):
    """
    Test page permissions.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.img = cls.upload_image(cls.user, cls.source)
        cls.labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, cls.labels)

    def test_annotation_history(self):
        url = reverse('annotation_history', args=[self.img.pk])
        template = 'annotations/annotation_history.html'

        self.source_to_private()
        self.assertPermissionLevel(url, self.SOURCE_EDIT, template=template)
        self.source_to_public()
        self.assertPermissionLevel(url, self.SOURCE_EDIT, template=template)


class NoLabelsetTest(ClientTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)
        cls.img = cls.upload_image(cls.user, cls.source)

    def test(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('annotation_history', args=[self.img.pk]),
        )
        self.assertContains(
            response, html_escape(
                "This source doesn't have a labelset yet,"
                " so it can't have any annotations yet."))
        self.assertTemplateUsed(response, 'labels/labelset_required.html')


class AnnotationHistoryAccessTest(ClientTest, AnnotationHistoryTestMixin):
    """
    Test accessing the annotation history page.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)
        labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, labels)

        cls.img = cls.upload_image(cls.user, cls.source)

    def test_access_event(self):
        self.client.force_login(self.user)
        self.client.get(reverse('annotation_tool', args=[self.img.pk]))

        response = self.view_history(self.user)
        self.assert_history_table_equals(
            response,
            [
                ['Accessed annotation tool',
                 '{name}'.format(name=self.user.username)],
            ]
        )
