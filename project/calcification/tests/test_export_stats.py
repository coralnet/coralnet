from bs4 import BeautifulSoup
from django.urls import reverse

from export.tests.utils import BaseExportTest
from lib.tests.utils import BasePermissionTest, ClientTest
from .utils import (
    create_default_calcify_table, create_source_calcify_table,
    grid_of_tables_html_to_tuples)


class PermissionTest(BasePermissionTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, cls.labels)

        # Make the action form available on Browse Images
        cls.upload_image(cls.user, cls.source)

        cls.calcify_table = create_default_calcify_table('Atlantic', dict())

    def test_calcify_stats_export(self):
        data = dict(rate_table_id=self.calcify_table.pk)
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
        self.client.force_login(self.user)
        return self.client.post(
            reverse('calcification:stats_export', args=[self.source.pk]),
            data, follow=True)


class ExportTest(BaseCalcifyStatsExportTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user, name="Test source", simple_number_of_points=5)

        cls.labels = cls.create_labels(
            cls.user, ['A', 'B', 'C'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, cls.labels)
        cls.label_pks = {label.name: label.pk for label in cls.labels}

    def test_filename_and_content_type(self):
        calcify_table = create_default_calcify_table('Atlantic', {})
        response = self.export_calcify_stats(
            dict(rate_table_id=calcify_table.pk))

        # TODO: Also test for the correct date in the filename, perhaps
        # allowing for being 1 day off so the test is robust
        self.assertTrue(
            response['content-disposition'].startswith(
                'attachment;filename="Test source - Calcification rates - '),
            msg="Filename should have the source name as expected")
        self.assertTrue(
            response['content-disposition'].endswith('.csv"'))

        self.assertTrue(
            response['content-type'].startswith('text/csv'),
            msg="Content type should be CSV")

    def test_basic_contents(self):
        img1 = self.upload_image(
            self.user, self.source, dict(filename='1.jpg'))
        self.add_annotations(self.user, img1, {
            1: 'A', 2: 'B', 3: 'A', 4: 'B', 5: 'A'})

        calcify_table = create_default_calcify_table(
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
            'Image ID,Image name,Mean rate,Lower bound,Upper bound',
            # 4.0*0.6 + 1.0*0.4
            # 3.2*0.6 + 0.8*0.4
            # 4.8*0.6 + 1.3*0.4
            f'{img1.pk},1.jpg,2.800,2.240,3.400',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_zero_for_undefined_rate(self):
        """If a label has no rate defined for it, should assume a 0 rate."""
        img1 = self.upload_image(
            self.user, self.source, dict(filename='1.jpg'))
        self.add_annotations(self.user, img1, {
            1: 'A', 2: 'B', 3: 'A', 4: 'B', 5: 'A'})

        calcify_table = create_default_calcify_table(
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
            'Image ID,Image name,Mean rate,Lower bound,Upper bound',
            # 4.0*0.6
            # 3.2*0.6
            # 4.8*0.6
            f'{img1.pk},1.jpg,2.400,1.920,2.880',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_different_tables(self):
        """Rate table choice should be respected in the export."""
        img1 = self.upload_image(
            self.user, self.source, dict(filename='1.jpg'))
        self.add_annotations(self.user, img1, {
            1: 'A', 2: 'B', 3: 'C', 4: 'B', 5: 'C'})

        calcify_table_1 = create_default_calcify_table(
            'Atlantic',
            {
                self.label_pks['A']: dict(
                    mean=4.0, lower_bound=3.2, upper_bound=4.8),
                self.label_pks['B']: dict(
                    mean=1.0, lower_bound=0.8, upper_bound=1.3),
            },
        )
        calcify_table_2 = create_default_calcify_table(
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
            'Image ID,Image name,Mean rate,Lower bound,Upper bound',
            # 4.0*0.2 + 1.0*0.4
            # 3.2*0.2 + 0.8*0.4
            # 4.8*0.2 + 1.3*0.4
            f'{img1.pk},1.jpg,1.200,0.960,1.480',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

        # Table 2
        response = self.export_calcify_stats(
            dict(rate_table_id=calcify_table_2.pk))
        expected_lines = [
            'Image ID,Image name,Mean rate,Lower bound,Upper bound',
            # 1.5*0.4 + -3.0*0.4
            # 1.0*0.4 + -4.2*0.4
            # 2.0*0.4 + -2.2*0.4
            f'{img1.pk},1.jpg,-0.600,-1.280,-0.080',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_optional_columns_contributions(self):
        """Test the optional mean and bounds contributions columns."""
        img1 = self.upload_image(
            self.user, self.source, dict(filename='1.jpg'))
        self.add_annotations(self.user, img1, {
            1: 'A', 2: 'B', 3: 'A', 4: 'B', 5: 'A'})

        calcify_table = create_default_calcify_table(
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
            'Image ID,Image name,Mean rate,Lower bound,Upper bound,'
            'A M,B M,C M',
            # 4.0*0.6 + 1.0*0.4
            # 3.2*0.6 + 0.8*0.4
            # 4.8*0.6 + 1.3*0.4
            f'{img1.pk},1.jpg,2.800,2.240,3.400,'
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
            'Image ID,Image name,Mean rate,Lower bound,Upper bound,'
            'A LB,B LB,C LB,A UB,B UB,C UB',
            f'{img1.pk},1.jpg,2.800,2.240,3.400,'
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
            'Image ID,Image name,Mean rate,Lower bound,Upper bound,'
            'A M,B M,C M,A LB,B LB,C LB,A UB,B UB,C UB',
            f'{img1.pk},1.jpg,2.800,2.240,3.400,'
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

        calcify_table = create_default_calcify_table(
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
            'Image ID,Image name,Mean rate,Lower bound,Upper bound,A M,B M,C M,A LB,B LB,C LB,A UB,B UB,C UB',
            f'{img1.pk},1.jpg,4.000,3.200,4.800,'
            '4.000,0.000,0.000,3.200,0.000,0.000,4.800,0.000,0.000',
            # 4.0*0.6 + 1.0*0.4
            # 3.2*0.6 + 0.8*0.4
            # 4.8*0.6 + 1.3*0.4
            f'{img2.pk},2.jpg,2.800,2.240,3.400,'
            '2.400,0.400,0.000,1.920,0.320,0.000,2.880,0.520,0.000',
            # Averages
            'ALL IMAGES,ALL IMAGES,3.400,2.720,4.100,'
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

        calcify_table = create_default_calcify_table(
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
            'Image ID,Image name,Mean rate,Lower bound,Upper bound,'
            'A M,B M,C M,A LB,B LB,C LB,A UB,B UB,C UB',
            f'{img1.pk},1.jpg,4.000,3.200,4.800,'
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
            cls.user, simple_number_of_points=5)
        cls.labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, cls.labels)

        cls.calcify_table = create_default_calcify_table('Atlantic', dict())

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

        data = self.default_search_params.copy()
        data['aux1'] = 'X'
        data['rate_table_id'] = self.calcify_table.pk
        response = self.export_calcify_stats(data)
        self.assert_csv_image_set(response.content, [img1, img3])

    def test_image_empty_set(self):
        """Export for 0 images."""
        self.upload_image(
            self.user, self.source, dict(filename='1.jpg'))

        data = self.default_search_params.copy()
        data['image_name'] = '5.jpg'
        data['rate_table_id'] = self.calcify_table.pk
        response = self.export_calcify_stats(data)
        self.assert_csv_image_set(response.content, [])

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

        source2 = self.create_source(self.user, simple_number_of_points=5)
        self.create_labelset(self.user, source2, self.labels)
        self.upload_image(self.user, source2, dict(filename='2.jpg'))

        response = self.export_calcify_stats(
            dict(rate_table_id=self.calcify_table.pk))
        # Should have image 1, but not 2
        self.assert_csv_image_set(response.content, [img1])


class UnicodeTest(BaseCalcifyStatsExportTest):
    """Test that non-ASCII characters don't cause problems."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user, simple_number_of_points=5)

        # No Unicode to test on labels, since the export uses the label name,
        # which is ASCII only.
        labels = cls.create_labels(cls.user, ['A'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, labels)

        cls.calcify_table = create_default_calcify_table('Atlantic', dict())

    def test(self):
        img1 = self.upload_image(
            self.user, self.source, dict(filename='あ.jpg'))

        response = self.export_calcify_stats(
            dict(rate_table_id=self.calcify_table.pk))
        expected_lines = [
            'Image ID,Image name,Mean rate,Lower bound,Upper bound',
            f'{img1.pk},あ.jpg,0.000,0.000,0.000',
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

        default_t1 = create_default_calcify_table('Atlantic', dict())
        default_t2 = create_default_calcify_table('Indo-Pacific', dict())
        # Create these out of order to test alphabetical order.
        source_t2 = create_source_calcify_table(self.source, dict(), name="S2")
        source_t1 = create_source_calcify_table(self.source, dict(), name="S1")
        # Test tables from other sources.
        source_b = self.create_source(self.user)
        create_source_calcify_table(source_b, dict(), name="S3")

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
            f'  <option value="{default_t1.pk}">'
            f'    {default_t1.name}</option>'
            f'  <option value="{default_t2.pk}">'
            f'    {default_t2.name}</option>'
            '</select>',
            msg="Should have custom tables in order, then default tables"
                " in order, without having tables from other sources")

    def test_grid_of_tables_content(self):
        """Test the content of the grid of tables."""

        default_a = create_default_calcify_table('Atlantic', dict(), name="A")
        default_i = create_default_calcify_table(
            'Indo-Pacific', dict(), name="I")
        # Create these out of order to test alphabetical order.
        source_t2 = create_source_calcify_table(
            self.source, dict(), name="S2", description="A description")
        source_t1 = create_source_calcify_table(
            self.source, dict(), name="S1", description="A description")
        # Test tables from other sources.
        source_b = self.create_source(self.user)
        create_source_calcify_table(source_b, dict(), name="S3")

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
                ("A", "",
                 reverse(
                     'calcification:rate_table_download',
                     args=[default_a.pk]),
                 reverse(
                     'calcification:rate_table_download',
                     args=[default_a.pk])),
                ("I", "",
                 reverse(
                     'calcification:rate_table_download',
                     args=[default_i.pk]),
                 reverse(
                     'calcification:rate_table_download',
                     args=[default_i.pk])),
            ],
            msg="Should have custom tables in order, then default tables"
                " in order, without having tables from other sources",
        )