from io import StringIO

from bs4 import BeautifulSoup
from django.core.files.base import ContentFile
from django.urls import reverse

from lib.tests.utils import (
    BasePermissionTest, ClientTest, sample_image_as_file)
from ..models import CalcifyRateTable
from .utils import (
    create_global_calcify_table, grid_of_tables_html_to_tuples)


class PermissionTest(BasePermissionTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, cls.labels)

        # Make the action form show on Browse Images
        cls.upload_image(cls.user, cls.source)

        create_global_calcify_table('Atlantic', dict())

    def test_calcify_table_upload(self):
        url = reverse(
            'calcification:rate_table_upload_ajax', args=[self.source.pk])

        self.source_to_private()
        self.assertPermissionLevel(
            url, self.SOURCE_EDIT, is_json=True, post_data={})
        self.source_to_public()
        self.assertPermissionLevel(
            url, self.SOURCE_EDIT, is_json=True, post_data={})

    def test_upload_button_requires_edit_perm(self):
        url = reverse('browse_images', args=[self.source.pk])

        # TODO: Make a similar method to assertPermissionLevel which takes
        # an arbitrary boolean-returning function and tests it on all possible
        # permission levels (not just Edit and View). Pass
        # button_is_present as the boolean function.

        def button_is_present():
            response = self.client.get(url, follow=True)
            response_soup = BeautifulSoup(response.content, 'html.parser')

            upload_button = response_soup.find(
                'button', id='new-rate-table-form-show-button')
            return bool(upload_button)

        self.client.force_login(self.user_editor)
        self.assertTrue(button_is_present())
        self.client.force_login(self.user_viewer)
        self.assertFalse(button_is_present())


class TableUploadTest(ClientTest):

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

    def upload_table(
            self, csv_rows, name="A name", description="A description",
            source=None):

        if source is None:
            source = self.source

        stream = StringIO()
        stream.writelines([f'{row}\n' for row in csv_rows])
        csv_file = ContentFile(stream.getvalue(), name='rates.csv')
        data = dict(
            name=name,
            description=description,
            csv_file=csv_file,
        )

        self.client.force_login(self.user)
        url = reverse(
            'calcification:rate_table_upload_ajax', args=[source.pk])
        return self.client.post(url, data=data, follow=True)

    def test_success(self):
        response = self.upload_table(
            [
                'Name,Mean,Lower bound,Upper bound',
                'A,3.0,2.0,4.0',
            ],
            "Source Indo-Pacific rates",
            "Description goes here",
        )

        # This table should be in the DB now
        table = CalcifyRateTable.objects.get(source=self.source)
        self.assertEqual(table.name, "Source Indo-Pacific rates")
        self.assertEqual(table.description, "Description goes here")
        self.assertDictEqual(
            table.rates_json,
            {str(self.labels.get(name='A').pk): dict(
                mean='3.0', lower_bound='2.0', upper_bound='4.0')})

        # Check response content
        self.assertStatusOK(response)
        response_json = response.json()
        self.assertHTMLEqual(
            response_json['tableDropdownHtml'],
            '<select id="id_rate_table_id" name="rate_table_id">'
            f'  <option value="{table.pk}">{table.name}</option>'
            f'  <option value="{self.default_indo_pacific.pk}">'
            f'    {self.default_indo_pacific.name}</option>'
            f'  <option value="{self.default_atlantic.pk}">'
            f'    {self.default_atlantic.name}</option>'
            '</select>')
        self.assertListEqual(
            grid_of_tables_html_to_tuples(
                response_json['gridOfTablesHtml']),
            [
                ("Source Indo-Pacific rates", "Description goes here",
                 reverse(
                     'calcification:rate_table_download', args=[table.pk]),
                 reverse(
                     'calcification:rate_table_delete_ajax', args=[table.pk])),
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

    def test_csv_file_required(self):
        data = dict(
            name="Name",
            description="Description",
            csv_file="",
        )
        url = reverse(
            'calcification:rate_table_upload_ajax', args=[self.source.pk])
        self.client.force_login(self.user)
        response = self.client.post(url, data=data, follow=True)

        self.assertEqual(
            response.json()['error'],
            "CSV file: Please select a CSV file.")

    def test_csv_wrong_file_format(self):
        """
        Do at least basic detection of non-CSV files.
        """
        data = dict(
            name="Name",
            description="Description",
            csv_file=sample_image_as_file('A.jpg'),
        )
        url = reverse(
            'calcification:rate_table_upload_ajax', args=[self.source.pk])
        self.client.force_login(self.user)
        response = self.client.post(url, data=data, follow=True)

        self.assertEqual(
            response.json()['error'],
            "CSV file: The selected file is not a CSV file.")

    def test_csv_columns_different_case(self):
        """
        The CSV column names can use different upper/lower case and still
        be matched to the expected column names.
        """
        self.upload_table([
            'name,meaN,LOWER BOUND,Upper bound',
            'A,3.0,2.0,4.0',
        ])

        table = CalcifyRateTable.objects.get(source=self.source)
        self.assertDictEqual(
            table.rates_json,
            {str(self.labels.get(name='A').pk): dict(
                mean='3.0', lower_bound='2.0', upper_bound='4.0')})

    def test_csv_missing_column(self):
        """Should return an error when missing a required column."""
        response = self.upload_table([
            'Name,Mean,Lower bound',
            'A,3.0,2.0',
        ])

        self.assertEqual(
            response.json()['error'],
            "CSV must have a column called Upper bound")

    def test_csv_unrecognized_label(self):
        response = self.upload_table([
            'Name,Mean,Lower bound,Upper bound',
            'F,3.0,2.0,4.0',
        ])

        self.assertEqual(
            response.json()['error'], "Label name not found: F")

    def test_csv_non_number_mean_rate(self):
        response = self.upload_table([
            'Name,Mean,Lower bound,Upper bound',
            'A,three,2.0,4.0',
        ])

        self.assertEqual(
            response.json()['error'],
            "mean value 'three'"
            " couldn't be converted to a number.")

    def test_csv_non_number_lower_bound(self):
        response = self.upload_table([
            'Name,Mean,Lower bound,Upper bound',
            'A,3.0,two,4.0',
        ])

        self.assertEqual(
            response.json()['error'],
            "lower_bound value 'two'"
            " couldn't be converted to a number.")

    def test_csv_non_number_upper_bound(self):
        response = self.upload_table([
            'Name,Mean,Lower bound,Upper bound',
            'A,3.0,2.0,four',
        ])

        self.assertEqual(
            response.json()['error'],
            "upper_bound value 'four'"
            " couldn't be converted to a number.")

    def test_name_required(self):
        response = self.upload_table(
            ['Name,Mean,Lower bound,Upper bound', 'A,3.0,2.0,4.0'],
            name="",
        )

        self.assertEqual(
            response.json()['error'], "Name: This field is required.")

    def test_name_too_long(self):
        response = self.upload_table(
            ['Name,Mean,Lower bound,Upper bound', 'A,3.0,2.0,4.0'],
            name="A"*81,
        )

        self.assertEqual(
            response.json()['error'],
            "Name: Ensure this value has at most 80 characters (it has 81).")

    def test_name_dupe_within_source(self):
        self.upload_table(
            ['Name,Mean,Lower bound,Upper bound', 'A,3.0,2.0,4.0'],
            name="A table",
        )
        response = self.upload_table(
            ['Name,Mean,Lower bound,Upper bound', 'A,3.0,2.0,4.0'],
            name="A table",
        )

        self.assertEqual(
            response.json()['error'],
            "Name: This source already has a rate table with the same name.")

    def test_name_same_as_other_source_table(self):
        self.upload_table(
            ['Name,Mean,Lower bound,Upper bound', 'A,3.0,2.0,4.0'],
            name="A table",
        )

        source2 = self.create_source(self.user)
        self.create_labelset(self.user, source2, self.labels)
        response = self.upload_table(
            ['Name,Mean,Lower bound,Upper bound', 'A,3.0,2.0,4.0'],
            name="A table",
            source=source2,
        )

        # Should be OK
        self.assertNotIn('error', response.json())
        table = CalcifyRateTable.objects.get(source=source2)
        self.assertEqual(table.name, "A table")

    def test_name_same_as_default_table(self):
        response = self.upload_table(
            ['Name,Mean,Lower bound,Upper bound', 'A,3.0,2.0,4.0'],
            name="Default Atlantic rates",
        )

        # Should be OK
        self.assertNotIn('error', response.json())
        table = CalcifyRateTable.objects.get(source=self.source)
        self.assertEqual(table.name, "Default Atlantic rates")

    def test_description_optional(self):
        self.upload_table(
            ['Name,Mean,Lower bound,Upper bound', 'A,3.0,2.0,4.0'],
            description="",
        )

        table = CalcifyRateTable.objects.get(source=self.source)
        self.assertEqual(table.description, "")

    def test_description_too_long(self):
        response = self.upload_table(
            ['Name,Mean,Lower bound,Upper bound', 'A,3.0,2.0,4.0'],
            description="A"*501,
        )

        self.assertEqual(
            response.json()['error'],
            "Description: Ensure this value has at most 500 characters"
            " (it has 501).")

    def test_already_have_5_tables(self):
        for i in range(5):
            self.upload_table(
                ['Name,Mean,Lower bound,Upper bound', 'A,3.0,2.0,4.0'],
                name=f"Table {i}")

        response = self.upload_table(
            ['Name,Mean,Lower bound,Upper bound', 'A,3.0,2.0,4.0'],
            name="Another table")

        self.assertEqual(
            response.json()['error'],
            "Up to 5 rate tables can be saved."
            " You must delete a table before saving a new one.")
