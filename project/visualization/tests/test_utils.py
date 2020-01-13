from PIL import Image as PILImage

from django.core.files.storage import get_storage_class
from django.conf import settings

from lib.tests.utils import ClientTest
from images.models import Point
from visualization.utils import generate_patch_if_doesnt_exist, get_patch_path


class LabelPatchGenerationTest(ClientTest):

    @classmethod
    def setUpTestData(cls):
        super(LabelPatchGenerationTest, cls).setUpTestData()

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

        # Then assert the patch was actually generated and that is RGB
        storage = get_storage_class()()
        patch = PILImage.open(storage.open(get_patch_path(point_id)))
        self.assertEqual(patch.size[0], settings.LABELPATCH_NROWS)
        self.assertEqual(patch.size[1], settings.LABELPATCH_NCOLS)
        self.assertEqual(patch.mode, 'RGB')


