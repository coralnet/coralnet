from django.urls import reverse

from export.tests.utils import BaseExportTest
from lib.tests.utils import BasePermissionTest
from .utils import create_global_calcify_table, create_source_calcify_table


class PermissionTest(BasePermissionTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, cls.labels)

    def test_default_table_download(self):
        table = create_global_calcify_table('Atlantic', dict())
        url = reverse(
            'calcification:rate_table_download', args=[table.pk])

        self.assertPermissionLevel(
            url, self.SIGNED_OUT, content_type='text/csv')

    def test_source_table_download(self):
        table = create_source_calcify_table(self.source, dict())
        url = reverse(
            'calcification:rate_table_download', args=[table.pk])

        self.source_to_private()
        self.assertPermissionLevel(
            url, self.SOURCE_VIEW, content_type='text/csv')
        self.source_to_public()
        self.assertPermissionLevel(
            url, self.SIGNED_OUT, content_type='text/csv')

    def test_default_table_download_with_source_param(self):
        table = create_global_calcify_table('Atlantic', dict())
        url = self.make_url_with_params(
            reverse('calcification:rate_table_download', args=[table.pk]),
            dict(source_id=self.source.pk))

        self.source_to_private()
        self.assertPermissionLevel(
            url, self.SOURCE_VIEW, content_type='text/csv')
        self.source_to_public()
        self.assertPermissionLevel(
            url, self.SIGNED_OUT, content_type='text/csv')


class RateTableDownloadTest(BaseExportTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.labels = cls.create_labels(cls.user, ['A', 'B', 'C'], 'GroupA')

        cls.source = cls.create_source(cls.user)
        cls.create_labelset(
            cls.user, cls.source, cls.labels.filter(name__in=['B', 'C']))

    def test_default_table(self):
        """Download a default rate table."""
        table = create_global_calcify_table(
            'Atlantic',
            {
                str(self.labels.get(name='A').pk): dict(
                    mean='2.0', lower_bound='1.0', upper_bound='3.0'),
                str(self.labels.get(name='B').pk): dict(
                    mean='-2.0', lower_bound='-3.0', upper_bound='-1.0'),
            },
            name="Table Name",
        )

        response = self.client.get(
            reverse('calcification:rate_table_download', args=[table.pk]))

        expected_lines = [
            'Name,Mean,Lower bound,Upper bound',
            'A,2.0,1.0,3.0',
            'B,-2.0,-3.0,-1.0',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

        self.assertEqual(
            response.headers['content-disposition'],
            'attachment;filename="Table Name.csv"',
            msg="CSV filename should be as expected")

    def test_source_table(self):
        """Download a table belonging to a source."""
        table = create_source_calcify_table(
            self.source,
            {
                str(self.labels.get(name='B').pk): dict(
                    mean='2.0', lower_bound='1.0', upper_bound='3.0'),
                str(self.labels.get(name='C').pk): dict(
                    mean='-2.0', lower_bound='-3.0', upper_bound='-1.0'),
            },
        )

        response = self.client.get(
            reverse('calcification:rate_table_download', args=[table.pk]))

        expected_lines = [
            'Name,Mean,Lower bound,Upper bound',
            'B,2.0,1.0,3.0',
            'C,-2.0,-3.0,-1.0',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_default_table_filtered_to_source_labelset(self):
        """
        Download a default table while specifying a source's labelset to
        filter the entries on.
        """
        table = create_global_calcify_table(
            'Atlantic',
            {
                str(self.labels.get(name='A').pk): dict(
                    mean='2.0', lower_bound='1.0', upper_bound='3.0'),
                str(self.labels.get(name='B').pk): dict(
                    mean='-2.0', lower_bound='-3.0', upper_bound='-1.0'),
            },
            name="Table Name",
        )

        response = self.client.get(
            reverse('calcification:rate_table_download', args=[table.pk]),
            data=dict(source_id=self.source.pk),
        )

        expected_lines = [
            'Name,Mean,Lower bound,Upper bound',
            # A isn't in the labelset
            # B is in the labelset and in the table
            'B,-2.0,-3.0,-1.0',
            # C isn't in the table
            'C,0.0,0.0,0.0',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_table_name_with_non_filename_chars(self):
        table = create_global_calcify_table(
            'Atlantic', {}, name="<Table/Name?>")

        response = self.client.get(
            reverse('calcification:rate_table_download', args=[table.pk]))

        self.assertEqual(
            response.headers['content-disposition'],
            'attachment;filename="_Table_Name__.csv"',
            msg="CSV filename should replace expected chars with underscores")
