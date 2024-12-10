from bs4 import BeautifulSoup
from django.urls import reverse
import pyexcel

from export.tests.utils import BaseExportTest
from labels.models import LocalLabel
from lib.tests.utils import BasePermissionTest, ClientTest
from .utils import (
    create_global_calcify_table, create_source_calcify_table,
    grid_of_tables_html_to_tuples)


class PermissionTest(BasePermissionTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, cls.labels)

        # Make the action form available on Browse Images
        cls.upload_image(cls.user, cls.source)

        cls.calcify_table = create_global_calcify_table('Atlantic', dict())

    def test_calcify_stats_export(self):
        data = dict(
            rate_table_id=self.calcify_table.pk,
            label_display='code', export_format='csv')
        url = reverse('calcification:stats_export', args=[self.source.pk])

        self.source_to_private()
        self.assertPermissionLevel(
            url, self.SOURCE_VIEW, post_data=data, content_type='text/csv')
        self.source_to_public()
        self.assertPermissionLevel(
            url, self.SIGNED_IN, post_data=data, content_type='text/csv',
            deny_type=self.REQUIRE_LOGIN)

    def test_export_form_requires_login(self):
        url = reverse('browse_images', args=[self.source.pk])

        def form_is_present():
            response = self.client.get(url, follow=True)
            response_soup = BeautifulSoup(response.content, 'html.parser')

            export_form = response_soup.find(
                'form', id='export-calcify-rates-form')
            return bool(export_form)

        self.source_to_public()
        self.client.force_login(self.user_outsider)
        self.assertTrue(form_is_present())
        self.client.logout()
        self.assertFalse(form_is_present())


class BaseCalcifyStatsExportTest(BaseExportTest):
    """Subclasses must define self.client and self.source."""

    def export_calcify_stats(self, data):
        """POST the export view and return the response."""
        if 'label_display' not in data:
            data['label_display'] = 'code'
        if 'export_format' not in data:
            data['export_format'] = 'csv'

        self.client.force_login(self.user)
        return self.client.post(
            reverse('calcification:stats_export', args=[self.source.pk]),
            data, follow=True)


class FileTypeTest(BaseCalcifyStatsExportTest):
    """Test the Excel export option."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user,
            image_annotation_area=dict(min_x=0, max_x=100, min_y=0, max_y=100),
            default_point_generation_method=dict(type='simple', points=5))
        cls.labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, cls.labels)

        cls.img1 = cls.upload_image(
            cls.user, cls.source, dict(filename='1.jpg'))
        cls.img2 = cls.upload_image(
            cls.user, cls.source, dict(filename='2.jpg'))
        cls.img3 = cls.upload_image(
            cls.user, cls.source, dict(filename='3.jpg'))
        cls.add_annotations(cls.user, cls.img1, {
            1: 'A', 2: 'A', 3: 'A', 4: 'A', 5: 'A'})
        cls.add_annotations(cls.user, cls.img2, {
            1: 'A', 2: 'A', 3: 'A', 4: 'A', 5: 'A'})
        cls.add_annotations(cls.user, cls.img3, {
            1: 'A', 2: 'A', 3: 'A', 4: 'A', 5: 'A'})
        cls.img1.metadata.aux1 = 'X'
        cls.img1.metadata.save()
        cls.img2.metadata.aux1 = 'Y'
        cls.img2.metadata.save()
        cls.img3.metadata.aux1 = 'X'
        cls.img3.metadata.save()

    def test_csv(self):
        calcify_table = create_global_calcify_table('Atlantic', {})
        response = self.export_calcify_stats(
            dict(rate_table_id=calcify_table.pk))

        self.assertEqual(
            response['content-type'], 'text/csv',
            msg="Content type should be CSV")

        # Currently being lazy and not checking the date in the filename.
        self.assertTrue(
            response['content-disposition'].startswith(
                f'attachment;'
                f'filename="{self.source.name} - Calcification rates - '),
            msg="Filename should have the source name as expected")
        self.assertTrue(
            response['content-disposition'].endswith('.csv"'))

        # CSV contents are already covered by other tests, so no need to
        # re-test that here.

    def test_excel(self):
        calcify_table = create_global_calcify_table(
            'Atlantic', {}, name="Test table")

        data = self.default_search_params.copy()
        # Some, but not all, images
        data['aux1'] = 'X'
        data['export_format'] = 'excel'
        data['rate_table_id'] = calcify_table.pk
        response = self.export_calcify_stats(data)

        self.assertEqual(
            response['content-type'],
            'application/'
            'vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            msg="Content type should correspond to xlsx")

        # Currently being lazy and not checking the date in the filename.
        self.assertTrue(
            response['content-disposition'].startswith(
                f'attachment;'
                f'filename="{self.source.name} - Calcification rates - '),
            msg="Filename should have the source name as expected")
        self.assertTrue(
            response['content-disposition'].endswith('.xlsx"'))

        book = pyexcel.get_book(
            file_type='xlsx', file_content=response.content)

        # Check data sheet contents
        expected_lines = [
            'Image ID,Image name,Annotation status,Points,'
            'Mean,Lower bound,Upper bound',

            # Excel will trim trailing zeros
            f'{self.img1.pk},1.jpg,Confirmed,5,0,0,0',
            f'{self.img3.pk},3.jpg,Confirmed,5,0,0,0',
            f'ALL IMAGES,,,,0,0,0',
        ]
        self.assert_csv_content_equal(book["Data"].csv, expected_lines)

        # Check meta sheet contents
        actual_rows = book["Meta"].array
        self.assertEqual(6, len(actual_rows))
        self.assertEqual(
            ["Source name", self.source.name], actual_rows[0])
        self.assertEqual(
            ["Image search method",
             "Filtering by aux1; Sorting by name, ascending"],
            actual_rows[1])
        self.assertEqual(
            ["Images in export", 2], actual_rows[2])
        self.assertEqual(
            ["Images in source", 3], actual_rows[3])
        # Currently being lazy and not checking the actual date here.
        self.assertEqual(
            "Export date", actual_rows[4][0])
        self.assertEqual(
            ["Calcification table", "Test table"], actual_rows[5])

        # Check label rates sheet contents


class ExportTest(BaseCalcifyStatsExportTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user, name="Test source",
            default_point_generation_method=dict(type='simple', points=5))

        cls.labels = cls.create_labels(
            cls.user, ['A', 'B', 'C'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, cls.labels)
        cls.label_pks = {label.name: label.pk for label in cls.labels}

    def test_basic_contents(self):
        img1 = self.upload_image(
            self.user, self.source, dict(filename='1.jpg'))
        self.add_annotations(self.user, img1, {
            1: 'A', 2: 'B', 3: 'A', 4: 'B', 5: 'A'})

        calcify_table = create_global_calcify_table(
            'Atlantic',
            {
                self.label_pks['A']: dict(
                    mean=4.0, lower_bound=3.2, upper_bound=4.8),
                self.label_pks['B']: dict(
                    mean=1.0, lower_bound=0.8, upper_bound=1.3),
            },
        )

        response = self.export_calcify_stats(
            dict(rate_table_id=calcify_table.pk))

        # Column headers, image IDs/names, calculations, and decimal places
        # should be as expected; and should work with multiple images
        expected_lines = [
            'Image ID,Image name,Annotation status,Points,'
            'Mean,Lower bound,Upper bound',

            # 4.0*0.6 + 1.0*0.4
            # 3.2*0.6 + 0.8*0.4
            # 4.8*0.6 + 1.3*0.4
            f'{img1.pk},1.jpg,Confirmed,5,2.800,2.240,3.400',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_zero_for_undefined_rate(self):
        """If a label has no rate defined for it, should assume a 0 rate."""
        img1 = self.upload_image(
            self.user, self.source, dict(filename='1.jpg'))
        self.add_annotations(self.user, img1, {
            1: 'A', 2: 'B', 3: 'A', 4: 'B', 5: 'A'})

        calcify_table = create_global_calcify_table(
            'Atlantic',
            {
                self.label_pks['A']: dict(
                    mean=4.0, lower_bound=3.2, upper_bound=4.8),
                # Nothing for B
            },
        )

        response = self.export_calcify_stats(
            dict(rate_table_id=calcify_table.pk))

        expected_lines = [
            'Image ID,Image name,Annotation status,Points,'
            'Mean,Lower bound,Upper bound',

            # 4.0*0.6
            # 3.2*0.6
            # 4.8*0.6
            f'{img1.pk},1.jpg,Confirmed,5,2.400,1.920,2.880',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_different_tables(self):
        """Rate table choice should be respected in the export."""
        img1 = self.upload_image(
            self.user, self.source, dict(filename='1.jpg'))
        self.add_annotations(self.user, img1, {
            1: 'A', 2: 'B', 3: 'C', 4: 'B', 5: 'C'})

        calcify_table_1 = create_global_calcify_table(
            'Atlantic',
            {
                self.label_pks['A']: dict(
                    mean=4.0, lower_bound=3.2, upper_bound=4.8),
                self.label_pks['B']: dict(
                    mean=1.0, lower_bound=0.8, upper_bound=1.3),
            },
        )
        calcify_table_2 = create_global_calcify_table(
            'Indo-Pacific',
            {
                self.label_pks['B']: dict(
                    mean=1.5, lower_bound=1.0, upper_bound=2.0),
                self.label_pks['C']: dict(
                    mean=-3.0, lower_bound=-4.2, upper_bound=-2.2),
            },
        )

        # Table 1
        response = self.export_calcify_stats(
            dict(rate_table_id=calcify_table_1.pk))
        expected_lines = [
            'Image ID,Image name,Annotation status,Points,'
            'Mean,Lower bound,Upper bound',

            # 4.0*0.2 + 1.0*0.4
            # 3.2*0.2 + 0.8*0.4
            # 4.8*0.2 + 1.3*0.4
            f'{img1.pk},1.jpg,Confirmed,5,1.200,0.960,1.480',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

        # Table 2
        response = self.export_calcify_stats(
            dict(rate_table_id=calcify_table_2.pk))
        expected_lines = [
            'Image ID,Image name,Annotation status,Points,'
            'Mean,Lower bound,Upper bound',

            # 1.5*0.4 + -3.0*0.4
            # 1.0*0.4 + -4.2*0.4
            # 2.0*0.4 + -2.2*0.4
            f'{img1.pk},1.jpg,Confirmed,5,-0.600,-1.280,-0.080',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_optional_columns_contributions(self):
        """Test the optional mean and bounds contributions columns."""
        img1 = self.upload_image(
            self.user, self.source, dict(filename='1.jpg'))
        self.add_annotations(self.user, img1, {
            1: 'A', 2: 'B', 3: 'A', 4: 'B', 5: 'A'})

        calcify_table = create_global_calcify_table(
            'Atlantic',
            {
                self.label_pks['A']: dict(
                    mean=4.0, lower_bound=3.2, upper_bound=4.8),
                self.label_pks['B']: dict(
                    mean=1.0, lower_bound=0.8, upper_bound=1.3),
            },
        )

        # Mean only
        response = self.export_calcify_stats(
            dict(
                rate_table_id=calcify_table.pk,
                optional_columns='per_label_mean'))
        expected_lines = [
            'Image ID,Image name,Annotation status,Points,'
            'Mean,Lower bound,Upper bound,'
            'A M,B M,C M',

            # 4.0*0.6 + 1.0*0.4
            # 3.2*0.6 + 0.8*0.4
            # 4.8*0.6 + 1.3*0.4
            f'{img1.pk},1.jpg,Confirmed,5,2.800,2.240,3.400,'
            # 4.0*0.6
            # 1.0*0.4
            # 0
            '2.400,0.400,0.000',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

        # Bounds only
        response = self.export_calcify_stats(
            dict(
                rate_table_id=calcify_table.pk,
                optional_columns='per_label_bounds'))
        expected_lines = [
            'Image ID,Image name,Annotation status,Points,'
            'Mean,Lower bound,Upper bound,'
            'A LB,B LB,C LB,A UB,B UB,C UB',

            f'{img1.pk},1.jpg,Confirmed,5,2.800,2.240,3.400,'
            # 3.2*0.6
            # 0.8*0.4
            # 0
            # 4.8*0.6
            # 1.3*0.4
            # 0
            '1.920,0.320,0.000,2.880,0.520,0.000',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

        # Mean and bounds
        response = self.export_calcify_stats(
            dict(
                rate_table_id=calcify_table.pk,
                optional_columns=['per_label_mean', 'per_label_bounds']))
        expected_lines = [
            'Image ID,Image name,Annotation status,Points,'
            'Mean,Lower bound,Upper bound,'
            'A M,B M,C M,A LB,B LB,C LB,A UB,B UB,C UB',

            f'{img1.pk},1.jpg,Confirmed,5,2.800,2.240,3.400,'
            '2.400,0.400,0.000,1.920,0.320,0.000,2.880,0.520,0.000',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_multiple_images(self):
        """
        Test with multiple images, which makes the CSV include a summary row.
        """
        img1 = self.upload_image(
            self.user, self.source, dict(filename='1.jpg'))
        self.add_annotations(self.user, img1, {
            1: 'A', 2: 'A', 3: 'A', 4: 'A', 5: 'A'})

        img2 = self.upload_image(
            self.user, self.source, dict(filename='2.jpg'))
        self.add_annotations(self.user, img2, {
            1: 'A', 2: 'B', 3: 'A', 4: 'B', 5: 'A'})

        calcify_table = create_global_calcify_table(
            'Atlantic',
            {
                self.label_pks['A']: dict(
                    mean=4.0, lower_bound=3.2, upper_bound=4.8),
                self.label_pks['B']: dict(
                    mean=1.0, lower_bound=0.8, upper_bound=1.3),
            },
        )

        response = self.export_calcify_stats(
            dict(
                rate_table_id=calcify_table.pk,
                optional_columns=['per_label_mean', 'per_label_bounds']))

        # Column headers, image IDs/names, calculations, and decimal places
        # should be as expected; and should work with multiple images
        expected_lines = [
            'Image ID,Image name,Annotation status,Points,'
            'Mean,Lower bound,Upper bound,'
            'A M,B M,C M,A LB,B LB,C LB,A UB,B UB,C UB',

            f'{img1.pk},1.jpg,Confirmed,5,4.000,3.200,4.800,'
            '4.000,0.000,0.000,3.200,0.000,0.000,4.800,0.000,0.000',
            # 4.0*0.6 + 1.0*0.4
            # 3.2*0.6 + 0.8*0.4
            # 4.8*0.6 + 1.3*0.4

            f'{img2.pk},2.jpg,Confirmed,5,2.800,2.240,3.400,'
            '2.400,0.400,0.000,1.920,0.320,0.000,2.880,0.520,0.000',

            # Averages
            'ALL IMAGES,,,,3.400,2.720,4.100,'
            '3.200,0.200,0.000,2.560,0.160,0.000,3.840,0.260,0.000',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_no_negative_zero(self):
        """
        Should not show -0.000 for zero contributions on labels with
        negative rates.
        """
        img1 = self.upload_image(
            self.user, self.source, dict(filename='1.jpg'))
        self.add_annotations(self.user, img1, {
            1: 'A', 2: 'A', 3: 'A', 4: 'A', 5: 'A'})

        calcify_table = create_global_calcify_table(
            'Atlantic',
            {
                self.label_pks['A']: dict(
                    mean=4.0, lower_bound=3.2, upper_bound=4.8),
                self.label_pks['C']: dict(
                    mean=-3.0, lower_bound=-4.2, upper_bound=-2.2),
            },
        )

        # Mean only
        response = self.export_calcify_stats(
            dict(
                rate_table_id=calcify_table.pk,
                optional_columns=['per_label_mean', 'per_label_bounds']))
        expected_lines = [
            'Image ID,Image name,Annotation status,Points,'
            'Mean,Lower bound,Upper bound,'
            'A M,B M,C M,A LB,B LB,C LB,A UB,B UB,C UB',

            f'{img1.pk},1.jpg,Confirmed,5,4.000,3.200,4.800,'
            # Contributions from C in particular should be 0.000, not -0.000
            '4.000,0.000,0.000,3.200,0.000,0.000,4.800,0.000,0.000',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_nonexistent_table_id(self):
        """
        Nonexistent table ID should return to Browse with an error message at
        the top.
        """
        # No tables should have been created yet, so this ID should be
        # nonexistent.
        response = self.export_calcify_stats(
            dict(rate_table_id=1))

        # Display an error in HTML instead of serving CSV.
        self.assertTrue(response['content-type'].startswith('text/html'))
        # It's not the most intuitive error message, but it shouldn't be a
        # common error case either (e.g. people editing params with
        # Inspect Element).
        self.assertContains(
            response,
            "Label rates to use: Select a valid choice."
            " 1 is not one of the available choices.")

    def test_other_source_table_id(self):
        """
        Table ID from another source should return to Browse with an error
        message.
        """
        source2 = self.create_source(self.user)
        table = create_source_calcify_table(source2, {})

        response = self.export_calcify_stats(
            dict(rate_table_id=table.pk))

        self.assertTrue(response['content-type'].startswith('text/html'))
        self.assertContains(
            response,
            "Label rates to use: Select a valid choice."
            f" {table.pk} is not one of the available choices.")


class ImageSetTest(BaseCalcifyStatsExportTest):
    """
    Test calcification stats export to CSV for different kinds of image
    subsets.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user,
            default_point_generation_method=dict(type='simple', points=5))
        cls.labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, cls.labels)

        cls.calcify_table = create_global_calcify_table('Atlantic', dict())

    def assert_csv_image_set(self, actual_csv_content, expected_images):
        # Convert from bytes to Unicode if necessary.
        if isinstance(actual_csv_content, bytes):
            actual_csv_content = actual_csv_content.decode()

        # The Python csv module uses \r\n by default (as part of the Excel
        # dialect). Due to the way we compare line by line, splitting on
        # \n would mess up the comparison, so we use split() instead of
        # splitlines().
        actual_rows = actual_csv_content.split('\r\n')
        # Since we're not using splitlines(), we have to deal with ending
        # newlines manually.
        if actual_rows[-1] == "":
            actual_rows.pop()

        # expected_images should be an iterable of Image objects. We'll check
        # that expected_images are exactly the images represented in the CSV,
        # minus the header row and any summary row.
        if len(expected_images) > 1:
            # Expecting summary row
            actual_image_rows = actual_rows[1:-1]
        else:
            # Not expecting summary row
            actual_image_rows = actual_rows[1:]
        self.assertEqual(
            len(expected_images), len(actual_image_rows),
            msg="Number of rows in the CSV should be as expected")

        for row, image in zip(actual_image_rows, expected_images):
            self.assertTrue(
                row.startswith(f'{image.pk},{image.metadata.name},'),
                msg="CSV row should have the expected image ID and name")

    def test_all_images_single(self):
        """Export for 1 out of 1 images."""
        img1 = self.upload_image(
            self.user, self.source, dict(filename='1.jpg'))
        self.add_annotations(self.user, img1, {
            1: 'A', 2: 'A', 3: 'A', 4: 'A', 5: 'A'})

        response = self.export_calcify_stats(
            dict(rate_table_id=self.calcify_table.pk))
        self.assert_csv_image_set(response.content, [img1])

    def test_all_images_multiple(self):
        """Export for n out of n images."""
        img1 = self.upload_image(
            self.user, self.source, dict(filename='1.jpg'))
        img2 = self.upload_image(
            self.user, self.source, dict(filename='2.jpg'))
        img3 = self.upload_image(
            self.user, self.source, dict(filename='3.jpg'))
        self.add_annotations(self.user, img1, {
            1: 'A', 2: 'A', 3: 'A', 4: 'A', 5: 'A'})
        self.add_annotations(self.user, img2, {
            1: 'A', 2: 'A', 3: 'A', 4: 'A', 5: 'A'})
        self.add_annotations(self.user, img3, {
            1: 'A', 2: 'A', 3: 'A', 4: 'A', 5: 'A'})

        response = self.export_calcify_stats(
            dict(rate_table_id=self.calcify_table.pk))
        self.assert_csv_image_set(response.content, [img1, img2, img3])

    def test_image_subset_by_metadata(self):
        """Export for some, but not all, images."""
        img1 = self.upload_image(
            self.user, self.source, dict(filename='1.jpg'))
        img2 = self.upload_image(
            self.user, self.source, dict(filename='2.jpg'))
        img3 = self.upload_image(
            self.user, self.source, dict(filename='3.jpg'))
        img1.metadata.aux1 = 'X'
        img1.metadata.save()
        img2.metadata.aux1 = 'Y'
        img2.metadata.save()
        img3.metadata.aux1 = 'X'
        img3.metadata.save()
        self.add_annotations(self.user, img1, {
            1: 'A', 2: 'A', 3: 'A', 4: 'A', 5: 'A'})
        self.add_annotations(self.user, img2, {
            1: 'A', 2: 'A', 3: 'A', 4: 'A', 5: 'A'})
        self.add_annotations(self.user, img3, {
            1: 'A', 2: 'A', 3: 'A', 4: 'A', 5: 'A'})

        data = self.default_search_params.copy()
        data['aux1'] = 'X'
        data['rate_table_id'] = self.calcify_table.pk
        response = self.export_calcify_stats(data)
        self.assert_csv_image_set(response.content, [img1, img3])

    def test_image_empty_set(self):
        """Export for 0 images."""
        img1 = self.upload_image(
            self.user, self.source, dict(filename='1.jpg'))
        self.add_annotations(self.user, img1, {
            1: 'A', 2: 'A', 3: 'A', 4: 'A', 5: 'A'})

        data = self.default_search_params.copy()
        data['image_name'] = '5.jpg'
        data['rate_table_id'] = self.calcify_table.pk
        response = self.export_calcify_stats(data)
        self.assert_csv_image_set(response.content, [])

    def test_exclude_unannotated_images(self):
        """
        CSV should exclude unannotated images, regardless of whether the
        search filters include such images.
        """
        img1 = self.upload_image(
            self.user, self.source, dict(filename='1.jpg'))
        img2 = self.upload_image(
            self.user, self.source, dict(filename='2.jpg'))
        self.upload_image(
            self.user, self.source, dict(filename='3.jpg'))
        # 1st image confirmed
        self.add_annotations(self.user, img1, {
            1: 'A', 2: 'B', 3: 'A', 4: 'B', 5: 'A'})
        # 2nd image unconfirmed
        robot = self.create_robot(self.source)
        self.add_robot_annotations(robot, img2, {
            1: 'A', 2: 'B', 3: 'B', 4: 'B', 5: 'B'})
        # 3rd image unannotated

        response = self.export_calcify_stats(
            dict(rate_table_id=self.calcify_table.pk))
        self.assert_csv_image_set(response.content, [img1, img2])

    def test_invalid_image_set_params(self):
        self.upload_image(self.user, self.source)

        data = self.default_search_params.copy()
        data['photo_date_0'] = 'abc'
        data['rate_table_id'] = self.calcify_table.pk
        response = self.export_calcify_stats(data)

        # Display an error in HTML instead of serving CSV.
        self.assertTrue(response['content-type'].startswith('text/html'))
        self.assertContains(response, "Image-search parameters were invalid.")

    def test_dont_get_other_sources_images(self):
        """Don't export for other sources' images."""
        img1 = self.upload_image(
            self.user, self.source, dict(filename='1.jpg'))
        self.add_annotations(self.user, img1, {
            1: 'A', 2: 'A', 3: 'A', 4: 'A', 5: 'A'})

        source2 = self.create_source(
            self.user,
            default_point_generation_method=dict(type='simple', points=5))
        self.create_labelset(self.user, source2, self.labels)
        img2 = self.upload_image(self.user, source2, dict(filename='2.jpg'))
        self.add_annotations(self.user, img2, {
            1: 'A', 2: 'A', 3: 'A', 4: 'A', 5: 'A'})

        response = self.export_calcify_stats(
            dict(rate_table_id=self.calcify_table.pk))
        # Should have image 1, but not 2
        self.assert_csv_image_set(response.content, [img1])


class LabelColumnsTest(BaseCalcifyStatsExportTest):
    """Test naming and ordering of the per-label CSV columns."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user,
            default_point_generation_method=dict(type='simple', points=5))
        # To test ordering by group and then name/code, we'll stagger the
        # alphabetical ordering between two label groups.
        labels_a = cls.create_labels(cls.user, ['A1', 'B1', 'C1'], 'Group1')
        labels_b = cls.create_labels(cls.user, ['A2', 'B2'], 'Group2')
        cls.create_labelset(cls.user, cls.source, labels_a | labels_b)

        # Custom codes; ordering by these codes gives a different order from
        # ordering by name or default code. Again, alpha order is staggered
        # between groups.
        local_a = LocalLabel.objects.get(
            labelset=cls.source.labelset, code='A1')
        local_a.code = '21'
        local_a.save()
        local_b = LocalLabel.objects.get(
            labelset=cls.source.labelset, code='B1')
        local_b.code = '31'
        local_b.save()
        local_c = LocalLabel.objects.get(
            labelset=cls.source.labelset, code='C1')
        local_c.code = '11'
        local_c.save()

        local_d = LocalLabel.objects.get(
            labelset=cls.source.labelset, code='A2')
        local_d.code = '22'
        local_d.save()
        local_e = LocalLabel.objects.get(
            labelset=cls.source.labelset, code='B2')
        local_e.code = '12'
        local_e.save()

        cls.calcify_table = create_global_calcify_table('Atlantic', dict())

    def test_order_by_group_and_code(self):
        img1 = self.upload_image(
            self.user, self.source, dict(filename='1.jpg'))
        self.add_annotations(self.user, img1, {
            1: '21', 2: '31', 3: '31', 4: '22', 5: '12'})

        response = self.export_calcify_stats(
            dict(
                rate_table_id=self.calcify_table.pk,
                optional_columns=['per_label_mean', 'per_label_bounds']))

        # Columns should have LocalLabel short codes
        expected_lines = [
            'Image ID,Image name,Annotation status,Points,'
            'Mean,Lower bound,Upper bound,'
            '11 M,21 M,31 M,12 M,22 M,'
            '11 LB,21 LB,31 LB,12 LB,22 LB,11 UB,21 UB,31 UB,12 UB,22 UB',

            f'{img1.pk},1.jpg,Confirmed,5,'
            '0.000,0.000,0.000,'
            '0.000,0.000,0.000,0.000,0.000,'
            '0.000,0.000,0.000,0.000,0.000,0.000,0.000,0.000,0.000,0.000',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_order_by_group_and_name(self):
        img1 = self.upload_image(
            self.user, self.source, dict(filename='1.jpg'))
        self.add_annotations(self.user, img1, {
            1: '21', 2: '31', 3: '31', 4: '22', 5: '12'})

        response = self.export_calcify_stats(
            dict(
                rate_table_id=self.calcify_table.pk,
                optional_columns=['per_label_mean', 'per_label_bounds'],
                label_display='name'))

        # Columns should have global label names
        expected_lines = [
            'Image ID,Image name,Annotation status,Points,'
            'Mean,Lower bound,Upper bound,'
            'A1 M,B1 M,C1 M,A2 M,B2 M,'
            'A1 LB,B1 LB,C1 LB,A2 LB,B2 LB,A1 UB,B1 UB,C1 UB,A2 UB,B2 UB',

            f'{img1.pk},1.jpg,Confirmed,5,'
            '0.000,0.000,0.000,'
            '0.000,0.000,0.000,0.000,0.000,'
            '0.000,0.000,0.000,0.000,0.000,0.000,0.000,0.000,0.000,0.000',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)


class UnicodeTest(BaseCalcifyStatsExportTest):
    """Test that non-ASCII characters don't cause problems."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user,
            default_point_generation_method=dict(type='simple', points=5))

        labels = cls.create_labels(cls.user, ['A'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, labels)
        # Unicode custom label code
        local_label = cls.source.labelset.locallabel_set.get(code='A')
        local_label.code = 'い'
        local_label.save()

        cls.calcify_table = create_global_calcify_table('Atlantic', dict())

    def test(self):
        img1 = self.upload_image(
            self.user, self.source, dict(filename='あ.jpg'))
        self.add_annotations(self.user, img1, {
            1: 'い', 2: 'い', 3: 'い', 4: 'い', 5: 'い'})

        response = self.export_calcify_stats(
            dict(
                rate_table_id=self.calcify_table.pk,
                optional_columns='per_label_mean'))
        expected_lines = [
            'Image ID,Image name,Annotation status,Points,'
            'Mean,Lower bound,Upper bound,'
            'い M',

            f'{img1.pk},あ.jpg,Confirmed,5,0.000,0.000,0.000,0.000',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)


class BrowseFormsTest(ClientTest):
    """
    Test how the calcification related forms are rendered on Browse.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)

        # Make the action form available on Browse Images
        cls.upload_image(cls.user, cls.source)

        group1_labels = cls.create_labels(
            cls.user, ['A', 'B', 'C', 'D', 'E', 'F'], 'Group1')
        cls.create_labels(cls.user, ['G', 'H'], 'Group2')

        # Create a labelset with only a subset of the labels (6 of 8)
        cls.create_labelset(cls.user, cls.source, group1_labels)

    def test_optional_columns_help_text(self):
        """
        Test the help text on the extra-columns options.
        The help text should depend on how many labels are in the labelset.
        """
        url = reverse('browse_images', args=[self.source.pk])
        self.client.force_login(self.user)
        response = self.client.get(url)

        response_soup = BeautifulSoup(response.content, 'html.parser')
        export_form = response_soup.find(
            'form', id='export-calcify-rates-form')

        option_1 = export_form.select('label[for="id_optional_columns_0"]')[0]
        self.assertEqual(
            option_1.text.strip(),
            "Per-label contributions to mean rate (adds 6 columns)")
        option_2 = export_form.select('label[for="id_optional_columns_1"]')[0]
        self.assertEqual(
            option_2.text.strip(),
            "Per-label contributions to confidence bounds (adds 12 columns)")

    def test_rate_table_choices(self):
        """Test the dropdown of rate table choices in the export form."""

        # These should be listed latest first, not alphabetically by name.
        global_t3 = create_global_calcify_table('Atlantic', dict(), name="A")
        global_t2 = create_global_calcify_table(
            'Indo-Pacific', dict(), name="I")
        global_t1 = create_global_calcify_table('Atlantic', dict(), name="B")
        # These should be listed alphabetically by name, not by date.
        source_t2 = create_source_calcify_table(
            self.source, dict(), name="S2")
        source_t1 = create_source_calcify_table(
            self.source, dict(), name="S1")
        source_t3 = create_source_calcify_table(
            self.source, dict(), name="S3")
        # Other sources' tables shouldn't be listed.
        other_t = self.create_source(self.user)
        create_source_calcify_table(other_t, dict(), name="S4")

        url = reverse('browse_images', args=[self.source.pk])
        self.client.force_login(self.user)
        response = self.client.get(url)

        response_soup = BeautifulSoup(response.content, 'html.parser')
        tables_dropdown = response_soup.find('select', id='id_rate_table_id')

        self.assertHTMLEqual(
            str(tables_dropdown),
            '<select id="id_rate_table_id" name="rate_table_id">'
            f'  <option value="{source_t1.pk}">S1</option>'
            f'  <option value="{source_t2.pk}">S2</option>'
            f'  <option value="{source_t3.pk}">S3</option>'
            f'  <option value="{global_t1.pk}">'
            f'    {global_t1.name}</option>'
            f'  <option value="{global_t2.pk}">'
            f'    {global_t2.name}</option>'
            f'  <option value="{global_t3.pk}">'
            f'    {global_t3.name}</option>'
            '</select>',
            msg="Should have custom tables in order, then default tables"
                " in order, without having tables from other sources")

    def test_grid_of_tables_content(self):
        """Test the content of the grid of tables."""

        # These should be listed latest first, not alphabetically by name.
        global_t3 = create_global_calcify_table('Atlantic', dict(), name="A")
        global_t2 = create_global_calcify_table(
            'Indo-Pacific', dict(), name="I")
        global_t1 = create_global_calcify_table('Atlantic', dict(), name="B")
        # These should be listed alphabetically by name, not by date.
        source_t2 = create_source_calcify_table(
            self.source, dict(), name="S2", description="A description")
        source_t1 = create_source_calcify_table(
            self.source, dict(), name="S1", description="A description")
        source_t3 = create_source_calcify_table(
            self.source, dict(), name="S3", description="A description")
        # Other sources' tables shouldn't be listed.
        other_t = self.create_source(self.user)
        create_source_calcify_table(other_t, dict(), name="S4")

        url = reverse('browse_images', args=[self.source.pk])
        self.client.force_login(self.user)
        response = self.client.get(url)

        response_soup = BeautifulSoup(response.content, 'html.parser')
        grid_of_tables_soup = response_soup.find(
            'table', id='table-of-calcify-tables')

        self.assertListEqual(
            grid_of_tables_html_to_tuples(
                str(grid_of_tables_soup)),
            [
                ("S1", "A description",
                 reverse(
                     'calcification:rate_table_download', args=[source_t1.pk]),
                 reverse(
                     'calcification:rate_table_delete_ajax',
                     args=[source_t1.pk])),
                ("S2", "A description",
                 reverse(
                     'calcification:rate_table_download', args=[source_t2.pk]),
                 reverse(
                     'calcification:rate_table_delete_ajax',
                     args=[source_t2.pk])),
                ("S3", "A description",
                 reverse(
                     'calcification:rate_table_download', args=[source_t3.pk]),
                 reverse(
                     'calcification:rate_table_delete_ajax',
                     args=[source_t3.pk])),
                ("B", "",
                 reverse(
                     'calcification:rate_table_download',
                     args=[global_t1.pk]),
                 reverse(
                     'calcification:rate_table_download',
                     args=[global_t1.pk])),
                ("I", "",
                 reverse(
                     'calcification:rate_table_download',
                     args=[global_t2.pk]),
                 reverse(
                     'calcification:rate_table_download',
                     args=[global_t2.pk])),
                ("A", "",
                 reverse(
                     'calcification:rate_table_download',
                     args=[global_t3.pk]),
                 reverse(
                     'calcification:rate_table_download',
                     args=[global_t3.pk])),
            ],
            msg="Should have custom tables in order, then default tables"
                " in order, without having tables from other sources",
        )


class PerformanceTest(BaseCalcifyStatsExportTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user,
            default_point_generation_method=dict(type='simple', points=20))
        cls.labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, cls.labels)

    def test_num_queries(self):
        for i in range(15):
            img = self.upload_image(
                self.user, self.source, dict(filename=f'{i}.png'))
            self.add_annotations(
                self.user, img, {p: 'A' for p in range(1, 20+1)})

        calcify_table = create_global_calcify_table(
            'Atlantic',
            {
                self.labels.get(name='A').pk: dict(
                    mean=4.0, lower_bound=3.2, upper_bound=4.8),
                self.labels.get(name='B').pk: dict(
                    mean=1.0, lower_bound=0.8, upper_bound=1.3),
            },
        )

        url = reverse('calcification:stats_export', args=[self.source.pk])
        data = dict(
            rate_table_id=calcify_table.pk,
            label_display='code', export_format='csv')
        self.client.force_login(self.user)

        # We just want the number of queries to be reasonably close to 15
        # (image count), and definitely less than 300 (annotation count),
        # but assertNumQueries only asserts on an exact number of queries.
        with self.assertNumQueries(30):
            response = self.client.post(url, data)
        self.assertStatusOK(response)
        self.assertEqual(response['content-type'], 'text/csv')
