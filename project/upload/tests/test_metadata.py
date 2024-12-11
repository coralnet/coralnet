import csv
import datetime
from io import StringIO

from django.core.files.base import ContentFile
from django.urls import reverse

from images.models import Image
from lib.tests.utils import BasePermissionTest, ClientTest


class PermissionTest(BasePermissionTest):

    def test_metadata(self):
        url = reverse('upload_metadata', args=[self.source.pk])
        template = 'upload/upload_metadata.html'

        self.source_to_private()
        self.assertPermissionLevel(url, self.SOURCE_EDIT, template=template)
        self.source_to_public()
        self.assertPermissionLevel(url, self.SOURCE_EDIT, template=template)

    def test_metadata_preview_ajax(self):
        url = reverse('upload_metadata_preview_ajax', args=[self.source.pk])

        self.source_to_private()
        self.assertPermissionLevel(
            url, self.SOURCE_EDIT, is_json=True, post_data={})
        self.source_to_public()
        self.assertPermissionLevel(
            url, self.SOURCE_EDIT, is_json=True, post_data={})

    def test_metadata_ajax(self):
        url = reverse('upload_metadata_ajax', args=[self.source.pk])

        self.source_to_private()
        self.assertPermissionLevel(
            url, self.SOURCE_EDIT, is_json=True, post_data={})
        self.source_to_public()
        self.assertPermissionLevel(
            url, self.SOURCE_EDIT, is_json=True, post_data={})


class UploadMetadataTest(ClientTest):
    """
    Metadata upload and preview.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)

        cls.source.key1 = 'Site'
        cls.source.key2 = 'Habitat'
        cls.source.key3 = 'Transect'
        cls.source.save()

        cls.img1 = cls.upload_image(
            cls.user, cls.source, image_options=dict(filename='1.png'))
        cls.img2 = cls.upload_image(
            cls.user, cls.source, image_options=dict(filename='2.png'))

        cls.standard_column_order = [
            'Name', 'Date', 'Site', 'Habitat', 'Transect', 'Aux4', 'Aux5',
            'Height (cm)', 'Latitude', 'Longitude', 'Depth',
            'Camera', 'Photographer', 'Water quality',
            'Strobes', 'Framing gear used', 'White balance card', 'Comments',
        ]

    def preview(self, csv_file):
        return self.client.post(
            reverse('upload_metadata_preview_ajax', args=[self.source.pk]),
            {'csv_file': csv_file},
        )

    def upload(self):
        return self.client.post(
            reverse('upload_metadata_ajax', args=[self.source.pk]),
        )

    def test_starting_from_blank_metadata(self):
        """
        Everything starts blank and has nothing to be replaced.
        When editing, we'll set some fields while leaving others blank.
        """
        self.client.force_login(self.user)

        stream = StringIO()
        writer = csv.DictWriter(stream, self.standard_column_order)
        writer.writeheader()
        writer.writerow({
            'Name': '1.png',
            'Date': '2016-07-18',
            'Site': 'SiteA',
            'Habitat': 'Fringing Reef',
            'Transect': '2-4',
            'Aux4': 'Q5',
            'Aux5': '28',
            'Height (cm)': '50',
            'Latitude': '20.18',
            'Longitude': '-59.64',
            'Depth': '30m',
            'Camera': 'Canon',
            'Photographer': 'Bob Doe',
            'Water quality': 'Mostly clear',
            'Strobes': '2x blue',
            'Framing gear used': 'FG-16',
            'White balance card': 'WB-03',
            'Comments': 'A bit off to the left from the transect line.',
        })
        writer.writerow({
            'Name': '2.png',
            'Date': '',
            'Site': 'SiteB',
            'Habitat': '10m out',
            'Transect': '',
            'Aux4': '',
            'Aux5': '',
            'Height (cm)': '50',
            'Latitude': '',
            'Longitude': '',
            'Depth': '',
            'Camera': 'Canon',
            'Photographer': '',
            'Water quality': '',
            'Strobes': '',
            'Framing gear used': 'FG-15',
            'White balance card': '',
            'Comments': '',
        })

        f = ContentFile(stream.getvalue(), name='A.csv')
        preview_response = self.preview(f)
        upload_response = self.upload()

        self.assertDictEqual(
            preview_response.json(),
            dict(
                success=True,
                previewTable=[
                    self.standard_column_order,
                    ['1.png', '2016-07-18', 'SiteA', 'Fringing Reef', '2-4',
                     'Q5', '28', '50', '20.18', '-59.64', '30m',
                     'Canon', 'Bob Doe', 'Mostly clear', '2x blue', 'FG-16',
                     'WB-03', 'A bit off to the left from the transect line.'],
                    ['2.png', '', 'SiteB', '10m out', '', '', '', '50',
                     '', '', '', 'Canon', '', '', '', 'FG-15', '', ''],
                ],
                previewDetails=dict(
                    numImages=2,
                    numFieldsReplaced=0,
                ),
            ),
        )

        self.assertDictEqual(upload_response.json(), dict(success=True))

        meta1 = Image.objects.get(pk=self.img1.pk).metadata
        self.assertEqual(meta1.name, '1.png')
        self.assertEqual(meta1.photo_date, datetime.date(2016, 7, 18))
        self.assertEqual(meta1.aux1, 'SiteA')
        self.assertEqual(meta1.aux2, 'Fringing Reef')
        self.assertEqual(meta1.aux3, '2-4')
        self.assertEqual(meta1.aux4, 'Q5')
        self.assertEqual(meta1.aux5, '28')
        self.assertEqual(meta1.height_in_cm, 50)
        self.assertEqual(meta1.latitude, '20.18')
        self.assertEqual(meta1.longitude, '-59.64')
        self.assertEqual(meta1.depth, '30m')
        self.assertEqual(meta1.camera, 'Canon')
        self.assertEqual(meta1.photographer, 'Bob Doe')
        self.assertEqual(meta1.water_quality, 'Mostly clear')
        self.assertEqual(meta1.strobes, '2x blue')
        self.assertEqual(meta1.framing, 'FG-16')
        self.assertEqual(meta1.balance, 'WB-03')
        self.assertEqual(
            meta1.comments, 'A bit off to the left from the transect line.')

        meta2 = Image.objects.get(pk=self.img2.pk).metadata
        self.assertEqual(meta2.name, '2.png')
        self.assertEqual(meta2.photo_date, None)
        self.assertEqual(meta2.aux1, 'SiteB')
        self.assertEqual(meta2.aux2, '10m out')
        self.assertEqual(meta2.aux3, '')
        self.assertEqual(meta2.aux4, '')
        self.assertEqual(meta2.aux5, '')
        self.assertEqual(meta2.height_in_cm, 50)
        self.assertEqual(meta2.latitude, '')
        self.assertEqual(meta2.longitude, '')
        self.assertEqual(meta2.depth, '')
        self.assertEqual(meta2.camera, 'Canon')
        self.assertEqual(meta2.photographer, '')
        self.assertEqual(meta2.water_quality, '')
        self.assertEqual(meta2.strobes, '')
        self.assertEqual(meta2.framing, 'FG-15')
        self.assertEqual(meta2.balance, '')
        self.assertEqual(meta2.comments, '')

    def test_some_same_metadata(self):
        """
        Some fields start out with non-blank values and
        the metadata specifies the same values for those fields.
        """
        self.client.force_login(self.user)

        meta1 = self.img1.metadata
        meta1.photo_date = datetime.date(2016, 7, 18)
        meta1.aux1 = 'SiteA'
        meta1.camera = 'Canon'
        meta1.save()

        stream = StringIO()
        writer = csv.DictWriter(stream, self.standard_column_order)
        writer.writeheader()
        writer.writerow({
            'Name': '1.png',
            'Date': '2016-07-18',
            'Site': 'SiteA',
            'Habitat': 'Fringing Reef',
            'Transect': '2-4',
            'Aux4': 'Q5',
            'Aux5': '28',
            'Height (cm)': '50',
            'Latitude': '20.18',
            'Longitude': '-59.64',
            'Depth': '30m',
            'Camera': 'Canon',
            'Photographer': '',
            'Water quality': '',
            'Strobes': '',
            'Framing gear used': '',
            'White balance card': '',
            'Comments': '',
        })

        f = ContentFile(stream.getvalue(), name='A.csv')
        preview_response = self.preview(f)
        upload_response = self.upload()

        self.assertDictEqual(
            preview_response.json(),
            dict(
                success=True,
                previewTable=[
                    self.standard_column_order,
                    ['1.png', '2016-07-18', 'SiteA',
                     'Fringing Reef', '2-4',
                     'Q5', '28', '50', '20.18', '-59.64', '30m',
                     'Canon', '', '', '', '', '', ''],
                ],
                previewDetails=dict(
                    numImages=1,
                    numFieldsReplaced=0,
                ),
            ),
        )

        self.assertDictEqual(upload_response.json(), dict(success=True))

        meta1 = Image.objects.get(pk=self.img1.pk).metadata
        self.assertEqual(meta1.name, '1.png')
        self.assertEqual(meta1.photo_date, datetime.date(2016, 7, 18))
        self.assertEqual(meta1.aux1, 'SiteA')
        self.assertEqual(meta1.aux2, 'Fringing Reef')
        self.assertEqual(meta1.aux3, '2-4')
        self.assertEqual(meta1.aux4, 'Q5')
        self.assertEqual(meta1.aux5, '28')
        self.assertEqual(meta1.height_in_cm, 50)
        self.assertEqual(meta1.latitude, '20.18')
        self.assertEqual(meta1.longitude, '-59.64')
        self.assertEqual(meta1.depth, '30m')
        self.assertEqual(meta1.camera, 'Canon')
        self.assertEqual(meta1.photographer, '')
        self.assertEqual(meta1.water_quality, '')
        self.assertEqual(meta1.strobes, '')
        self.assertEqual(meta1.framing, '')
        self.assertEqual(meta1.balance, '')
        self.assertEqual(meta1.comments, '')

    def test_some_replaced_metadata(self):
        """
        Some fields get their non-blank values replaced
        with different values (blank or non-blank).
        """
        self.client.force_login(self.user)

        meta1 = self.img1.metadata
        meta1.photo_date = datetime.date(2014, 2, 27)
        meta1.aux1 = 'SiteC'
        meta1.camera = 'Nikon'
        meta1.save()

        stream = StringIO()
        writer = csv.DictWriter(stream, self.standard_column_order)
        writer.writeheader()
        writer.writerow({
            'Name': '1.png',
            'Date': '2016-07-18',
            'Site': 'SiteA',
            'Habitat': 'Fringing Reef',
            'Transect': '2-4',
            'Aux4': 'Q5',
            'Aux5': '28',
            'Height (cm)': '50',
            'Latitude': '20.18',
            'Longitude': '-59.64',
            'Depth': '30m',
            'Camera': '',
            'Photographer': '',
            'Water quality': '',
            'Strobes': '',
            'Framing gear used': '',
            'White balance card': '',
            'Comments': '',
        })

        f = ContentFile(stream.getvalue(), name='A.csv')
        preview_response = self.preview(f)
        upload_response = self.upload()

        self.assertDictEqual(
            preview_response.json(),
            dict(
                success=True,
                previewTable=[
                    self.standard_column_order,
                    ['1.png', ['2016-07-18', '2014-02-27'], ['SiteA', 'SiteC'],
                     'Fringing Reef', '2-4',
                     'Q5', '28', '50', '20.18', '-59.64', '30m',
                     ['', 'Nikon'], '', '', '', '', '', ''],
                ],
                previewDetails=dict(
                    numImages=1,
                    numFieldsReplaced=3,
                ),
            ),
        )

        self.assertDictEqual(upload_response.json(), dict(success=True))

        meta1 = Image.objects.get(pk=self.img1.pk).metadata
        self.assertEqual(meta1.name, '1.png')
        self.assertEqual(meta1.photo_date, datetime.date(2016, 7, 18))
        self.assertEqual(meta1.aux1, 'SiteA')
        self.assertEqual(meta1.aux2, 'Fringing Reef')
        self.assertEqual(meta1.aux3, '2-4')
        self.assertEqual(meta1.aux4, 'Q5')
        self.assertEqual(meta1.aux5, '28')
        self.assertEqual(meta1.height_in_cm, 50)
        self.assertEqual(meta1.latitude, '20.18')
        self.assertEqual(meta1.longitude, '-59.64')
        self.assertEqual(meta1.depth, '30m')
        self.assertEqual(meta1.camera, '')
        self.assertEqual(meta1.photographer, '')
        self.assertEqual(meta1.water_quality, '')
        self.assertEqual(meta1.strobes, '')
        self.assertEqual(meta1.framing, '')
        self.assertEqual(meta1.balance, '')
        self.assertEqual(meta1.comments, '')

    def test_skipped_fields(self):
        """
        The CSV doesn't have to cover every possible field in its columns.
        Excluded fields should have their metadata untouched.
        """
        self.client.force_login(self.user)

        meta1 = self.img1.metadata
        meta1.photo_date = datetime.date(2014, 2, 27)
        meta1.aux1 = 'SiteC'
        meta1.camera = 'Nikon'
        meta1.height_in_cm = 50
        meta1.save()

        column_names = ['Name', 'Site', 'Habitat', 'Transect']

        stream = StringIO()
        writer = csv.DictWriter(stream, column_names)
        writer.writeheader()
        writer.writerow({
            'Name': '1.png',
            'Site': 'SiteA',
            'Habitat': 'Fringing Reef',
            'Transect': '2-4',
        })

        f = ContentFile(stream.getvalue(), name='A.csv')
        preview_response = self.preview(f)
        upload_response = self.upload()

        self.assertDictEqual(
            preview_response.json(),
            dict(
                success=True,
                previewTable=[
                    column_names,
                    ['1.png', ['SiteA', 'SiteC'],
                     'Fringing Reef', '2-4'],
                ],
                previewDetails=dict(
                    numImages=1,
                    numFieldsReplaced=1,
                ),
            ),
        )

        self.assertDictEqual(upload_response.json(), dict(success=True))

        meta1 = Image.objects.get(pk=self.img1.pk).metadata
        self.assertEqual(meta1.name, '1.png')
        self.assertEqual(meta1.photo_date, datetime.date(2014, 2, 27))
        self.assertEqual(meta1.aux1, 'SiteA')
        self.assertEqual(meta1.aux2, 'Fringing Reef')
        self.assertEqual(meta1.aux3, '2-4')
        self.assertEqual(meta1.height_in_cm, 50)
        self.assertEqual(meta1.camera, 'Nikon')

    def test_skipped_csv_columns(self):
        """
        The CSV can have column names that we don't recognize. Those columns
        will just be ignored.
        """
        self.client.force_login(self.user)

        column_names = ['Name', 'Site', 'Time of day', 'Habitat', 'Transect']

        stream = StringIO()
        writer = csv.DictWriter(stream, column_names)
        writer.writeheader()
        writer.writerow({
            'Name': '1.png',
            'Site': 'SiteA',
            'Time of day': 'Sunset',
            'Habitat': 'Fringing Reef',
            'Transect': '2-4',
        })

        f = ContentFile(stream.getvalue(), name='A.csv')
        preview_response = self.preview(f)
        upload_response = self.upload()

        self.assertDictEqual(
            preview_response.json(),
            dict(
                success=True,
                previewTable=[
                    ['Name', 'Site', 'Habitat', 'Transect'],
                    ['1.png', 'SiteA', 'Fringing Reef', '2-4'],
                ],
                previewDetails=dict(
                    numImages=1,
                    numFieldsReplaced=0,
                ),
            ),
        )

        self.assertDictEqual(upload_response.json(), dict(success=True))

        meta1 = Image.objects.get(pk=self.img1.pk).metadata
        self.assertEqual(meta1.name, '1.png')
        self.assertEqual(meta1.aux1, 'SiteA')
        self.assertEqual(meta1.aux2, 'Fringing Reef')
        self.assertEqual(meta1.aux3, '2-4')

    def test_skipped_filenames(self):
        """
        The CSV can have filenames that we don't recognize. Those rows
        will just be ignored.
        """
        self.client.force_login(self.user)

        column_names = ['Name', 'Site']

        stream = StringIO()
        writer = csv.DictWriter(stream, column_names)
        writer.writeheader()
        writer.writerow({
            'Name': '1.png',
            'Site': 'SiteA',
        })
        writer.writerow({
            'Name': '10.png',
            'Site': 'SiteJ',
        })

        f = ContentFile(stream.getvalue(), name='A.csv')
        preview_response = self.preview(f)
        upload_response = self.upload()

        self.assertDictEqual(
            preview_response.json(),
            dict(
                success=True,
                previewTable=[
                    ['Name', 'Site'],
                    ['1.png', 'SiteA'],
                ],
                previewDetails=dict(
                    numImages=1,
                    numFieldsReplaced=0,
                ),
            ),
        )

        self.assertDictEqual(upload_response.json(), dict(success=True))

        meta1 = Image.objects.get(pk=self.img1.pk).metadata
        self.assertEqual(meta1.name, '1.png')
        self.assertEqual(meta1.aux1, 'SiteA')

    def test_columns_different_order(self):
        """
        The CSV columns can be in a different order.
        """
        self.client.force_login(self.user)

        column_names = ['Transect', 'Site', 'Name']

        stream = StringIO()
        writer = csv.DictWriter(stream, column_names)
        writer.writeheader()
        writer.writerow({
            'Transect': '2-4',
            'Site': 'SiteA',
            'Name': '1.png',
        })

        f = ContentFile(stream.getvalue(), name='A.csv')
        preview_response = self.preview(f)
        upload_response = self.upload()

        self.assertDictEqual(
            preview_response.json(),
            dict(
                success=True,
                previewTable=[
                    column_names,
                    ['2-4', 'SiteA', '1.png'],
                ],
                previewDetails=dict(
                    numImages=1,
                    numFieldsReplaced=0,
                ),
            ),
        )

        self.assertDictEqual(upload_response.json(), dict(success=True))

        meta1 = Image.objects.get(pk=self.img1.pk).metadata
        self.assertEqual(meta1.name, '1.png')
        self.assertEqual(meta1.aux1, 'SiteA')
        self.assertEqual(meta1.aux3, '2-4')

    def test_columns_different_case(self):
        """
        The CSV column names can use different upper/lower case and still
        be matched to the metadata field labels.
        """
        self.client.force_login(self.user)

        column_names = ['TRANSECT', 'site', 'NaMe']

        stream = StringIO()
        writer = csv.DictWriter(stream, column_names)
        writer.writeheader()
        writer.writerow({
            'TRANSECT': '2-4',
            'site': 'SiteA',
            'NaMe': '1.png',
        })

        f = ContentFile(stream.getvalue(), name='A.csv')
        preview_response = self.preview(f)
        upload_response = self.upload()

        self.assertDictEqual(
            preview_response.json(),
            dict(
                success=True,
                previewTable=[
                    ['Transect', 'Site', 'Name'],
                    ['2-4', 'SiteA', '1.png'],
                ],
                previewDetails=dict(
                    numImages=1,
                    numFieldsReplaced=0,
                ),
            ),
        )

        self.assertDictEqual(upload_response.json(), dict(success=True))

        meta1 = Image.objects.get(pk=self.img1.pk).metadata
        self.assertEqual(meta1.name, '1.png')
        self.assertEqual(meta1.aux1, 'SiteA')
        self.assertEqual(meta1.aux3, '2-4')

    def test_dupe_column_names(self):
        """
        Two CSV columns have the same name. Shouldn't get a server error.
        (Arbitrarily, the later column will take precedence).
        """
        self.client.force_login(self.user)

        column_names = ['Name', 'Latitude', 'LATITUDE']

        stream = StringIO()
        writer = csv.DictWriter(stream, column_names)
        writer.writeheader()
        writer.writerow({
            'Name': '1.png',
            'Latitude': '24.08',
            'LATITUDE': '42.67',
        })

        f = ContentFile(stream.getvalue(), name='A.csv')
        preview_response = self.preview(f)
        upload_response = self.upload()

        self.assertDictEqual(
            preview_response.json(),
            dict(
                success=True,
                previewTable=[
                    ['Name', 'Latitude'],
                    ['1.png', '42.67'],
                ],
                previewDetails=dict(
                    numImages=1,
                    numFieldsReplaced=0,
                ),
            ),
        )

        self.assertDictEqual(upload_response.json(), dict(success=True))

        meta1 = Image.objects.get(pk=self.img1.pk).metadata
        self.assertEqual(meta1.name, '1.png')
        self.assertEqual(meta1.latitude, '42.67')


class UploadMetadataMultipleSourcesTest(ClientTest):
    """
    Test involving multiple sources.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)
        cls.source2 = cls.create_source(cls.user)

        cls.img1_s1 = cls.upload_image(
            cls.user, cls.source, image_options=dict(filename='1.png'))
        cls.img1_s2 = cls.upload_image(
            cls.user, cls.source2, image_options=dict(filename='1.png'))
        cls.img2_s2 = cls.upload_image(
            cls.user, cls.source2, image_options=dict(filename='2.png'))

    def preview1(self, csv_file):
        return self.client.post(
            reverse('upload_metadata_preview_ajax', args=[self.source.pk]),
            {'csv_file': csv_file},
        )

    def upload1(self):
        return self.client.post(
            reverse('upload_metadata_ajax', args=[self.source.pk]),
        )

    def preview2(self, csv_file):
        return self.client.post(
            reverse('upload_metadata_preview_ajax', args=[self.source2.pk]),
            {'csv_file': csv_file},
        )

    def upload2(self):
        return self.client.post(
            reverse('upload_metadata_ajax', args=[self.source2.pk]),
        )

    def test_other_sources_unaffected(self):
        """
        We shouldn't touch images of other sources which happen to have
        the same image names.
        """
        self.client.force_login(self.user)

        column_names = ['Name', 'Aux1']

        # Upload to source 2
        stream = StringIO()
        writer = csv.DictWriter(stream, column_names)
        writer.writeheader()
        writer.writerow({
            'Name': '1.png',
            'Aux1': 'SiteA',
        })
        writer.writerow({
            'Name': '2.png',
            'Aux1': 'SiteB',
        })

        f = ContentFile(stream.getvalue(), name='A.csv')
        self.preview2(f)
        self.upload2()

        # Upload to source 1
        stream = StringIO()
        writer = csv.DictWriter(stream, column_names)
        writer.writeheader()
        writer.writerow({
            'Name': '1.png',
            'Aux1': 'SiteC',
        })
        writer.writerow({
            'Name': '2.png',
            'Aux1': 'SiteD',
        })

        f = ContentFile(stream.getvalue(), name='B.csv')
        preview_response = self.preview1(f)
        upload_response = self.upload1()

        # Check source 1 responses

        self.assertDictEqual(
            preview_response.json(),
            dict(
                success=True,
                previewTable=[
                    column_names,
                    ['1.png', 'SiteC'],
                ],
                previewDetails=dict(
                    numImages=1,
                    numFieldsReplaced=0,
                ),
            ),
        )

        self.assertDictEqual(upload_response.json(), dict(success=True))

        # Check source 1 objects

        meta1_s1 = self.img1_s1.metadata
        self.assertEqual(meta1_s1.name, '1.png')
        self.assertEqual(meta1_s1.aux1, 'SiteC')

        # Check source 2 objects

        meta1_s2 = self.img1_s2.metadata
        meta2_s2 = self.img2_s2.metadata
        self.assertEqual(meta1_s2.name, '1.png')
        self.assertEqual(meta1_s2.aux1, 'SiteA')
        self.assertEqual(meta2_s2.name, '2.png')
        self.assertEqual(meta2_s2.aux1, 'SiteB')


class UploadMetadataPreviewTest(ClientTest):
    """
    Tests only pertaining to metadata preview.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)

        cls.source.key1 = 'Site'
        cls.source.save()

        cls.img1 = cls.upload_image(
            cls.user, cls.source, image_options=dict(filename='1.png'))
        cls.img2 = cls.upload_image(
            cls.user, cls.source, image_options=dict(filename='2.png'))
        cls.img3 = cls.upload_image(
            cls.user, cls.source, image_options=dict(filename='3.png'))
        cls.img4 = cls.upload_image(
            cls.user, cls.source, image_options=dict(filename='4.png'))
        cls.img5 = cls.upload_image(
            cls.user, cls.source, image_options=dict(filename='5.png'))
        cls.img6 = cls.upload_image(
            cls.user, cls.source, image_options=dict(filename='6.png'))
        cls.img7 = cls.upload_image(
            cls.user, cls.source, image_options=dict(filename='7.png'))
        cls.img8 = cls.upload_image(
            cls.user, cls.source, image_options=dict(filename='8.png'))
        cls.img9 = cls.upload_image(
            cls.user, cls.source, image_options=dict(filename='9.png'))
        cls.img10 = cls.upload_image(
            cls.user, cls.source, image_options=dict(filename='10.png'))

    def preview(self, csv_file):
        return self.client.post(
            reverse('upload_metadata_preview_ajax', args=[self.source.pk]),
            {'csv_file': csv_file},
        )

    def test_row_order_preserved_in_preview_table(self):
        """
        The CSV row order should be the same as the row order
        in the preview table.
        """
        self.client.force_login(self.user)

        column_names = ['Name', 'Site']

        stream = StringIO()
        writer = csv.DictWriter(stream, column_names)
        writer.writeheader()
        writer.writerow({'Name': '5.png', 'Site': 'SiteE'})
        writer.writerow({'Name': '1.png', 'Site': 'SiteA'})
        writer.writerow({'Name': '2.png', 'Site': 'SiteB'})
        writer.writerow({'Name': '6.png', 'Site': 'SiteF'})
        writer.writerow({'Name': '10.png', 'Site': 'SiteJ'})
        writer.writerow({'Name': '4.png', 'Site': 'SiteD'})
        writer.writerow({'Name': '7.png', 'Site': 'SiteG'})
        writer.writerow({'Name': '8.png', 'Site': 'SiteH'})
        writer.writerow({'Name': '9.png', 'Site': 'SiteI'})
        writer.writerow({'Name': '3.png', 'Site': 'SiteC'})

        f = ContentFile(stream.getvalue(), name='A.csv')
        preview_response = self.preview(f)

        self.assertDictEqual(
            preview_response.json(),
            dict(
                success=True,
                previewTable=[
                    column_names,
                    ['5.png', 'SiteE'],
                    ['1.png', 'SiteA'],
                    ['2.png', 'SiteB'],
                    ['6.png', 'SiteF'],
                    ['10.png', 'SiteJ'],
                    ['4.png', 'SiteD'],
                    ['7.png', 'SiteG'],
                    ['8.png', 'SiteH'],
                    ['9.png', 'SiteI'],
                    ['3.png', 'SiteC'],
                ],
                previewDetails=dict(
                    numImages=10,
                    numFieldsReplaced=0,
                ),
            ),
        )


class UploadMetadataErrorTest(ClientTest):
    """
    Metadata upload, error cases.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)

        cls.img1 = cls.upload_image(
            cls.user, cls.source, image_options=dict(filename='1.png'))
        cls.img2 = cls.upload_image(
            cls.user, cls.source, image_options=dict(filename='2.png'))

        cls.standard_column_order = [
            'Name', 'Date', 'Aux1', 'Aux2', 'Aux3', 'Aux4', 'Aux5',
            'Height (cm)', 'Latitude', 'Longitude', 'Depth',
            'Camera', 'Photographer', 'Water quality',
            'Strobes', 'Framing gear used', 'White balance card', 'Comments',
        ]

    def preview(self, csv_file):
        return self.client.post(
            reverse('upload_metadata_preview_ajax', args=[self.source.pk]),
            {'csv_file': csv_file},
        )

    def upload(self):
        return self.client.post(
            reverse('upload_metadata_ajax', args=[self.source.pk]),
        )

    def test_expired_session(self):
        """
        The session variable is cleared between preview and upload.
        """
        self.client.force_login(self.user)

        column_names = ['Name', 'Aux1']

        stream = StringIO()
        writer = csv.DictWriter(stream, column_names)
        writer.writeheader()
        writer.writerow({
            'Name': '1.png',
            'Aux1': 'SiteA',
        })

        f = ContentFile(stream.getvalue(), name='A.csv')
        self.preview(f)

        # Clear the session data
        #
        # "Be careful: To modify the session and then save it,
        # it must be stored in a variable first (because a new SessionStore
        # is created every time this property is accessed)"
        # http://stackoverflow.com/a/4454671/
        session = self.client.session
        session.pop('csv_metadata')
        session.save()

        upload_response = self.upload()

        self.assertDictEqual(
            upload_response.json(),
            dict(error=(
                "We couldn't find the expected data in your session."
                " Please try loading this page again. If the problem persists,"
                " let us know on the forum."
            )),
        )


class UploadMetadataPreviewErrorTest(ClientTest):
    """
    Metadata upload preview, error cases (mainly related to CSV content).
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)

        cls.img1 = cls.upload_image(
            cls.user, cls.source, image_options=dict(filename='1.png'))
        cls.img2 = cls.upload_image(
            cls.user, cls.source, image_options=dict(filename='2.png'))

        cls.standard_column_order = [
            'Name', 'Date', 'Aux1', 'Aux2', 'Aux3', 'Aux4', 'Aux5',
            'Height (cm)', 'Latitude', 'Longitude', 'Depth',
            'Camera', 'Photographer', 'Water quality',
            'Strobes', 'Framing gear used', 'White balance card', 'Comments',
        ]

    def preview(self, csv_file):
        return self.client.post(
            reverse('upload_metadata_preview_ajax', args=[self.source.pk]),
            {'csv_file': csv_file},
        )

    def test_dupe_field_labels_1(self):
        """
        An aux. metadata field has the same label (non case sensitive)
        as a default metadata field.

        Gets an error even if this metadata field is not involved in the
        import.
        (It behaves this way just to make implementing the check simpler.)
        """
        self.client.force_login(self.user)

        self.source.key2 = 'CAMERA'
        self.source.save()

        column_names = ['Name', 'Aux1']

        stream = StringIO()
        writer = csv.DictWriter(stream, column_names)
        writer.writeheader()
        writer.writerow({
            'Name': '1.png',
            'Aux1': 'SiteA',
        })

        f = ContentFile(stream.getvalue(), name='A.csv')
        preview_response = self.preview(f)

        self.assertDictEqual(
            preview_response.json(),
            dict(
                error=(
                    "More than one metadata field uses the label 'camera'."
                    " Your auxiliary fields' names must be unique"
                    " and different from the default metadata fields."
                ),
            ),
        )

    def test_dupe_field_labels_2(self):
        """
        Two aux. metadata fields have the same label.
        """
        self.client.force_login(self.user)

        self.source.key1 = 'Site'
        self.source.key2 = 'site'
        self.source.save()

        column_names = ['Name', 'Site']

        stream = StringIO()
        writer = csv.DictWriter(stream, column_names)
        writer.writeheader()
        writer.writerow({
            'Name': '1.png',
            'Site': 'SiteA',
        })

        f = ContentFile(stream.getvalue(), name='A.csv')
        preview_response = self.preview(f)

        self.assertDictEqual(
            preview_response.json(),
            dict(
                error=(
                    "More than one metadata field uses the label 'site'."
                    " Your auxiliary fields' names must be unique"
                    " and different from the default metadata fields."
                ),
            ),
        )

    def test_dupe_row_filenames(self):
        """
        Two CSV rows have the same filename.
        """
        self.client.force_login(self.user)

        column_names = ['Name', 'Aux1']

        stream = StringIO()
        writer = csv.DictWriter(stream, column_names)
        writer.writeheader()
        writer.writerow({
            'Name': '1.png',
            'Aux1': 'SiteA',
        })
        writer.writerow({
            'Name': '1.png',
            'Aux1': 'SiteA',
        })

        f = ContentFile(stream.getvalue(), name='A.csv')
        preview_response = self.preview(f)

        self.assertDictEqual(
            preview_response.json(),
            dict(
                error=(
                    "More than one row with the same Name: 1.png"
                ),
            ),
        )

    def test_no_specified_images_found_in_source(self):
        """
        No CSV rows have a filename that can be found in the source.
        """
        self.client.force_login(self.user)

        column_names = ['Name', 'Aux1']

        stream = StringIO()
        writer = csv.DictWriter(stream, column_names)
        writer.writeheader()
        writer.writerow({
            'Name': '3.png',
            'Aux1': 'SiteA',
        })

        f = ContentFile(stream.getvalue(), name='A.csv')
        preview_response = self.preview(f)

        self.assertDictEqual(
            preview_response.json(),
            dict(
                error=(
                    "No matching filenames found in the source"
                ),
            ),
        )

    def test_no_name_column(self):
        """
        No CSV columns correspond to the name field.
        """
        self.client.force_login(self.user)

        column_names = ['Aux1', 'Aux2']

        stream = StringIO()
        writer = csv.DictWriter(stream, column_names)
        writer.writeheader()
        writer.writerow({
            'Aux1': 'SiteA',
            'Aux2': 'Fringing Reef',
        })

        f = ContentFile(stream.getvalue(), name='A.csv')
        preview_response = self.preview(f)

        self.assertDictEqual(
            preview_response.json(),
            dict(
                error=(
                    "CSV must have a column called Name"
                ),
            ),
        )

    def test_no_recognized_non_name_column(self):
        """
        No CSV columns correspond to metadata fields besides the name field,
        and thus no metadata could be found.
        """
        self.client.force_login(self.user)

        column_names = ['Name', 'Time of day']

        stream = StringIO()
        writer = csv.DictWriter(stream, column_names)
        writer.writeheader()
        writer.writerow({
            'Name': '1.png',
            'Time of day': 'Sunset',
        })

        f = ContentFile(stream.getvalue(), name='A.csv')
        preview_response = self.preview(f)

        self.assertDictEqual(
            preview_response.json(),
            dict(error=(
                "CSV must have at least one metadata column other than Name"
            )),
        )

    def test_invalid_metadata_value(self):
        """
        One of the metadata values is invalid.
        """
        self.client.force_login(self.user)

        column_names = ['Name', 'Date']

        stream = StringIO()
        writer = csv.DictWriter(stream, column_names)
        writer.writeheader()
        writer.writerow({
            'Name': '1.png',
            'Date': '2015-02-29',  # Nonexistent date
        })

        f = ContentFile(stream.getvalue(), name='A.csv')
        preview_response = self.preview(f)

        self.assertDictEqual(
            preview_response.json(),
            dict(error="(1.png - Date) Enter a valid date."),
        )


class UploadMetadataPreviewFormatTest(ClientTest):
    """
    Metadata upload preview, special cases or error cases with CSV formats.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)

        cls.img1 = cls.upload_image(
            cls.user, cls.source, image_options=dict(filename='1.png'))
        cls.img2 = cls.upload_image(
            cls.user, cls.source, image_options=dict(filename='2.png'))

    def preview(self, csv_file):
        return self.client.post(
            reverse('upload_metadata_preview_ajax', args=[self.source.pk]),
            {'csv_file': csv_file},
        )

    def test_crlf_newlines(self):
        """
        Tolerate carriage return + line feed newlines in the CSV
        (Windows style).
        """
        self.client.force_login(self.user)

        content = (
            'Name,Aux1'
            '\r\n1.png,SiteA'
        )
        f = ContentFile(content, name='A.csv')
        preview_response = self.preview(f)

        self.assertDictEqual(
            preview_response.json(),
            dict(
                success=True,
                previewTable=[
                    ['Name', 'Aux1'],
                    ['1.png', 'SiteA'],
                ],
                previewDetails=dict(
                    numImages=1,
                    numFieldsReplaced=0,
                ),
            ),
        )

    def test_cr_only_newlines(self):
        """
        Tolerate carriage-return-only newlines in the CSV (old Mac style).
        """
        self.client.force_login(self.user)

        content = (
            'Name,Aux1'
            '\r1.png,SiteA'
        )
        f = ContentFile(content, name='A.csv')
        preview_response = self.preview(f)

        self.assertDictEqual(
            preview_response.json(),
            dict(
                success=True,
                previewTable=[
                    ['Name', 'Aux1'],
                    ['1.png', 'SiteA'],
                ],
                previewDetails=dict(
                    numImages=1,
                    numFieldsReplaced=0,
                ),
            ),
        )

    def test_unicode(self):
        """
        Tolerate non-ASCII UTF-8 characters in the CSV.
        """
        self.client.force_login(self.user)

        content = (
            'Name,Aux1'
            '\n1.png,地点A'
        )
        f = ContentFile(content, name='A.csv')
        preview_response = self.preview(f)

        self.assertDictEqual(
            preview_response.json(),
            dict(
                success=True,
                previewTable=[
                    ['Name', 'Aux1'],
                    ['1.png', '地点A'],
                ],
                previewDetails=dict(
                    numImages=1,
                    numFieldsReplaced=0,
                ),
            ),
        )

    def test_utf8_bom_char(self):
        """
        Tolerate UTF-8 BOM character at the start of the CSV.
        """
        self.client.force_login(self.user)

        content = (
            '\ufeffName,Aux1'
            '\n1.png,SiteA'
        )
        f = ContentFile(content, name='A.csv')
        preview_response = self.preview(f)

        self.assertDictEqual(
            preview_response.json(),
            dict(
                success=True,
                previewTable=[
                    ['Name', 'Aux1'],
                    ['1.png', 'SiteA'],
                ],
                previewDetails=dict(
                    numImages=1,
                    numFieldsReplaced=0,
                ),
            ),
        )

    def test_field_with_newline(self):
        """
        Upload a metadata field value with a newline character in it (within
        quotation marks). The newline character should be preserved in the
        saved metadata.
        """
        self.client.force_login(self.user)

        content = (
            'Name,Comments'
            '\n1.png,"Here are\nsome comments."'
        )
        f = ContentFile(content, name='A.csv')
        preview_response = self.preview(f)

        self.assertDictEqual(
            preview_response.json(),
            dict(
                success=True,
                previewTable=[
                    ['Name', 'Comments'],
                    ['1.png', 'Here are\nsome comments.'],
                ],
                previewDetails=dict(
                    numImages=1,
                    numFieldsReplaced=0,
                ),
            ),
        )

    def test_extra_quotes(self):
        """
        Strip "surrounding quotes" around CSV values. This is the most common
        text delimiter for CSVs, used to enclose cell values containing commas.
        Depending on how you save your CSV, your program might auto-add quotes
        even in the absence of commas.
        """
        self.client.force_login(self.user)

        content = (
            'Name,Aux1'
            '\n"1.png","SiteA,IsleB"'
        )
        f = ContentFile(content, name='A.csv')
        preview_response = self.preview(f)

        self.assertDictEqual(
            preview_response.json(),
            dict(
                success=True,
                previewTable=[
                    ['Name', 'Aux1'],
                    ['1.png', 'SiteA,IsleB'],
                ],
                previewDetails=dict(
                    numImages=1,
                    numFieldsReplaced=0,
                ),
            ),
        )

    def test_surrounding_whitespace(self):
        """
        Strip leading and trailing whitespace around CSV values.
        """
        self.client.force_login(self.user)

        content = (
            'Name,Aux1  '
            '\n 1.png\t,  SiteA '
        )
        f = ContentFile(content, name='A.csv')
        preview_response = self.preview(f)

        self.assertDictEqual(
            preview_response.json(),
            dict(
                success=True,
                previewTable=[
                    ['Name', 'Aux1'],
                    ['1.png', 'SiteA'],
                ],
                previewDetails=dict(
                    numImages=1,
                    numFieldsReplaced=0,
                ),
            ),
        )

    def test_non_csv(self):
        """
        Do at least basic detection of non-CSV files.
        """
        self.client.force_login(self.user)

        f = self.sample_image_as_file('A.jpg')
        preview_response = self.preview(f)

        self.assertDictEqual(
            preview_response.json(),
            dict(
                error="The selected file is not a CSV file.",
            ),
        )

    def test_empty_file(self):
        self.client.force_login(self.user)

        content = ''
        f = ContentFile(content, name='A.csv')
        preview_response = self.preview(f)

        self.assertDictEqual(
            preview_response.json(),
            dict(
                error="The submitted file is empty.",
            ),
        )
