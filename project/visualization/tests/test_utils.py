from io import BytesIO
import os
from unittest import mock

from PIL import Image as PILImage
from PIL.Image import SAVE as PIL_SAVE
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import override_settings

from images.models import Point
from lib.tests.utils import ClientTest
from visualization.utils import generate_patch_if_doesnt_exist, get_patch_path


class LabelPatchGenerationTest(ClientTest):
    """
    Test basics of patch generation, including supporting different color
    spaces.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)
        labels = cls.create_labels(cls.user, ['label1'], 'group1')
        cls.labelset = cls.create_labelset(cls.user, cls.source, labels)

    def test_rgb(self):
        self._test_helper('RGB')

    def test_rgba(self):
        self._test_helper('RGBA')

    def test_gray(self):
        self._test_helper('L')

    def _test_helper(self, image_mode):
        img = self.upload_image(self.user, self.source,
                                image_options={'mode': image_mode})

        point_id = Point.objects.filter(image=img)[0].id

        # Assert that patches can be generated without problems
        try:
            generate_patch_if_doesnt_exist(point_id)
        except IOError as msg:
            self.fail("Error occurred during patch generation: {}".format(msg))

        # Then assert the patch was actually generated and that it's RGB
        with default_storage.open(get_patch_path(point_id)) as fp:
            patch = PILImage.open(fp)
            self.assertEqual(patch.size[0], settings.LABELPATCH_NROWS)
            self.assertEqual(patch.size[1], settings.LABELPATCH_NCOLS)
            self.assertEqual(patch.mode, 'RGB')

    def test_rgb_convert_fix(self):

        # This file caused an issue in production. Solution is to set
        # PIL.ImageFile.LOAD_TRUNCATED_IMAGES = True before loading.
        # See https://github.com/coralnet/coralnet/issues/282 for details
        filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                'fixtures/p82pkvoqn3.JPG')
        img = PILImage.open(filepath)

        try:
            img.convert('RGB')
        except IOError as e:
            self.fail("img.convert('RGB') raised IOError unexpectedly: {}"
                      .format(repr(e)))


def always_save_png(self, fp, format=None, **params):
    """
    Mock version of PIL's Image.save().
    Ignores the format param and always uses 'PNG'.
    """
    self.encoderinfo = params
    self.encoderconfig = ()
    PIL_SAVE['PNG'](self, fp, '1.png')


@override_settings(
    LABELPATCH_NCOLS=21,
    LABELPATCH_NROWS=21,
    LABELPATCH_SIZE_FRACTION=0.2,
    POINT_PATCH_FILE_PATTERN=(
        '{full_image_path}.pointpk{point_pk}.thumbnail.png'))
class PatchCropTest(ClientTest):
    """
    Test that patch generation does cropping pixel-perfectly.

    Target sizes:
    Original image w, h --crop-> 21, 21 --resize-> 21, 21.
    Since the resize doesn't change the resolution, and since we're
    saving a PNG patch using the mocked save() method, the resize is
    essentially a no-op, allowing us to assert exact pixel values.
    Due to how the crop size is calculated, max(w, h) should be between
    100 and 109 for this to work.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)
        labels = cls.create_labels(cls.user, ['label1'], 'group1')
        cls.labelset = cls.create_labelset(cls.user, cls.source, labels)

    def assertPatchCroppedCorrectly(
            self, image_size, point_location, off_image_pixel_count=0):
        # Create an image with:
        # - A blue background
        # - 1 red pixel where a point will be placed
        # - 1 green pixel where the bottom-left corner of the patch will be
        blue_color = (0, 0, 255)
        red_color = (255, 0, 0)
        green_color = (0, 255, 0)
        black_color = (0, 0, 0)

        im = PILImage.new('RGB', image_size, color=blue_color)
        im.putpixel(point_location, red_color)
        bottom_right_corner = (point_location[0]-10, point_location[1]+10)
        im.putpixel(bottom_right_corner, green_color)

        with BytesIO() as stream:
            im.save(stream, 'PNG')
            image_file = ContentFile(stream.getvalue(), name='1.png')
        img = self.upload_image(self.user, self.source, image_file=image_file)

        # Take any point and give it the specified coordinates.
        point = img.point_set.first()
        point.column = point_location[0]
        point.row = point_location[1]
        point.save()

        # Generate the patch.
        # Patches normally save as JPG, but that's going to screw up our
        # efforts to check exact pixel values, so we mock Image's save() with
        # a version that always saves PNG, ignoring the 'format' param passed
        # to save().
        with mock.patch.object(PILImage.Image, 'save', always_save_png):
            generate_patch_if_doesnt_exist(point.pk)

        with default_storage.open(get_patch_path(point.pk)) as fp:
            patch = PILImage.open(fp)

            # The patch should have 1 red pixel in the center (to be exact, the
            # bottom-right of the 4 center pixels), and 1 green pixel in the
            # corner.
            self.assertEqual(patch.size, (21, 21))
            self.assertEqual(patch.getpixel((10, 10)), red_color)
            self.assertEqual(patch.getpixel((0, 20)), green_color)

            actual_colors = set(patch.getcolors())

        # For the other pixels, on-image pixels should be blue and off-image
        # pixels should be black (even if it's PNG for this test, since RGB
        # mode is being used).
        expected_color_counts = {
            (1, green_color), (1, red_color),
            (21*21-2 - off_image_pixel_count, blue_color)}
        if off_image_pixel_count > 0:
            expected_color_counts.add((off_image_pixel_count, black_color))
        self.assertSetEqual(actual_colors, expected_color_counts)

    def test_x_greater_dimension(self):
        # For this test, we make the crop size based on the x dimension, and
        # we make sure the patch doesn't touch the image edges.
        self.assertPatchCroppedCorrectly(
            image_size=(100, 70), point_location=(50, 25))

    def test_y_greater_dimension(self):
        # Crop size based on the y dimension.
        self.assertPatchCroppedCorrectly(
            image_size=(70, 100), point_location=(50, 25))

    def test_patch_includes_edge(self):
        # Since we're checking for a green pixel in the bottom-left corner,
        # we make sure that particular corner is within the image.
        # Here we'll make the crop go beyond the top edge.
        self.assertPatchCroppedCorrectly(
            image_size=(100, 70), point_location=(50, 5),
            off_image_pixel_count=(5 * 21))

    def test_patch_includes_corner(self):
        # Make the crop go beyond the top-right corner.
        self.assertPatchCroppedCorrectly(
            image_size=(100, 70), point_location=(92, 5),
            off_image_pixel_count=(5*21 + (92-99+10)*(21-5)))
