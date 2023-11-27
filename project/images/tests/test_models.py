from io import BytesIO

import piexif
from PIL import Image as PILImage
from django.core.files.base import ContentFile
from django.test import override_settings
from easy_thumbnails.files import get_thumbnailer

from lib.tests.utils import BaseTest, ClientTest
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
            cls.user, feature_extractor_setting='efficientnet_b0_ver1')

    @override_settings(FORCE_DUMMY_EXTRACTOR=False)
    def test_do_not_force_dummy(self):
        self.assertEqual('efficientnet_b0_ver1', self.source.feature_extractor)

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
            PointGen.db_to_point_count(PointGen.args_to_db_format(
                point_generation_type=PointGen.Types.SIMPLE,
                simple_number_of_points=15,
            )),
            15,
        )

    def test_point_count_stratified_random(self):
        self.assertEqual(
            PointGen.db_to_point_count(PointGen.args_to_db_format(
                point_generation_type=PointGen.Types.STRATIFIED,
                number_of_cell_rows=3,
                number_of_cell_columns=5,
                stratified_points_per_cell=7,
            )),
            105,
        )

    def test_point_count_uniform_grid(self):
        self.assertEqual(
            PointGen.db_to_point_count(PointGen.args_to_db_format(
                point_generation_type=PointGen.Types.UNIFORM,
                number_of_cell_rows=10,
                number_of_cell_columns=17,
            )),
            170,
        )

    def test_point_count_imported(self):
        self.assertEqual(
            PointGen.db_to_point_count(PointGen.args_to_db_format(
                point_generation_type=PointGen.Types.IMPORTED,
                imported_number_of_points=40,
            )),
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
