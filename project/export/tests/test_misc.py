from io import BytesIO
from zipfile import ZipFile

from django.urls import reverse
from django.utils.html import escape as html_escape

from lib.tests.utils import BasePermissionTest, ClientTest
from ..utils import write_zip


class PermissionTest(BasePermissionTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, cls.labels)

    def test_source_export_serve(self):
        url = reverse('source_export_serve', args=[self.source.pk])

        # Without session variables from export-prepare, this should redirect
        # to browse images.
        template = 'visualization/browse_images.html'

        self.source_to_private()
        self.assertPermissionLevel(
            url, self.SOURCE_VIEW, template=template)
        self.source_to_public()
        self.assertPermissionLevel(
            url, self.SIGNED_IN, template=template,
            deny_type=self.REQUIRE_LOGIN)


class SessionErrorTest(ClientTest):
    """Test session-related error cases on the serve view."""
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)

    def test_no_session_data_timestamp(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('source_export_serve', args=[self.source.pk]),
            dict(session_data_timestamp=''),
            follow=True,
        )

        self.assertRedirects(
            response, reverse('browse_images', args=[self.source.pk]))
        self.assertContains(
            response,
            html_escape(
                "Export failed: Request data doesn't have a"
                " session_data_timestamp."),
        )

    def test_no_session_data(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('source_export_serve', args=[self.source.pk]),
            dict(session_data_timestamp='123'),
            follow=True,
        )

        self.assertRedirects(
            response, reverse('browse_images', args=[self.source.pk]))
        self.assertContains(
            response,
            html_escape(
                "Export failed: We couldn't find the expected data"
                " in your session."),
        )

    def test_mismatched_timestamp(self):
        self.client.force_login(self.user)

        # To modify the session and then save it, it must be stored in a
        # variable first.
        # https://docs.djangoproject.com/en/dev/topics/testing/tools/#django.test.Client.session
        session = self.client.session
        session['export'] = dict(
            timestamp='123', data=dict())
        session.save()

        response = self.client.get(
            reverse('source_export_serve', args=[self.source.pk]),
            dict(session_data_timestamp='456'),
            follow=True,
        )

        self.assertRedirects(
            response, reverse('browse_images', args=[self.source.pk]))
        self.assertContains(
            response,
            html_escape(
                "Export failed: Session data timestamp didn't match."),
        )


class ZipTest(ClientTest):

    def test_write_zip(self):
        zip_stream = BytesIO()
        f1 = b'This is\r\na test file.'
        f2 = b'This is another test file.\r\n'
        names_and_streams = {
            'f1.txt': f1,
            'f2.txt': f2,
        }
        write_zip(zip_stream, names_and_streams)

        zip_file = ZipFile(zip_stream)
        zip_file.testzip()
        f1_read = zip_file.read('f1.txt')
        f2_read = zip_file.read('f2.txt')
        self.assertEqual(f1_read, b'This is\r\na test file.')
        self.assertEqual(f2_read, b'This is another test file.\r\n')
