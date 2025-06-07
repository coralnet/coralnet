import datetime

from django.core.files.base import ContentFile
from django.shortcuts import resolve_url
from django.urls import reverse

from export.tests.utils import BaseExportTest
from lib.tests.utils import BasePermissionTest


class PermissionTest(BasePermissionTest):

    def test_metadata(self):
        url = reverse('export_metadata', args=[self.source.pk])

        self.source_to_private()
        self.assertPermissionLevel(
            url, self.SOURCE_VIEW, content_type='text/csv')
        self.source_to_public()
        self.assertPermissionLevel(
            url, self.SIGNED_IN, content_type='text/csv',
            deny_type=self.REQUIRE_LOGIN)


class ImageSetTest(BaseExportTest):
    """Test metadata export to CSV for different kinds of image subsets."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)

    def test_all_images_single(self):
        """Export for 1 out of 1 images."""
        self.img1 = self.upload_image(
            self.user, self.source, dict(filename='1.jpg'))

        response = self.export_metadata()

        expected_lines = [
            'Name,Date,Aux1,Aux2,Aux3,Aux4,Aux5'
            ',Height (cm),Latitude,Longitude,Depth,Camera,Photographer'
            ',Water quality,Strobes,Framing gear used,White balance card'
            ',Comments',
            '1.jpg,,,,,,,,,,,,,,,,,',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_all_images_multiple(self):
        """Export for 3 out of 3 images."""
        self.img1 = self.upload_image(
            self.user, self.source, dict(filename='1.jpg'))
        self.img2 = self.upload_image(
            self.user, self.source, dict(filename='2.jpg'))
        self.img3 = self.upload_image(
            self.user, self.source, dict(filename='3.jpg'))

        response = self.export_metadata()

        expected_lines = [
            'Name,Date,Aux1,Aux2,Aux3,Aux4,Aux5'
            ',Height (cm),Latitude,Longitude,Depth,Camera,Photographer'
            ',Water quality,Strobes,Framing gear used,White balance card'
            ',Comments',
            '1.jpg,,,,,,,,,,,,,,,,,',
            '2.jpg,,,,,,,,,,,,,,,,,',
            '3.jpg,,,,,,,,,,,,,,,,,',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_image_subset_by_metadata(self):
        """Export for some, but not all, images."""
        self.img1 = self.upload_image(
            self.user, self.source, dict(filename='1.jpg'))
        self.img2 = self.upload_image(
            self.user, self.source, dict(filename='2.jpg'))
        self.img3 = self.upload_image(
            self.user, self.source, dict(filename='3.jpg'))
        self.img1.metadata.aux1 = 'X'
        self.img1.metadata.save()
        self.img2.metadata.aux1 = 'Y'
        self.img2.metadata.save()
        self.img3.metadata.aux1 = 'X'
        self.img3.metadata.save()

        post_data = dict(aux1='X')
        response = self.export_metadata(post_data)

        expected_lines = [
            'Name,Date,Aux1,Aux2,Aux3,Aux4,Aux5'
            ',Height (cm),Latitude,Longitude,Depth,Camera,Photographer'
            ',Water quality,Strobes,Framing gear used,White balance card'
            ',Comments',
            '1.jpg,,X,,,,,,,,,,,,,,,',
            '3.jpg,,X,,,,,,,,,,,,,,,',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_image_empty_set(self):
        """Export for 0 images."""
        self.img1 = self.upload_image(
            self.user, self.source, dict(filename='1.jpg'))

        post_data = dict(image_name='5.jpg')
        response = self.export_metadata(post_data)

        expected_lines = [
            'Name,Date,Aux1,Aux2,Aux3,Aux4,Aux5'
            ',Height (cm),Latitude,Longitude,Depth,Camera,Photographer'
            ',Water quality,Strobes,Framing gear used,White balance card'
            ',Comments',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_invalid_image_set_params(self):
        self.upload_image(self.user, self.source)

        post_data = dict(photo_date_0='abc')
        response = self.export_metadata(post_data)

        # Display an error in HTML instead of serving CSV.
        self.assertTrue(response['content-type'].startswith('text/html'))
        self.assertContains(response, "Image-search parameters were invalid.")

    def test_dont_get_other_sources_images(self):
        """Don't export for other sources' images."""
        self.img1 = self.upload_image(
            self.user, self.source, dict(filename='1.jpg'))
        source2 = self.create_source(self.user)
        self.upload_image(self.user, source2, dict(filename='2.jpg'))

        response = self.export_metadata()

        # Should have image 1, but not 2
        expected_lines = [
            'Name,Date,Aux1,Aux2,Aux3,Aux4,Aux5'
            ',Height (cm),Latitude,Longitude,Depth,Camera,Photographer'
            ',Water quality,Strobes,Framing gear used,White balance card'
            ',Comments',
            '1.jpg,,,,,,,,,,,,,,,,,',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)


class MetadataColumnsTest(BaseExportTest):
    """Test that the export's columns are filled as they should."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)

    def test_metadata_values(self):
        self.img1 = self.upload_image(
            self.user, self.source, dict(filename='1.jpg'))
        self.img1.metadata.photo_date = datetime.date(2001, 2, 3)
        self.img1.metadata.aux1 = "Site A"
        self.img1.metadata.aux2 = "Transect 1-2"
        self.img1.metadata.aux3 = "Quadrant 5"
        self.img1.metadata.aux4 = "Line 4"
        self.img1.metadata.aux5 = "Point 8"
        self.img1.metadata.height_in_cm = 40
        self.img1.metadata.latitude = "5.789"
        self.img1.metadata.longitude = "-50"
        self.img1.metadata.depth = "10m"
        self.img1.metadata.camera = "Nikon"
        self.img1.metadata.photographer = "John Doe"
        self.img1.metadata.water_quality = "Clear"
        self.img1.metadata.strobes = "White A"
        self.img1.metadata.framing = "Framing set C"
        self.img1.metadata.balance = "Card B"
        self.img1.metadata.comments = "Here are\nsome comments."
        self.img1.metadata.save()

        response = self.export_metadata()

        expected_lines = [
            'Name,Date,Aux1,Aux2,Aux3,Aux4,Aux5'
            ',Height (cm),Latitude,Longitude,Depth,Camera,Photographer'
            ',Water quality,Strobes,Framing gear used,White balance card'
            ',Comments',
            '1.jpg,2001-02-03,Site A,Transect 1-2,Quadrant 5,Line 4,Point 8'
            ',40,5.789,-50,10m,Nikon,John Doe'
            ',Clear,White A,Framing set C,Card B'
            ',"Here are\nsome comments."',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_named_aux_fields(self):
        self.img1 = self.upload_image(
            self.user, self.source, dict(filename='1.jpg'))
        self.source.key1 = "Site"
        self.source.key2 = "Transect"
        self.source.key3 = "Quadrant"
        self.source.save()
        self.img1.metadata.photo_date = datetime.date(2001, 2, 3)
        self.img1.metadata.aux1 = "Site A"
        self.img1.metadata.aux2 = "Transect 1-2"
        self.img1.metadata.aux3 = "Quadrant 5"
        self.img1.metadata.save()

        response = self.export_metadata()

        expected_lines = [
            'Name,Date,Site,Transect,Quadrant,Aux4,Aux5'
            ',Height (cm),Latitude,Longitude,Depth,Camera,Photographer'
            ',Water quality,Strobes,Framing gear used,White balance card'
            ',Comments',
            '1.jpg,2001-02-03,Site A,Transect 1-2,Quadrant 5,,,,,,,,,,,,,',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)


class UnicodeTest(BaseExportTest):
    """Test that non-ASCII characters don't cause problems."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)

    def test(self):
        self.img1 = self.upload_image(
            self.user, self.source, dict(filename='あ.jpg'))
        self.img1.metadata.aux1 = "地点A"
        self.img1.metadata.save()

        response = self.export_metadata()

        expected_lines = [
            'Name,Date,Aux1,Aux2,Aux3,Aux4,Aux5'
            ',Height (cm),Latitude,Longitude,Depth,Camera,Photographer'
            ',Water quality,Strobes,Framing gear used,White balance card'
            ',Comments',
            'あ.jpg,,地点A,,,,,,,,,,,,,,,',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)


class UploadAndExportSameDataTest(BaseExportTest):
    """Test that we can upload a CSV and then export the exact same CSV."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)

    def test(self):
        self.img1 = self.upload_image(
            self.user, self.source, dict(filename='1.jpg'))

        # Upload metadata
        content = ''
        csv_lines = [
            'Name,Date,Aux1,Aux2,Aux3,Aux4,Aux5'
            ',Height (cm),Latitude,Longitude,Depth,Camera,Photographer'
            ',Water quality,Strobes,Framing gear used,White balance card'
            ',Comments',
            '1.jpg,2001-02-03,Site A,Transect 1-2,Quadrant 5,Line 4,Point 8'
            ',40,5.789,-50,10m,Nikon,John Doe'
            ',Clear,White A,Framing set C,Card B'
            ',"Here are\nsome comments."',
        ]
        for line in csv_lines:
            content += (line + '\n')
        csv_file = ContentFile(content, name='metadata.csv')

        self.client.force_login(self.user)
        self.client.post(
            resolve_url('upload_metadata_preview_ajax', self.source.pk),
            {'csv_file': csv_file},
        )
        self.client.post(
            resolve_url('upload_metadata_ajax', self.source.pk),
        )

        # Export metadata
        response = self.export_metadata()

        self.assert_csv_content_equal(response.content, csv_lines)
