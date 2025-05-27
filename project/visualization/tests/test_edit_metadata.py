import datetime

from bs4 import BeautifulSoup
from django.urls import reverse
from django.utils import timezone

from lib.tests.utils import BasePermissionTest
from sources.models import Source
from .utils import BaseBrowsePageTest


tz = timezone.get_current_timezone()


class PermissionTest(BasePermissionTest):
    """
    Test page permissions.
    """
    def test_edit_metadata(self):
        url = reverse('edit_metadata', args=[self.source.pk])
        template = 'visualization/edit_metadata.html'

        self.source_to_private()
        self.assertPermissionLevel(url, self.SOURCE_EDIT, template=template)
        self.source_to_public()
        self.assertPermissionLevel(url, self.SOURCE_EDIT, template=template)

    def test_edit_metadata_ajax(self):
        url = reverse('edit_metadata_ajax', args=[self.source.pk])

        # We get a 500 error if we don't pass in basic formset params and at
        # least 1 form.
        img = self.upload_image(self.user, self.source)
        post_data = {
            'form-TOTAL_FORMS': 1,
            'form-INITIAL_FORMS': 1,
            'form-MAX_NUM_FORMS': '',
            'form-0-id': img.metadata.pk,
        }

        self.source_to_private()
        self.assertPermissionLevel(
            url, self.SOURCE_EDIT, is_json=True, post_data=post_data)
        self.source_to_public()
        self.assertPermissionLevel(
            url, self.SOURCE_EDIT, is_json=True, post_data=post_data)


class BaseBrowseMetadataTest(BaseBrowsePageTest):

    url_name = 'edit_metadata'

    def get_results_table(self, response):
        response_soup = BeautifulSoup(response.content, 'html.parser')
        return response_soup.find('table', id='metadataFormTable')

    def assert_browse_results(
        self, response, expected_images,
        msg_prefix="Listed images should be the expected ones",
    ):
        table = self.get_results_table(response)
        status_cells = table.findAll('td', class_='status')
        status_cell_hrefs = [
            cell.find('a').attrs.get('href') for cell in status_cells]
        expected_status_cell_hrefs = [
            reverse('image_detail', args=[image.pk])
            for image in expected_images]
        self.assertListEqual(
            status_cell_hrefs, expected_status_cell_hrefs,
            msg=msg_prefix,
        )

    def assert_no_results(self, response):
        self.assert_table_absent(response)

    def assert_table_absent(self, response):
        table = self.get_results_table(response)
        self.assertIsNone(table, msg="Table should be absent")


# Many of the tests from here onward mirror tests from
# test_browse_images.py.


class FiltersTest(BaseBrowseMetadataTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.img1, cls.img2, cls.img3, cls.img4, cls.img5 = cls.images

    def test_no_submit(self):
        """Page landing, no search performed yet."""
        response = self.get_browse()
        self.assert_no_results(response)
        self.assertContains(
            response,
            "Use the form to specify the images you want to work with")

    def test_default_search(self):
        response = self.get_browse(**self.default_search_params)
        self.assert_browse_results(response, self.images)
        self.assertNotContains(
            response,
            "Use the form to specify the images you want to work with")

    def test_zero_results(self):
        response = self.get_browse(image_name='DSC')

        self.assert_no_results(response)
        self.assert_not_invalid_params(response)
        self.assertContains(response, "No image results.")

    def test_one_result(self):
        self.update_multiple_metadatas(
            'name',
            [(self.img3, 'DSC_0001.jpg')])
        response = self.get_browse(image_name='DSC')

        self.assert_browse_results(response, [self.img3])
        self.assert_not_invalid_params(response)
        self.assertNotContains(response, "No image results.")

    def test_dont_get_other_sources_images(self):
        source2 = self.create_source(self.user)
        self.upload_image(self.user, source2)

        # Just source 1's images, not source 2's
        response = self.get_browse(**self.default_search_params)
        self.assert_browse_results(response, self.images)

    def test_post_request(self):
        params = dict(image_name='1')
        self.client.force_login(self.user)

        response = self.client.post(self.url, params, follow=False)
        self.assertRedirects(
            response, self.url,
            msg_prefix="Should redirect back to edit metadata")

        response = self.client.post(self.url, params, follow=True)
        self.assertContains(
            response, "An error occurred; please try another search.",
            msg_prefix="Should show a message indicating the search didn't"
                       " actually work due to POST being used")

    # Specific filters.
    # These filters should be tested more thoroughly in test_browse_images.py.

    def test_filter_by_aux1(self):
        self.update_multiple_metadatas(
            'aux1',
            [(self.img1, 'Site1'),
             (self.img2, 'Site3'),
             (self.img3, 'Site3')])

        response = self.get_browse(aux1='Site3')
        self.assert_browse_results(
            response, [self.img2, self.img3])

    def test_filter_by_annotation_status_confirmed(self):
        robot = self.create_robot(self.source)
        # 2 points per image
        # confirmed, confirmed, unconfirmed, partial
        self.add_annotations(self.user, self.img1, {1: 'A', 2: 'B'})
        self.add_annotations(self.user, self.img2, {1: 'B', 2: 'A'})
        self.add_robot_annotations(robot, self.img3)
        self.add_annotations(self.user, self.img4, {1: 'B'})

        response = self.get_browse(annotation_status='confirmed')
        self.assert_browse_results(
            response, [self.img1, self.img2])

    def test_filter_by_photo_date_year(self):
        self.update_multiple_metadatas(
            'photo_date',
            [(self.img1, datetime.date(2011, 12, 28)),
             (self.img2, datetime.date(2012, 1, 13)),
             (self.img3, datetime.date(2012, 8, 4))])

        response = self.get_browse(photo_date_0='year', photo_date_1=2012)
        self.assert_browse_results(
            response, [self.img2, self.img3])

    def test_filter_by_annotation_date_range(self):
        # The given range should be included from day 1 00:00 to day n+1 00:00.
        self.set_last_annotation(
            self.img1, dt=datetime.datetime(2012, 3, 9, 23, 59, tzinfo=tz))
        self.set_last_annotation(
            self.img2, dt=datetime.datetime(2012, 3, 10, 0, 0, tzinfo=tz))
        self.set_last_annotation(
            self.img3, dt=datetime.datetime(2012, 3, 15, 12, 34, tzinfo=tz))
        self.set_last_annotation(
            self.img4, dt=datetime.datetime(2012, 3, 20, 23, 59, tzinfo=tz))
        self.set_last_annotation(
            self.img5, dt=datetime.datetime(2012, 3, 21, 0, 1, tzinfo=tz))

        response = self.get_browse(
            last_annotated_0='date_range',
            last_annotated_3=datetime.date(2012, 3, 10),
            last_annotated_4=datetime.date(2012, 3, 20),
        )
        self.assert_browse_results(
            response, [self.img2, self.img3, self.img4])

    def test_filter_by_annotator_tool_specific_user(self):
        self.add_annotations(self.user, self.img1, {1: 'A', 2: 'B'})

        user2 = self.create_user()
        self.add_source_member(
            self.user, self.source, user2, Source.PermTypes.EDIT.code)
        self.add_annotations(user2, self.img2, {1: 'A', 2: 'B'})

        response = self.get_browse(
            last_annotator_0='annotation_tool',
            last_annotator_1=user2.pk,
        )
        self.assert_browse_results(
            response, [self.img2])


class FormInitializationTest(BaseBrowseMetadataTest):

    def test_no_submit(self):
        """Page landing, no search performed yet."""
        response = self.get_browse()

        self.assertIsNotNone(
            self.get_search_form_field(response, 'image_name'),
            msg="Basic search fields should be present")
        self.assert_not_invalid_params(response)

    def test_default_search(self):
        response = self.get_browse(**self.default_search_params)

        self.assertIsNotNone(
            self.get_search_form_field(response, 'image_name'),
            msg="Basic search fields should be present")
        self.assert_not_invalid_params(response)

    def test_basic_field_after_submit(self):
        response = self.get_browse(image_name='DSC')

        search_field = self.get_search_form_field(response, 'image_name')
        self.assertEqual(
            search_field.attrs.get('value'), 'DSC',
            msg="Field value should be present in the search form")

    def test_load_metadata_form(self):
        """
        See if the form is loaded with the correct metadata in the fields.
        """
        # We'll test various fields, and ensure that there is at least one
        # field where the two images have different non-empty values.
        metadata_1 = self.images[0].metadata
        metadata_1.photo_date = datetime.date(2015, 11, 15)
        metadata_1.aux1 = "1"
        metadata_1.aux2 = "A"
        metadata_1.framing = "Framing device FD-09"
        metadata_1.save()
        metadata_2 = self.images[1].metadata
        metadata_2.aux1 = "2"
        metadata_2.aux2 = "B"
        metadata_2.height_in_cm = 45
        metadata_2.latitude = '-20.98'
        metadata_2.camera = "Nikon"
        metadata_2.comments = "This, is; a< test/\ncomment."
        metadata_2.save()

        response = self.get_browse(**self.default_search_params)

        # The form should have the correct metadata for both images.
        formset = response.context['metadata_formset']

        metadata_pks_to_forms = dict()
        for form in formset.forms:
            metadata_pks_to_forms[form['id'].value()] = form

        form_1 = metadata_pks_to_forms[self.images[0].pk]
        form_2 = metadata_pks_to_forms[self.images[1].pk]

        self.assertEqual(form_1['name'].value(), metadata_1.name)
        self.assertEqual(
            form_1['photo_date'].value(), datetime.date(2015, 11, 15))
        self.assertEqual(form_1['aux1'].value(), "1")
        self.assertEqual(form_1['aux2'].value(), "A")
        self.assertEqual(form_1['framing'].value(), "Framing device FD-09")

        self.assertEqual(form_2['name'].value(), metadata_2.name)
        self.assertEqual(form_2['aux1'].value(), "2")
        self.assertEqual(form_2['aux2'].value(), "B")
        self.assertEqual(form_2['height_in_cm'].value(), 45)
        self.assertEqual(form_2['latitude'].value(), "-20.98")
        self.assertEqual(form_2['camera'].value(), "Nikon")
        self.assertEqual(
            form_2['comments'].value(), "This, is; a< test/\ncomment.")


class ImageIdsTest(BaseBrowseMetadataTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.img1, cls.img2, cls.img3, cls.img4, cls.img5 = cls.images

    def test_filter_by_image_id_list(self):
        """
        This field should be tested more thoroughly in browse-images
        where we are more expecting the field to be used.
        """
        response = self.get_browse(
            image_id_list=f'{self.img2.pk}_{self.img3.pk}'
                          f'_{self.img5.pk}')
        self.assert_browse_results(
            response, [self.img2, self.img3, self.img5])

    def test_filter_by_image_id_range(self):
        """
        This filter is used when coming from image upload.
        """
        response = self.get_browse(
            image_id_range=f'{self.img2.pk}_{self.img4.pk}')
        self.assert_browse_results(
            response, [self.img2, self.img3, self.img4])

        # It's OK for the range to go beyond the eligible image IDs.
        response = self.get_browse(
            image_id_range=f'{self.img4.pk}_{self.img4.pk + 5}')
        self.assert_browse_results(
            response, [self.img4, self.img5])

    def test_non_integer_image_id_range(self):
        response = self.get_browse(
            image_id_range=f'{self.img1.pk}_a')
        self.assert_invalid_params(
            response, 'image_id_range',
            "Enter only digits separated by underscores.")

        response = self.get_browse(
            image_id_range=f'4.3_{self.img3.pk}')
        self.assert_invalid_params(
            response, 'image_id_range',
            "Enter only digits separated by underscores.")

    def test_image_id_range_wrong_size(self):
        response = self.get_browse(
            image_id_range=f'12_13_14')
        self.assert_invalid_params(
            response, 'image_id_range',
            "Should be a list of exactly 2 ID numbers.")

        response = self.get_browse(
            image_id_range=f'12')
        self.assert_invalid_params(
            response, 'image_id_range',
            "Should be a list of exactly 2 ID numbers.")

    def test_image_id_range_wrong_order(self):
        response = self.get_browse(
            image_id_range=f'14_13')
        self.assert_invalid_params(
            response, 'image_id_range',
            "Minimum ID (first number) should not be greater than the"
            " maximum ID (second number).")

        # Equal bounds are OK.
        response = self.get_browse(
            image_id_range=f'13_13')
        self.assert_not_invalid_params(response)

    def test_image_id_range_after_submit(self):
        id_range = f'{self.img1.pk}_{self.img3.pk}'
        response = self.get_browse(
            image_id_range=id_range,
        )
        self.assert_not_invalid_params(response)

        search_field = self.get_search_form_field(response, 'image_id_range')
        self.assertIsNone(
            search_field,
            msg="This field isn't supposed to be in the search form")

    def test_dont_get_other_sources_images_id_range(self):
        source_2 = self.create_source(self.user)
        other_image = self.upload_image(self.user, source_2)

        # Just source 1's applicable images, not source 2's
        response = self.get_browse(
            image_id_range=f'{self.img4.pk}_{other_image.pk}')
        self.assert_browse_results(
            response, [self.img4, self.img5])


class SubmitEditsTest(BaseBrowseMetadataTest):
    """
    Test the metadata edit functionality.
    """
    def submit_edits(self, post_data):
        self.client.force_login(self.user)
        url = reverse('edit_metadata_ajax', args=[self.source.pk])
        return self.client.post(url, post_data)

    def test_submit_edits(self):
        """
        Submit metadata edits and see if they go through.
        """
        image_1 = self.images[0]
        post_data = {
            'form-TOTAL_FORMS': 1,
            'form-INITIAL_FORMS': 1,
            'form-MAX_NUM_FORMS': '',
            'form-0-id': image_1.metadata.pk,
            'form-0-name': 'new_name.arbitrary_ext',
            'form-0-photo_date': '2004-07-19',
            'form-0-height_in_cm': 325,
            'form-0-latitude': '68',
            'form-0-longitude': '-25.908',
            'form-0-depth': "57.1m",
            'form-0-camera': "Canon ABC94",
            'form-0-photographer': "",
            'form-0-water_quality': "",
            'form-0-strobes': "",
            'form-0-framing': "",
            'form-0-balance': "Balance card A",
            'form-0-comments': "These, are; some<\n test/ comments.",
        }

        response = self.submit_edits(post_data)

        # Response should be as expected.
        self.assertStatusOK(response)
        response_json = response.json()
        self.assertEqual(response_json['status'], 'success')

        image_1.metadata.refresh_from_db()
        self.assertEqual('new_name.arbitrary_ext', image_1.metadata.name)
        self.assertEqual(
            datetime.date(2004, 7, 19), image_1.metadata.photo_date)
        self.assertEqual(325, image_1.metadata.height_in_cm)
        self.assertEqual('68', image_1.metadata.latitude)
        self.assertEqual('-25.908', image_1.metadata.longitude)
        self.assertEqual("57.1m", image_1.metadata.depth)
        self.assertEqual("Canon ABC94", image_1.metadata.camera)
        self.assertEqual("", image_1.metadata.photographer)
        self.assertEqual("", image_1.metadata.water_quality)
        self.assertEqual("", image_1.metadata.strobes)
        self.assertEqual("", image_1.metadata.framing)
        self.assertEqual("Balance card A", image_1.metadata.balance)
        self.assertEqual(
            "These, are; some<\n test/ comments.", image_1.metadata.comments)

    def test_submit_errors(self):
        """
        Submit metadata edits with errors.

        Ensure that valid edits in the same submission don't get saved,
        and ensure the error messages are as expected.
        """
        image_1 = self.images[0]
        image_2 = self.images[1]
        post_data = {
            'form-TOTAL_FORMS': 2,
            'form-INITIAL_FORMS': 2,
            'form-MAX_NUM_FORMS': '',
            'form-0-id': image_1.metadata.pk,
            'form-0-name': image_1.metadata.name,
            'form-0-photo_date': '2007-04-08',    # Valid edit
            'form-0-height_in_cm': '',
            'form-0-latitude': '',
            'form-0-longitude': '',
            'form-0-depth': "",
            'form-0-camera': "",
            'form-0-photographer': "",
            'form-0-water_quality': "",
            'form-0-strobes': "",
            'form-0-framing': "",
            'form-0-balance': "",
            'form-0-comments': "",
            'form-1-id': image_2.metadata.pk,
            'form-1-name': image_2.metadata.name,
            'form-1-photo_date': '205938',    # Not valid
            'form-1-height_in_cm': '-20',    # Not valid
            'form-1-latitude': '',
            'form-1-longitude': '',
            'form-1-depth': "",
            'form-1-camera': "",
            'form-1-photographer': "",
            'form-1-water_quality': "",
            'form-1-strobes': "",
            'form-1-framing': "",
            'form-1-balance': "Balance card A",    # Valid edit
            'form-1-comments': "",
        }

        response = self.submit_edits(post_data)

        # Response should be as expected.
        self.assertStatusOK(response)
        response_json = response.json()
        self.assertEqual(response_json['status'], 'error')

        # Response errors should be as expected.
        # The error order is undefined, so we won't check for order.
        response_error_dict = dict([
            (e['fieldId'], e['errorMessage'])
            for e in response_json['errors']
        ])
        expected_error_dict = dict()
        expected_error_dict['id_form-1-photo_date'] = (
            image_2.metadata.name
            + " | Date"
            + " | Enter a valid date.")
        expected_error_dict['id_form-1-height_in_cm'] = (
            image_2.metadata.name
            + " | Height (cm)"
            + " | Ensure this value is greater than or equal to 0.")
        self.assertDictEqual(
            response_error_dict,
            expected_error_dict,
        )

        # No edits should have gone through.
        image_1.metadata.refresh_from_db()
        image_2.metadata.refresh_from_db()
        self.assertEqual(image_1.metadata.photo_date, None)
        self.assertEqual(image_2.metadata.balance, "")

    def test_dupe_name_errors(self):
        """
        Submit metadata edits with duplicate-image-name errors.
        """
        post_data = {
            'form-TOTAL_FORMS': 4,
            'form-INITIAL_FORMS': 4,
            'form-MAX_NUM_FORMS': '',

            'form-0-id': self.images[0].metadata.pk,
            # Dupe with [4], which is not in the form
            'form-0-name': self.images[4].metadata.name,
            'form-0-photo_date': '2007-04-08',
            'form-0-height_in_cm': '',
            'form-0-latitude': '',
            'form-0-longitude': '',
            'form-0-depth': "",
            'form-0-camera': "",
            'form-0-photographer': "",
            'form-0-water_quality': "",
            'form-0-strobes': "",
            'form-0-framing': "",
            'form-0-balance': "",
            'form-0-comments': "",

            'form-1-id': self.images[1].metadata.pk,
            # Dupe with [2], which is also in the form
            'form-1-name': 'new_name_23',
            'form-1-photo_date': '2007-04-08',
            'form-1-height_in_cm': '',
            'form-1-latitude': '',
            'form-1-longitude': '',
            'form-1-depth': "",
            'form-1-camera': "",
            'form-1-photographer': "",
            'form-1-water_quality': "",
            'form-1-strobes': "",
            'form-1-framing': "",
            'form-1-balance': "",
            'form-1-comments': "",

            'form-2-id': self.images[2].metadata.pk,
            # Dupe with [1], which is also in the form
            'form-2-name': 'new_name_23',
            'form-2-photo_date': '2007-04-08',
            'form-2-height_in_cm': '',
            'form-2-latitude': '',
            'form-2-longitude': '',
            'form-2-depth': "",
            'form-2-camera': "",
            'form-2-photographer': "",
            'form-2-water_quality': "",
            'form-2-strobes': "",
            'form-2-framing': "",
            'form-2-balance': "",
            'form-2-comments': "",

            'form-3-id': self.images[3].metadata.pk,
            # Not dupe
            'form-3-name': 'new_name_4',
            'form-3-photo_date': '2007-04-08',
            'form-3-height_in_cm': '',
            'form-3-latitude': '',
            'form-3-longitude': '',
            'form-3-depth': "",
            'form-3-camera': "",
            'form-3-photographer': "",
            'form-3-water_quality': "",
            'form-3-strobes': "",
            'form-3-framing': "",
            'form-3-balance': "",
            'form-3-comments': "",
        }

        response = self.submit_edits(post_data)

        # Response should be as expected.
        self.assertStatusOK(response)
        response_json = response.json()
        self.assertEqual(response_json['status'], 'error')

        # Response errors should be as expected.
        # The error order is undefined, so we won't check for order.
        response_error_dict = dict([
            (e['fieldId'], e['errorMessage'])
            for e in response_json['errors']
        ])
        expected_error_dict = dict()
        expected_error_dict['id_form-0-name'] = (
            self.images[4].metadata.name
            + " | Name"
            + " | Same name as another image in the source or this form"
        )
        expected_error_dict['id_form-1-name'] = (
            'new_name_23'
            + " | Name"
            + " | Same name as another image in the source or this form"
        )
        expected_error_dict['id_form-2-name'] = (
            'new_name_23'
            + " | Name"
            + " | Same name as another image in the source or this form"
        )
        self.assertDictEqual(
            response_error_dict,
            expected_error_dict,
        )

        # No edits should have gone through.
        self.images[3].metadata.refresh_from_db()
        self.assertEqual(self.images[3].metadata.photo_date, None)

    def test_error_messages_containing_unicode(self):
        """
        Ensure error messages containing Unicode characters can be processed
        properly. For example, include Unicode in an image's name and trigger
        an error for that image.
        """
        image_1 = self.images[0]
        post_data = {
            'form-TOTAL_FORMS': 1,
            'form-INITIAL_FORMS': 1,
            'form-MAX_NUM_FORMS': '',
            'form-0-id': image_1.metadata.pk,
            'form-0-name': 'あ.png',
            'form-0-photo_date': '2004',
            'form-0-height_in_cm': 325,
            'form-0-latitude': '68',
            'form-0-longitude': '-25.908',
            'form-0-depth': "57.1m",
            'form-0-camera': "Canon ABC94",
            'form-0-photographer': "",
            'form-0-water_quality': "",
            'form-0-strobes': "",
            'form-0-framing': "",
            'form-0-balance': "Balance card A",
            'form-0-comments': "These, are; some<\n test/ comments.",
        }

        response = self.submit_edits(post_data)
        response_json = response.json()

        # The error order is undefined, so we won't check for order.
        response_error_dict = dict([
            (e['fieldId'], e['errorMessage'])
            for e in response_json['errors']
        ])
        expected_error_dict = dict()
        expected_error_dict['id_form-0-photo_date'] = (
            "あ.png"
            + " | Date"
            + " | Enter a valid date."
        )
        self.assertDictEqual(response_error_dict, expected_error_dict)

    def test_deny_metadata_ids_of_other_source(self):
        """
        Attempts to submit metadata IDs of another source should be rejected.
        Otherwise there's a security hole.

        Specifically, what happens here is that the edits to the outside-ID
        object are ignored, and no error is returned. This is the expected
        behavior when an ID is outside of the Django formset's queryset.
        """
        source_2 = self.create_source(self.user)
        image_s2 = self.upload_image(self.user, source_2)
        old_name = image_s2.metadata.name

        post_data = {
            'form-TOTAL_FORMS': 1,
            'form-INITIAL_FORMS': 1,
            'form-MAX_NUM_FORMS': '',
            # Metadata ID from another source
            'form-0-id': image_s2.metadata.pk,
            'form-0-name': 'other_source_image.png',
            'form-0-photo_date': '2007-04-08',
            'form-0-height_in_cm': '',
            'form-0-latitude': '',
            'form-0-longitude': '',
            'form-0-depth': "",
            'form-0-camera': "",
            'form-0-photographer': "",
            'form-0-water_quality': "",
            'form-0-strobes': "",
            'form-0-framing': "",
            'form-0-balance': "",
            'form-0-comments': "",
        }

        response = self.submit_edits(post_data)

        # Response should be as expected.
        self.assertStatusOK(response)
        response_json = response.json()
        self.assertEqual(response_json['status'], 'success')

        # No edits should have gone through.
        image_s2.metadata.refresh_from_db()
        self.assertEqual(image_s2.metadata.name, old_name)
        self.assertEqual(image_s2.metadata.photo_date, None)
