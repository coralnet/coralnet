from django.urls import reverse

from images.models import Image, Metadata
from lib.tests.utils import BasePermissionTest, ClientTest
from vision_backend.models import Features
from .utils import BrowseActionsFormTest


class PermissionTest(BasePermissionTest):
    """
    Test view permissions.
    """
    def test_browse_delete_ajax(self):
        url = reverse('browse_delete_ajax', args=[self.source.pk])

        self.source_to_private()
        self.assertPermissionLevel(
            url, self.SOURCE_EDIT, is_json=True, post_data={})
        self.source_to_public()
        self.assertPermissionLevel(
            url, self.SOURCE_EDIT, is_json=True, post_data={})


class BaseDeleteTest(ClientTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)

        cls.url = reverse('browse_delete_ajax', args=[cls.source.pk])

        cls.default_search_params = dict(submit='search')

    def assert_image_deleted(self, image_id, name):
        msg = f"Image {name} should be deleted"
        with self.assertRaises(Image.DoesNotExist, msg=msg):
            Image.objects.get(pk=image_id)

    def assert_image_not_deleted(self, image_id, name):
        try:
            Image.objects.get(pk=image_id)
        except Image.DoesNotExist:
            raise AssertionError(f"Image {name} should not be deleted")

    def assert_confirmation_message(self, count):
        """
        Call this after a successful deletion to check the top-of-page
        confirmation message.
        """
        browse_url = reverse('browse_images', args=[self.source.pk])
        self.client.force_login(self.user)
        response = self.client.get(browse_url)
        self.assertContains(
            response,
            f"The {count} selected images have been deleted.")


class FormAvailabilityTest(BrowseActionsFormTest):
    form_id = 'delete-images-ajax-form'

    def test_no_search(self):
        self.client.force_login(self.user)
        response = self.client.get(self.browse_url)
        self.assert_form_placeholdered(
            response,
            "You must first submit the Search form before you can batch-delete images. (This is a safety check to reduce the chances of accidentally deleting all your images. If you really want to delete all images, just click Search without changing any of the search fields.)",
        )

    def test_after_search(self):
        self.client.force_login(self.user)
        response = self.client.get(
            self.browse_url, self.default_search_params)
        self.assert_form_available(response)

    def test_view_perms_only(self):
        self.client.force_login(self.user_viewer)
        response = self.client.get(
            self.browse_url, self.default_search_params)
        self.assert_form_absent(response)


class SuccessTest(BaseDeleteTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.img1 = cls.upload_image(cls.user, cls.source)
        cls.img2 = cls.upload_image(cls.user, cls.source)
        cls.img3 = cls.upload_image(cls.user, cls.source)

    def test_delete_all_images(self):
        """
        Delete all images in the source.
        """
        self.client.force_login(self.user)
        response = self.client.post(self.url, self.default_search_params)
        self.assertDictEqual(response.json(), dict(success=True))

        self.assert_image_deleted(self.img1.pk, "img1")
        self.assert_image_deleted(self.img2.pk, "img2")
        self.assert_image_deleted(self.img3.pk, "img3")

        self.assert_confirmation_message(count=3)

    def test_delete_by_aux_meta(self):
        """
        Delete when filtering images by auxiliary metadata.
        """
        self.img1.metadata.aux1 = 'SiteA'
        self.img1.metadata.save()

        post_data = dict(aux1='SiteA')

        self.client.force_login(self.user)
        response = self.client.post(self.url, post_data)
        self.assertDictEqual(response.json(), dict(success=True))

        self.assert_image_deleted(self.img1.pk, "img1")
        self.assert_image_not_deleted(self.img2.pk, "img2")
        self.assert_image_not_deleted(self.img3.pk, "img3")

        self.assert_confirmation_message(count=1)

    def test_delete_by_image_ids(self):
        """
        Delete images of particular image ids.
        """
        post_data = dict(
            image_id_list='_'.join([str(self.img1.pk), str(self.img3.pk)])
        )

        self.client.force_login(self.user)
        response = self.client.post(self.url, post_data)
        self.assertDictEqual(response.json(), dict(success=True))

        self.assert_image_deleted(self.img1.pk, "img1")
        self.assert_image_not_deleted(self.img2.pk, "img2")
        self.assert_image_deleted(self.img3.pk, "img3")

        self.assert_confirmation_message(count=2)

    def test_delete_related_objects(self):
        """
        Delete not just the Image objects, but also related objects.
        """
        post_data = dict(
            image_id_list='_'.join([str(self.img1.pk), str(self.img3.pk)])
        )
        metadata_1_id = self.img1.metadata.pk
        metadata_2_id = self.img2.metadata.pk
        metadata_3_id = self.img3.metadata.pk
        features_1_id = self.img1.features.pk
        features_2_id = self.img2.features.pk
        features_3_id = self.img3.features.pk

        self.client.force_login(self.user)
        response = self.client.post(self.url, post_data)
        self.assertDictEqual(response.json(), dict(success=True))

        with self.assertRaises(Metadata.DoesNotExist, msg="Should delete"):
            Metadata.objects.get(pk=metadata_1_id)
        try:
            Metadata.objects.get(pk=metadata_2_id)
        except Metadata.DoesNotExist:
            raise AssertionError("Should not delete")
        with self.assertRaises(Metadata.DoesNotExist, msg="Should delete"):
            Metadata.objects.get(pk=metadata_3_id)

        with self.assertRaises(Features.DoesNotExist, msg="Should delete"):
            Features.objects.get(pk=features_1_id)
        try:
            Features.objects.get(pk=features_2_id)
        except Features.DoesNotExist:
            raise AssertionError("Should not delete")
        with self.assertRaises(Features.DoesNotExist, msg="Should delete"):
            Features.objects.get(pk=features_3_id)


class OtherSourceTest(BaseDeleteTest):
    """
    Ensure that the UI doesn't allow deleting other sources' images.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.img1 = cls.upload_image(cls.user, cls.source)
        cls.img2 = cls.upload_image(cls.user, cls.source)
        source2 = cls.create_source(cls.user)
        cls.img21 = cls.upload_image(cls.user, source2)
        cls.img22 = cls.upload_image(cls.user, source2)

    def test_dont_delete_other_sources_images_via_search_form(self):
        """
        Sanity check that the search form only picks up images in the current
        source.
        """
        self.client.force_login(self.user)
        response = self.client.post(self.url, self.default_search_params)
        self.assertDictEqual(response.json(), dict(success=True))

        self.assert_image_deleted(self.img1.pk, "img1")
        self.assert_image_deleted(self.img2.pk, "img2")

        self.assert_image_not_deleted(self.img21.pk, "img21")
        self.assert_image_not_deleted(self.img22.pk, "img22")

    def test_dont_delete_other_sources_images_via_ids(self):
        """
        Sanity check that specifying by IDs only accepts images in the current
        source.
        """
        post_data = dict(
            image_id_list='_'.join([str(self.img1.pk), str(self.img22.pk)])
        )

        self.client.force_login(self.user)
        response = self.client.post(self.url, post_data)
        self.assertDictEqual(response.json(), dict(success=True))

        self.assert_image_deleted(self.img1.pk, "img1")
        self.assert_image_not_deleted(self.img22.pk, "img22")


class ErrorTest(BaseDeleteTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.img1 = cls.upload_image(cls.user, cls.source)
        cls.img2 = cls.upload_image(cls.user, cls.source)
        cls.img3 = cls.upload_image(cls.user, cls.source)

    def test_no_search_form(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url, dict())
        self.assertDictEqual(response.json(), dict(
            error=(
                "You must first use the search form or select images on the"
                " page to use the delete function. If you really want to"
                " delete all images, first click 'Search' without"
                " changing any of the search fields."
            )
        ))

        self.assert_image_not_deleted(self.img1.pk, "img1")
        self.assert_image_not_deleted(self.img2.pk, "img2")
        self.assert_image_not_deleted(self.img3.pk, "img3")

    def test_form_error(self):
        post_data = dict(annotation_status='invalid_value')

        self.client.force_login(self.user)
        response = self.client.post(self.url, post_data)
        self.assertDictEqual(response.json(), dict(
            error=(
                "There was an error with the form."
                " Nothing was deleted."
            )
        ))

        self.assert_image_not_deleted(self.img1.pk, "img1")
        self.assert_image_not_deleted(self.img2.pk, "img2")
        self.assert_image_not_deleted(self.img3.pk, "img3")
