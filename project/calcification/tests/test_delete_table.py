from bs4 import BeautifulSoup
from django.urls import reverse

from lib.tests.utils import BasePermissionTest, ClientTest
from ..models import CalcifyRateTable
from .utils import (
    create_global_calcify_table, create_source_calcify_table,
    grid_of_tables_html_to_tuples)


class PermissionTest(BasePermissionTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, cls.labels)

        # Make the action form show on Browse Images
        cls.upload_image(cls.user, cls.source)

        create_global_calcify_table('Atlantic', dict())

    def test_calcify_table_delete_in_private_source(self):
        deletion_urls = []
        for i in range(5):
            table = create_source_calcify_table(
                self.source, dict(), name=f"Table {i}")
            deletion_urls.append(reverse(
                'calcification:rate_table_delete_ajax', args=[table.pk]))

        # Accessing the view. Use different images so we can re-test after a
        # successful delete.
        self.source_to_private()
        self.assertPermissionDeniedJson(deletion_urls[0], None, post_data={})
        self.assertPermissionDeniedJson(
            deletion_urls[1], self.user_outsider, post_data={})
        self.assertPermissionDeniedJson(
            deletion_urls[2], self.user_viewer, post_data={})
        self.assertPermissionGrantedJson(
            deletion_urls[3], self.user_editor, post_data={})
        self.assertPermissionGrantedJson(
            deletion_urls[4], self.user_admin, post_data={})

    def test_calcify_table_delete_in_public_source(self):
        deletion_urls = []
        for i in range(5):
            table = create_source_calcify_table(
                self.source, dict(), name=f"Table {i}")
            deletion_urls.append(reverse(
                'calcification:rate_table_delete_ajax', args=[table.pk]))

        self.source_to_public()
        self.assertPermissionDeniedJson(deletion_urls[0], None, post_data={})
        self.assertPermissionDeniedJson(
            deletion_urls[1], self.user_outsider, post_data={})
        self.assertPermissionDeniedJson(
            deletion_urls[2], self.user_viewer, post_data={})
        self.assertPermissionGrantedJson(
            deletion_urls[3], self.user_editor, post_data={})
        self.assertPermissionGrantedJson(
            deletion_urls[4], self.user_admin, post_data={})

    def test_delete_button_requires_edit_perm(self):
        # Ensure there's at least one source table
        create_source_calcify_table(self.source, dict())

        url = reverse('browse_images', args=[self.source.pk])

        def button_is_present():
            response = self.client.get(url, follow=True)
            response_soup = BeautifulSoup(response.content, 'html.parser')

            delete_forms = response_soup.select('form.rate-table-delete')
            return bool(delete_forms)

        self.client.force_login(self.user_editor)
        self.assertTrue(button_is_present())
        self.client.force_login(self.user_viewer)
        self.assertFalse(button_is_present())


class TableDeleteTest(ClientTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)
        cls.labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, cls.labels)

        # Make the action form show on Browse Images
        cls.upload_image(cls.user, cls.source)

        cls.default_atlantic = create_global_calcify_table(
            'Atlantic', dict(),
            name="Default Atlantic rates")
        cls.default_indo_pacific = create_global_calcify_table(
            'Indo-Pacific', dict(),
            name="Default Indo-Pacific rates")

    def test_success(self):
        table = create_source_calcify_table(self.source, dict())
        table_id = table.pk

        self.client.force_login(self.user)
        response = self.client.post(reverse(
            'calcification:rate_table_delete_ajax', args=[table_id]))

        # Table shouldn't be in the DB anymore
        self.assertRaises(
            CalcifyRateTable.DoesNotExist,
            CalcifyRateTable.objects.get,
            pk=table_id)

        # Check response content
        self.assertStatusOK(response)
        response_json = response.json()
        self.assertHTMLEqual(
            response_json['tableDropdownHtml'],
            '<select id="id_rate_table_id" name="rate_table_id">'
            f'  <option value="{self.default_indo_pacific.pk}">'
            f'    {self.default_indo_pacific.name}</option>'
            f'  <option value="{self.default_atlantic.pk}">'
            f'    {self.default_atlantic.name}</option>'
            '</select>')
        self.assertListEqual(
            grid_of_tables_html_to_tuples(
                response_json['gridOfTablesHtml']),
            [
                ("Default Indo-Pacific rates", "",
                 reverse(
                     'calcification:rate_table_download',
                     args=[self.default_indo_pacific.pk]),
                 reverse(
                     'calcification:rate_table_download',
                     args=[self.default_indo_pacific.pk])),
                ("Default Atlantic rates", "",
                 reverse(
                     'calcification:rate_table_download',
                     args=[self.default_atlantic.pk]),
                 reverse(
                     'calcification:rate_table_download',
                     args=[self.default_atlantic.pk])),
            ]
        )

    def test_nonexistent_table_id(self):
        """
        Trying to delete a nonexistent table ID should obviously fail, and
        should also show the permission error in order to obfuscate which
        IDs actually exist.
        """
        table = create_source_calcify_table(self.source, dict())
        table_id = table.pk

        self.client.force_login(self.user)
        # Delete
        response = self.client.post(reverse(
            'calcification:rate_table_delete_ajax', args=[table_id]))
        # Just for good measure, ensure this succeeded
        self.assertNotIn('error', response.json())
        # Attempt to delete the same ID
        response = self.client.post(reverse(
            'calcification:rate_table_delete_ajax', args=[table_id]))

        self.assertEqual(
            response.json()['error'],
            f"You don't have permission to delete table of ID {table_id}.")

    def test_default_table(self):
        """Can't delete default tables using the delete view."""
        table_id = self.default_atlantic.pk

        self.client.force_login(self.user)
        response = self.client.post(reverse(
            'calcification:rate_table_delete_ajax', args=[table_id]))

        # Table should still exist (this should not raise DoesNotExist)
        CalcifyRateTable.objects.get(pk=table_id)

        self.assertEqual(
            response.json()['error'],
            f"You don't have permission to delete table of ID {table_id}.")
