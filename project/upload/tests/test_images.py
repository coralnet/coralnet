from io import BytesIO
import json
import re
from unittest import mock

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core import mail
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from images.models import Image, Metadata
from lib.tests.utils import BasePermissionTest, ClientTest
from lib.tests.utils_data import create_sample_image


class PermissionTest(BasePermissionTest):

    def test_images(self):
        url = reverse('upload_images', args=[self.source.pk])
        template = 'upload/upload_images.html'

        self.source_to_private()
        self.assertPermissionLevel(url, self.SOURCE_EDIT, template=template)
        self.source_to_public()
        self.assertPermissionLevel(url, self.SOURCE_EDIT, template=template)

    def test_images_preview_ajax(self):
        url = reverse('upload_images_preview_ajax', args=[self.source.pk])
        post_data = dict(file_info='[]')

        self.source_to_private()
        self.assertPermissionLevel(
            url, self.SOURCE_EDIT, is_json=True, post_data=post_data)
        self.source_to_public()
        self.assertPermissionLevel(
            url, self.SOURCE_EDIT, is_json=True, post_data=post_data)

    def test_images_ajax(self):
        url = reverse('upload_images_ajax', args=[self.source.pk])

        self.source_to_private()
        self.assertPermissionLevel(
            url, self.SOURCE_EDIT, is_json=True, post_data={})
        self.source_to_public()
        self.assertPermissionLevel(
            url, self.SOURCE_EDIT, is_json=True, post_data={})


class PreviewTest(ClientTest):
    """
    Test the upload-image preview view.
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

    def submit_preview(self, file_info: list[dict]):
        self.client.force_login(self.user)
        return self.client.post(
            reverse('upload_images_preview_ajax', args=[self.source.pk]),
            dict(file_info=json.dumps(file_info)),
        )

    def assert_statuses(self, response, expected_statuses: list[dict]):
        response_json = response.json()
        self.assertDictEqual(
            response_json,
            dict(statuses=expected_statuses),
        )

    def test_valid(self):
        response = self.submit_preview(
            [dict(filename='3.png', size=1024)])

        self.assert_statuses(response, [dict(ok=True)])

    def test_dupe(self):
        response = self.submit_preview(
            [dict(filename='1.png', size=1024)])

        self.assert_statuses(response, [dict(
            error="Image with this name already exists",
            url=reverse('image_detail', args=[self.img1.id]),
        )])

    def test_dupe_case_insensitive(self):
        response = self.submit_preview(
            [dict(filename='1.PNG', size=1024)])

        self.assert_statuses(response, [dict(
            error="Image with this name already exists",
            url=reverse('image_detail', args=[self.img1.id]),
        )])

    def test_same_name_in_other_source_ok(self):
        source_2 = self.create_source(self.user)
        source_2_img = self.upload_image(
            self.user, source_2, image_options=dict(filename='3.png'))
        self.assertEqual(
            source_2_img.metadata.name, '3.png',
            msg="Sanity check: source_2 upload should succeed")

        # Upload preview on self.source
        response = self.submit_preview(
            [dict(filename='3.png', size=1024)])

        # Having the same name as source_2_img should be OK
        self.assert_statuses(response, [dict(ok=True)])

    @override_settings(IMAGE_UPLOAD_MAX_FILE_SIZE=30*1024*1024)
    def test_max_filesize(self):
        response = self.submit_preview(
            [dict(filename='3.png', size=30*1024*1024)])
        self.assert_statuses(response, [dict(ok=True)])

        response = self.submit_preview(
            [dict(filename='3.png', size=(30*1024*1024)+1)])
        self.assert_statuses(response, [dict(
            error="Exceeds size limit of 30.00 MB",
        )])

    def test_multiple(self):
        response = self.submit_preview([
            dict(filename='1.png', size=1024),
            dict(filename='2.png', size=1024),
            dict(filename='3.png', size=1024),
        ])

        self.assert_statuses(response, [
            dict(
                error="Image with this name already exists",
                url=reverse('image_detail', args=[self.img1.id]),
            ),
            dict(
                error="Image with this name already exists",
                url=reverse('image_detail', args=[self.img2.id]),
            ),
            dict(
                ok=True,
            ),
        ])


class UploadProcessTest(ClientTest):
    """
    Tests for the image upload itself (not the preview).
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)

    def submit_upload(self, post_data: dict):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('upload_images_ajax', args=[self.source.pk]),
            post_data,
        )
        return response.json()


class BasicsTest(UploadProcessTest):
    """
    Basic checks for the image upload itself.
    """

    def test_valid_png(self):
        """ .png created using the PIL. """
        response_json = self.submit_upload(
            dict(file=self.sample_image_as_file('1.png'), name='1.png'))

        self.assertEqual(response_json['success'], True)
        image_id = response_json['image_id']
        image = Image.objects.get(pk=image_id)
        self.assertEqual(image.metadata.name, '1.png')

    def test_valid_jpg(self):
        """ .jpg created using the PIL. """
        response_json = self.submit_upload(
            dict(file=self.sample_image_as_file('A.jpg'), name='A.jpg'))

        self.assertEqual(response_json['success'], True)
        image_id = response_json['image_id']
        image = Image.objects.get(pk=image_id)
        self.assertEqual(image.metadata.name, 'A.jpg')

    def test_image_fields(self):
        """
        Upload an image and see if the fields have been set correctly.
        """
        datetime_before_upload = timezone.now()

        image_file = self.sample_image_as_file(
            '1.png',
            image_options=dict(
                width=600, height=450,
            ),
        )

        response_json = self.submit_upload(
            dict(file=image_file, name=image_file.name))

        image_id = response_json['image_id']
        img = Image.objects.get(pk=image_id)

        # Check that the filepath follows the expected pattern
        image_filepath_regex = re.compile(
            settings.IMAGE_FILE_PATTERN
            # 10 lowercase alphanum chars
            .replace('{name}', r'[a-z0-9]{10}')
            # Same extension as the uploaded file
            .replace('{extension}', r'\.png')
        )
        self.assertRegex(
            str(img.original_file), image_filepath_regex)

        self.assertEqual(img.source_id, self.source.pk)
        self.assertEqual(img.original_width, 600)
        self.assertEqual(img.original_height, 450)

        self.assertTrue(datetime_before_upload <= img.upload_date)
        self.assertTrue(img.upload_date <= timezone.now())

        # Check that the user who uploaded the image is the
        # user we logged in as to do the upload.
        self.assertEqual(img.uploaded_by.pk, self.user.pk)

        metadata = Metadata.objects.get(image=img)
        self.assertEqual(metadata.source_id, self.source.pk)
        self.assertEqual(metadata.name, '1.png')
        self.assertEqual(
            metadata.annotation_area, self.source.image_annotation_area)

    def test_file_existence(self):
        """Uploaded file should exist in storage."""
        response_json = self.submit_upload(
            dict(file=self.sample_image_as_file('1.png'), name='1.png'))

        self.assertEqual(response_json['success'], True)
        image_id = response_json['image_id']
        img = Image.objects.get(pk=image_id)

        self.assertTrue(default_storage.exists(img.original_file.name))


class FormatTest(UploadProcessTest):
    """
    Tests pertaining to filetype, filesize and dimensions.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)

    def test_non_image(self):
        """Text file. Should get an error."""
        response_json = self.submit_upload(
            dict(file=ContentFile('some text', name='1.txt'), name='1.txt'))

        self.assertDictEqual(
            response_json,
            dict(error=(
                "Image file: The file is either a corrupt image,"
                " or in a file format that we don't support."
            ))
        )

    def test_unsupported_image_type(self):
        """An image, but not a supported type. Should get an error."""
        im = create_sample_image()
        with BytesIO() as stream:
            im.save(stream, 'BMP')
            bmp_file = ContentFile(stream.getvalue(), name='1.bmp')

        response_json = self.submit_upload(
            dict(file=bmp_file, name=bmp_file.name))

        self.assertDictEqual(
            response_json,
            dict(error="Image file: This image file format isn't supported.")
        )

    def test_capitalized_extension(self):
        """Capitalized extensions like .PNG should be okay."""
        response_json = self.submit_upload(
            dict(file=self.sample_image_as_file('1.PNG'), name='1.PNG'))

        self.assertEqual(response_json['success'], True)

        image_id = response_json['image_id']
        img = Image.objects.get(pk=image_id)
        self.assertEqual(img.metadata.name, '1.PNG')

    def test_no_filename_extension(self):
        """A supported image type, but the given filename has no extension."""
        im = create_sample_image()
        with BytesIO() as stream:
            im.save(stream, 'PNG')
            png_file = ContentFile(stream.getvalue(), name='123')

        response_json = self.submit_upload(
            dict(file=png_file, name=png_file.name))

        error_message = response_json['error']
        self.assertIn(
            'Image file: File extension “” is not allowed.', error_message)

    def test_empty_file(self):
        """0-byte file. Should get an error."""
        response_json = self.submit_upload(
            dict(file=ContentFile(bytes(), name='1.png'), name='1.png'))

        self.assertDictEqual(
            response_json,
            dict(error="Image file: The submitted file is empty.")
        )

    def test_max_image_dimensions_1(self):
        """Should check the max image width."""
        image_file = self.sample_image_as_file(
            '1.png', image_options=dict(width=600, height=450),
        )

        with self.settings(IMAGE_UPLOAD_MAX_DIMENSIONS=(599, 1000)):
            response_json = self.submit_upload(
                dict(file=image_file, name=image_file.name))

        self.assertDictEqual(
            response_json,
            dict(error=(
                "Image file: Ensure the image dimensions"
                " are at most 599 x 1000."))
        )

    def test_max_image_dimensions_2(self):
        """Should check the max image height."""
        image_file = self.sample_image_as_file(
            '1.png', image_options=dict(width=600, height=450),
        )

        with self.settings(IMAGE_UPLOAD_MAX_DIMENSIONS=(1000, 449)):
            response_json = self.submit_upload(
                dict(file=image_file, name=image_file.name))

        self.assertDictEqual(
            response_json,
            dict(error=(
                "Image file: Ensure the image dimensions"
                " are at most 1000 x 449."))
        )

    def test_upload_max_memory_size(self):
        """Exceeding the upload max memory size setting should be okay."""
        image_file = self.sample_image_as_file(
            '1.png', image_options=dict(width=600, height=450),
        )

        # Use an upload max memory size of 200 bytes; as long as the image has
        # some color variation, no way it'll be smaller than that
        with self.settings(FILE_UPLOAD_MAX_MEMORY_SIZE=200):
            response_json = self.submit_upload(
                dict(file=image_file, name=image_file.name))

        self.assertEqual(response_json['success'], True)
        image_id = response_json['image_id']
        image = Image.objects.get(pk=image_id)
        self.assertEqual(image.metadata.name, '1.png')


class MetadataNameCollisionTest(UploadProcessTest):
    """
    Test metadata name field collisions at confirm/process time.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)

        cls.img1 = cls.upload_image(
            cls.user, cls.source, image_options=dict(filename='1.png'))

    def test_dupe(self):
        image_file = self.sample_image_as_file('1.png')
        response_json = self.submit_upload(
            dict(file=image_file, name=image_file.name))

        self.assertDictEqual(
            response_json,
            dict(error=(
                "Image with this name already exists."))
        )

    def test_dupe_case_insensitive(self):
        image_file = self.sample_image_as_file('1.PNG')
        response_json = self.submit_upload(
            dict(file=image_file, name=image_file.name))

        self.assertDictEqual(
            response_json,
            dict(error=(
                "Image with this name already exists."))
        )

    def test_same_name_in_other_source_ok(self):
        source_2 = self.create_source(self.user)
        source_2_img = self.upload_image(
            self.user, source_2, image_options=dict(filename='3.png'))
        self.assertEqual(
            source_2_img.metadata.name, '3.png',
            msg="Sanity check: source_2 upload should succeed")

        image_file = self.sample_image_as_file('3.png')
        response_json = self.submit_upload(
            dict(file=image_file, name=image_file.name))

        self.assertEqual(response_json['success'], True)
        image_id = response_json['image_id']
        image = Image.objects.get(pk=image_id)
        self.assertEqual(image.metadata.name, '3.png')


class ThreeNameGenerator:

    iteration = 0

    # - Only 3 possible names
    # - At least one duplicate before going through all possible names
    # - At least as many items as image upload's name generation attempts (10)
    sequence = ['a', 'b', 'b', 'a', 'c', 'a', 'b', 'c', 'c', 'c', 'b', 'a']

    @classmethod
    def generate_name(cls, *args):
        cls.iteration += 1
        return cls.sequence[cls.iteration - 1]

    @classmethod
    def reset_iteration(cls):
        cls.iteration = 0


# Patch the rand_string function when used in the images.models module.
# The patched function can only generate 3 possible base names.
@mock.patch('images.models.rand_string', ThreeNameGenerator.generate_name)
@override_settings(ADMINS=[('Admin', 'admin@example.com')])
class StorageNameCollisionTest(UploadProcessTest):
    """
    Test name collisions when generating the image filename to save to
    file storage.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)

    def upload(self, image_name):
        # Ensure every upload starts from the beginning of the name generation
        # sequence.
        ThreeNameGenerator.reset_iteration()

        return self.submit_upload(
            dict(file=self.sample_image_as_file(image_name), name=image_name))

    def assertProblemMailAsExpected(self):
        problem_mail = mail.outbox[-1]

        self.assertListEqual(
            problem_mail.to, ['admin@example.com'],
            "Recipients should be correct")
        self.assertListEqual(problem_mail.cc, [], "cc should be empty")
        self.assertListEqual(problem_mail.bcc, [], "bcc should be empty")
        self.assertIn(
            "Image upload filename problem", problem_mail.subject,
            "Subject should have the expected contents")
        self.assertIn(
            "Wasn't able to generate a unique base name after 10 tries.",
            problem_mail.body,
            "Body should have the expected contents")

    def test_possible_base_names_exhausted(self):

        # Should be able to upload 3 images with the 3 possible base names.
        for image_name in ['1.png', '2.png', '3.png']:
            response_json = self.upload(image_name)

            img = Image.objects.get(pk=response_json['image_id'])
            self.assertRegex(img.original_file.name, r'[abc]\.png')

        self.assertEqual(
            len(mail.outbox), 0, msg="Should have no admin mail yet")

        # Should get a collision for the 4th, because there are no other
        # possible base names.
        response_json = self.upload('4.png')

        img = Image.objects.get(pk=response_json['image_id'])
        # In this case, we expect the storage framework to add a suffix to get
        # a unique filename.
        self.assertRegex(
            img.original_file.name, r'[abc]_[A-Za-z0-9]+\.png')

        self.assertEqual(len(mail.outbox), 1)
        self.assertProblemMailAsExpected()

        # Should still get a collision even if the extension is different
        # from the existing images, since comparisons are done on the
        # base name.
        response_json = self.upload('4.jpg')

        img = Image.objects.get(pk=response_json['image_id'])
        # In this case, we expect the storage framework to not add a suffix
        # because the extension is different.
        self.assertRegex(
            img.original_file.name, r'[abc]\.jpg')

        self.assertEqual(len(mail.outbox), 2)
        self.assertProblemMailAsExpected()
