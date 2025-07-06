from io import BytesIO
from unittest import mock

import piexif
from PIL import Image as PILImage
from django.core.files.base import ContentFile
from django.db.models import QuerySet
from django.test import override_settings
from django_migration_testcase import MigrationTest
from easy_thumbnails.files import get_thumbnailer

from lib.tests.utils import BaseTest, ClientTest, spy_decorator
from vision_backend.common import Extractors
from ..model_utils import PointGen
from ..models import Point


class SourceExtractorPropertyTest(ClientTest):
    """
    Test the feature_extractor property of the Source model.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user, feature_extractor_setting=Extractors.EFFICIENTNET.value)

    @override_settings(FORCE_DUMMY_EXTRACTOR=False)
    def test_do_not_force_dummy(self):
        self.assertEqual(
            Extractors.EFFICIENTNET.value, self.source.feature_extractor)

    @override_settings(FORCE_DUMMY_EXTRACTOR=True)
    def test_force_dummy(self):
        self.assertEqual('dummy', self.source.feature_extractor)


class ImageExifOrientationTest(ClientTest):
    """
    Test images with EXIF orientation.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)
        labels = cls.create_labels(cls.user, ['label1'], 'group1')
        cls.labelset = cls.create_labelset(cls.user, cls.source, labels)

    def test_thumbnail_doesnt_use_exif_orientation(self):
        """
        Generated thumbnails should ignore the original image's EXIF
        orientation.
        """
        # Create an image with:
        # - A blue background
        # - 1 corner filled with red pixels
        blue_color = (0, 0, 255)
        red_color = (255, 0, 0)

        # EXIF specifying 90-degree right rotation
        zeroth_ifd = {piexif.ImageIFD.Orientation: 8}
        exif_dict = {'0th': zeroth_ifd}
        exif_bytes = piexif.dump(exif_dict)

        with PILImage.new('RGB', (100, 70), color=blue_color) as im:
            upper_left_20_by_20 = (0, 0, 20, 20)
            im.paste(red_color, upper_left_20_by_20)

            # Save image
            with BytesIO() as stream:
                im.save(stream, 'JPEG', exif=exif_bytes)
                image_file = ContentFile(stream.getvalue(), name='1.jpg')

        # Upload image
        img = self.upload_image(self.user, self.source, image_file=image_file)

        im = PILImage.open(img.original_file)
        exif_dict = piexif.load(im.info['exif'])
        # We don't use a context manager to close in this case, since that
        # didn't properly close it on Windows for some reason.
        im.close()

        self.assertEqual(
            exif_dict['0th'][piexif.ImageIFD.Orientation], 8,
            "Image should be saved with EXIF orientation")

        # Generate thumbnail of 50-pixel width
        opts = {'size': (50, 0)}
        thumbnail = get_thumbnailer(img.original_file).get_thumbnail(opts)

        # Check thumbnail file
        with PILImage.open(thumbnail.file) as thumb_im:
            self.assertEqual(
                thumb_im.size, (50, 35),
                "Thumbnail dimensions should have the same aspect ratio as"
                " the original image, un-rotated")
            self.assertNotIn(
                'exif', thumb_im.info,
                "Thumbnail should not have EXIF (we just want it to not have"
                " non-default EXIF orientation, but the actual result is that"
                " there is no EXIF, so we check for that)")

            # Check thumbnail file content. This is all JPEG, so we don't
            # expect exact color matches, but this code should manage to check
            # which corner is the red corner.
            upper_left_pixel = thumb_im.getpixel((0, 0))
            upper_left_r_greater_than_b = \
                upper_left_pixel[0] > upper_left_pixel[2]
            self.assertTrue(
                upper_left_r_greater_than_b,
                "Red corner should be the same corner as in the original"
                " image, indicating that the thumbnail content is un-rotated")


class PointGenTest(BaseTest):

    def test_point_count_simple_random(self):
        self.assertEqual(
            PointGen(type='simple', points=15).total_points,
            15,
        )

    def test_point_count_stratified_random(self):
        self.assertEqual(
            PointGen(type='stratified', cell_rows=3,
                     cell_columns=5, per_cell=7).total_points,
            105,
        )

    def test_point_count_uniform_grid(self):
        self.assertEqual(
            PointGen(type='uniform', cell_rows=10,
                     cell_columns=17).total_points,
            170,
        )

    def test_point_count_imported(self):
        self.assertEqual(
            PointGen(type='imported', points=40).total_points,
            40,
        )


class PointValidationTest(ClientTest):

    def test_bounds_checks(self):
        user = self.create_user()
        source = self.create_source(user)
        image = self.upload_image(
            user, source, image_options=dict(width=50, height=40))

        # OK
        point = Point(image=image, column=0, row=0, point_number=1)
        point.save()
        point = Point(image=image, column=49, row=39, point_number=2)
        point.save()

        # Errors
        point = Point(image=image, column=0, row=-1, point_number=3)
        with self.assertRaisesMessage(AssertionError, "Row below minimum"):
            point.save()

        point = Point(image=image, column=49, row=40, point_number=3)
        with self.assertRaisesMessage(AssertionError, "Row above maximum"):
            point.save()

        point = Point(image=image, column=-1, row=0, point_number=3)
        with self.assertRaisesMessage(AssertionError, "Column below minimum"):
            point.save()

        point = Point(image=image, column=50, row=39, point_number=3)
        with self.assertRaisesMessage(AssertionError, "Column above maximum"):
            point.save()


class MetadataImageFieldMigrationTest(MigrationTest):
    """
    Test porting from Image.metadata field to Metadata.image field.
    """

    before = [
        ('images', '0040_delete_source'),
        ('sources', '0010_populate_deployed_classifier'),
    ]
    after = [
        ('images', '0045_metadata_image_onetoone_schema3'),
    ]

    image_defaults = dict(
        original_width=100,
        original_height=100,
    )

    def test_images_and_metadata_remain_paired(self):
        """
        Images and Metadata that were paired before should remain paired after.
        """
        Source = self.get_model_before('sources.Source')
        Image = self.get_model_before('images.Image')
        Metadata = self.get_model_before('images.Metadata')

        source = Source.objects.create()

        metadata_ids = []
        image_ids = []
        for _ in range(10):
            metadata = Metadata.objects.create()
            metadata_ids.append(metadata.pk)
            image = Image.objects.create(
                source=source, metadata=metadata, **self.image_defaults)
            image_ids.append(image.pk)

            # Metadata.image attributes shouldn't exist yet
            self.assertRaises(AttributeError, getattr, metadata, 'image')

        bulk_update = spy_decorator(QuerySet.bulk_update)

        with (
            mock.patch(
                'images.migrations.0042_metadata_image_onetoone_data1'
                '.UPDATE_BATCH_SIZE',
                3,
            ),
            mock.patch.object(QuerySet, 'bulk_update', bulk_update),
        ):
            self.run_migration()

        Metadata = self.get_model_after('images.Metadata')

        for i in range(10):
            # Metadata.image attributes should be filled in
            self.assertEqual(
                Metadata.objects.get(pk=metadata_ids[i]).image.pk,
                image_ids[i])

        self.assertEqual(
            bulk_update.mock_obj.call_count, 4,
            msg="Should require 4 calls with batch size 3"
                " to update 10 metadata instances"
        )

    def test_clean_up_metadata_without_images(self):
        """
        Metadata without a corresponding Image should get cleaned up.
        """
        Source = self.get_model_before('sources.Source')
        Metadata = self.get_model_before('images.Metadata')
        Image = self.get_model_before('images.Image')

        source = Source.objects.create()

        metadata_1 = Metadata.objects.create()
        metadata_1_pk = metadata_1.pk
        Image.objects.create(
            source=source, metadata=metadata_1, **self.image_defaults)

        metadata_2 = Metadata.objects.create()
        metadata_2_pk = metadata_2.pk

        def input_without_prompt(_):
            """
            Bypass the input prompt by mocking input(). This just returns a
            constant value.
            """
            return 'y'
        def print_noop(_):
            """Don't print output during the migration run."""
            pass
        input_mock_target = \
            'images.migrations.0044_metadata_image_onetoone_data2.input'
        print_mock_target = \
            'images.migrations.0044_metadata_image_onetoone_data2.print'
        with mock.patch(input_mock_target, input_without_prompt):
            with mock.patch(print_mock_target, print_noop):
                self.run_migration()

        Metadata = self.get_model_after('images.Metadata')
        # This should still exist (should not raise error)
        Metadata.objects.get(pk=metadata_1_pk)
        # This shouldn't exist anymore
        self.assertRaises(
            Metadata.DoesNotExist, Metadata.objects.get, pk=metadata_2_pk)


class MetadataImageFieldBackwardsMigrationTest(MigrationTest):
    """
    Test porting from Metadata.image field back to Image.metadata field.
    """

    before = [
        ('images', '0045_metadata_image_onetoone_schema3'),
        ('sources', '0010_populate_deployed_classifier'),
    ]
    after = [
        ('images', '0040_delete_source'),
    ]

    image_defaults = dict(
        original_width=100,
        original_height=100,
    )

    def test_images_and_metadata_remain_paired(self):
        """
        Images and Metadata that were paired before should remain paired after.
        """
        Source = self.get_model_before('sources.Source')
        Image = self.get_model_before('images.Image')
        Metadata = self.get_model_before('images.Metadata')

        source = Source.objects.create()

        image_ids = []
        metadata_ids = []
        for _ in range(10):
            image = Image.objects.create(
                source=source, **self.image_defaults)
            image_ids.append(image.pk)
            metadata = Metadata.objects.create(image=image)
            metadata_ids.append(metadata.pk)

        bulk_update = spy_decorator(QuerySet.bulk_update)

        with (
            mock.patch(
                'images.migrations.0042_metadata_image_onetoone_data1'
                '.UPDATE_BATCH_SIZE',
                3,
            ),
            mock.patch.object(QuerySet, 'bulk_update', bulk_update),
        ):
            self.run_migration()

        Image = self.get_model_after('images.Image')
        Metadata = self.get_model_after('images.Metadata')

        for i in range(10):
            # Image.metadata should be filled in
            self.assertEqual(
                Image.objects.get(pk=image_ids[i]).metadata.pk,
                metadata_ids[i])

            # Metadata.image attributes shouldn't exist anymore
            self.assertRaises(
                AttributeError, getattr,
                Metadata.objects.get(pk=metadata_ids[i]), 'image')

        self.assertEqual(
            bulk_update.mock_obj.call_count, 4,
            msg="Should require 4 calls with batch size 3"
                " to update 10 metadata instances"
        )
