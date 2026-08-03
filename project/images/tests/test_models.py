from io import BytesIO

import piexif
from PIL import Image as PILImage
from django.core.files.base import ContentFile
from django.db import IntegrityError
from django.test import override_settings
from easy_thumbnails.files import get_thumbnailer

from lib.tests.utils import CnStandardTest
from vision_backend.common import Extractors
from ..model_utils import PointGen
from ..models import Image, Metadata, Point


def input_without_prompt(_):
    """
    Bypass the input prompt by mocking input(). This just returns a
    constant value.
    """
    return 'y'


image_defaults = dict(
    original_width=32,
    original_height=32,
)


class SourceExtractorPropertyTest(CnStandardTest):
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


class ImageExifOrientationTest(CnStandardTest):
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


class MetadataUniqueNamesInSourceTest(CnStandardTest):
    """
    Raw-ORM testing for dupe image names.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)
        cls.other_source = cls.create_source(cls.user)

    def new_image(self, source):
        return Image.objects.create(source=source, **image_defaults)

    def test(self):
        Metadata.objects.create(
            source=self.source, image=self.new_image(self.source),
            name='1.png')
        Metadata.objects.create(
            source=self.source, image=self.new_image(self.source),
            name='2.png')

        with self.assertRaises(IntegrityError):
            Metadata.objects.create(
                source=self.source, image=self.new_image(self.source),
                name='1.png')

    def test_same_name_in_other_source_ok(self):
        Metadata.objects.create(
            source=self.other_source, image=self.new_image(self.other_source),
            name='1.png')
        Metadata.objects.create(
            source=self.source, image=self.new_image(self.source),
            name='1.png')

    def test_case_insensitive(self):
        Metadata.objects.create(
            source=self.source, image=self.new_image(self.source),
            name='1.png')

        with self.assertRaises(IntegrityError):
            Metadata.objects.create(
                source=self.source, image=self.new_image(self.source),
                name='1.PNG')


class PointGenUtilTest(CnStandardTest):

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


class PointCreateTest(CnStandardTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)
        cls.image = cls.upload_image(cls.user, cls.source)

    def test_image_fks_present(self):
        Point.objects.delete_for_image(self.image)
        self.assertEqual(self.image.point_set.count(), 0, msg="Sanity check")

        points = [
            Point(
                point_number=num, row=num, column=num,
                image=self.image,
            )
            for num in [1,2,3]
        ]
        Point.objects.bulk_create_for_image(points, self.image)

        self.assertEqual(self.image.point_set.count(), 3)

    def test_image_fks_present_but_mismatched(self):
        Point.objects.delete_for_image(self.image)
        self.assertEqual(self.image.point_set.count(), 0, msg="Sanity check")

        image2 = self.upload_image(self.user, self.source)

        points = [
            Point(
                point_number=num, row=num, column=num,
                image=image2,
            )
            for num in [1,2,3]
        ]
        with self.assertRaises(ValueError) as cm:
            Point.objects.bulk_create_for_image(points, self.image)

        self.assertEqual(
            str(cm.exception),
            f"Args have clashing Images:"
            f" ID {image2.pk} vs. ID {self.image.pk}")

        self.assertEqual(self.image.point_set.count(), 0)

    def test_image_fks_absent(self):
        Point.objects.delete_for_image(self.image)
        self.assertEqual(self.image.point_set.count(), 0, msg="Sanity check")

        points = [
            Point(
                point_number=num, row=num, column=num,
            )
            for num in [1,2,3]
        ]
        Point.objects.bulk_create_for_image(points, self.image)

        self.assertEqual(self.image.point_set.count(), 3)


class PointValidationTest(CnStandardTest):

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
