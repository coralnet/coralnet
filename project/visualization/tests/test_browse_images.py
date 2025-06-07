import datetime
import re

from bs4 import BeautifulSoup
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.utils import get_alleviate_user, get_imported_user
from lib.tests.utils import BasePermissionTest
from sources.models import Source
from .utils import BaseBrowsePageTest, BrowseActionsFormTest

tz = timezone.get_current_timezone()


class PermissionTest(BasePermissionTest):
    """
    Test page permissions.
    """
    def test_browse_images(self):
        url = reverse('browse_images', args=[self.source.pk])
        template = 'visualization/browse_images.html'

        self.source_to_private()
        self.assertPermissionLevel(url, self.SOURCE_VIEW, template=template)
        self.source_to_public()
        self.assertPermissionLevel(url, self.SIGNED_OUT, template=template)


class AnnotateFormAvailabilityTest(BrowseActionsFormTest):
    form_id = 'annotate-all-form'

    def test_available(self):
        self.client.force_login(self.user)
        response = self.client.get(self.browse_url)
        self.assert_form_available(response)

    def test_view_perms_only(self):
        self.client.force_login(self.user_viewer)
        response = self.client.get(self.browse_url)
        self.assert_form_absent(response)


class BaseBrowseImagesTest(BaseBrowsePageTest):

    url_name = 'browse_images'

    @staticmethod
    def thumb_wrapper_to_image_id(thumb_wrapper):
        anchor = thumb_wrapper.find('a')
        # The only number in the thumbnail's link should be the
        # image ID.
        match = re.search(r'(\d+)', anchor.attrs.get('href'))
        return int(match.groups()[0])

    def assert_browse_results(self, response, expected_images, msg_prefix=None):
        response_soup = BeautifulSoup(response.content, 'html.parser')
        thumb_wrappers = response_soup.find_all('span', class_='thumb_wrapper')
        actual_ids = [
            self.thumb_wrapper_to_image_id(thumb_wrapper)
            for thumb_wrapper in thumb_wrappers
        ]

        expected_ids = [image.pk for image in expected_images]
        self.assertListEqual(
            actual_ids, expected_ids,
            # This is a message prefix, not a message replacement,
            # as long as longMessage is True.
            msg=msg_prefix,
        )

    def assert_no_results(self, response):
        response_soup = BeautifulSoup(response.content, 'html.parser')
        self.assertIsNone(
            response_soup.find('span', class_='thumb_wrapper'))

    def assert_multi_field_values(
        self, response, field_name, expected_values
    ):
        for index, expected_value in enumerate(expected_values):

            subfield_name = f'{field_name}_{index}'

            search_field = self.get_search_form_field(
                response, subfield_name)
            self.assertEqual(
                self.get_field_value(search_field), expected_value,
                msg=f"{subfield_name} field value should be as expected"
                    f" in the search form")

            hidden_field = self.get_hidden_field(response, subfield_name)
            if expected_value == '':
                self.assertIsNone(
                    hidden_field,
                    msg=f"Hidden form should not have {subfield_name} field")
            else:
                self.assertEqual(
                    self.get_field_value(hidden_field), expected_value,
                    msg=f"{subfield_name} field value should be as"
                        f" expected in the hidden form")


class BasicFiltersTest(BaseBrowseImagesTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.img1, cls.img2, cls.img3, cls.img4, cls.img5 = cls.images

    def test_no_submit(self):
        """Page landing, no search performed yet."""
        response = self.get_browse()
        self.assert_browse_results(
            response, self.images, msg_prefix="Should have all images")

    def test_default_search(self):
        response = self.get_browse(**self.default_search_params)
        self.assert_browse_results(
            response, self.images, msg_prefix="Should have all images")

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
        source_2 = self.create_source(self.user)
        self.upload_image(self.user, source_2)

        # Just source 1's images, not source 2's
        response = self.get_browse()
        self.assert_browse_results(response, self.images)

    def test_post_request(self):
        self.client.force_login(self.user)

        response = self.client.post(self.url, {}, follow=False)
        self.assertRedirects(
            response, self.url,
            msg_prefix="Should redirect back to browse images")

        response = self.client.post(self.url, {}, follow=True)
        self.assertContains(
            response, "An error occurred; please try another search.",
            msg_prefix="Should show a message indicating the search didn't"
                       " actually work due to POST being used")

    # Specific filters.

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

    def test_filter_by_annotation_status_unconfirmed(self):
        robot = self.create_robot(self.source)
        # 2 points per image
        # confirmed, unconfirmed, unconfirmed, partial
        self.add_annotations(self.user, self.img1, {1: 'A', 2: 'B'})
        self.add_robot_annotations(robot, self.img2)
        self.add_robot_annotations(robot, self.img3)
        self.add_annotations(self.user, self.img4, {1: 'B'})

        response = self.get_browse(annotation_status='unconfirmed')
        self.assert_browse_results(
            response, [self.img2, self.img3])

    def test_filter_by_annotation_status_unclassified(self):
        robot = self.create_robot(self.source)
        # 2 points per image
        # confirmed, unconfirmed, partial (counts as unclassified)
        self.add_annotations(self.user, self.img1, {1: 'A', 2: 'B'})
        self.add_robot_annotations(robot, self.img2)
        self.add_annotations(self.user, self.img3, {1: 'B'})

        response = self.get_browse(annotation_status='unclassified')
        self.assert_browse_results(
            response, [self.img3, self.img4, self.img5])

    def test_filter_by_image_name_one_token(self):
        self.update_multiple_metadatas(
            'name',
            [(self.img1, 'abcxyzdef.png'),
             (self.img2, 'XYZ.jpg'),
             (self.img3, 'xydefz.png')])

        response = self.get_browse(image_name='xyz')
        self.assert_browse_results(
            response, [self.img1, self.img2])

    def test_filter_by_image_name_two_tokens(self):
        # Both search tokens must be present
        self.update_multiple_metadatas(
            'name',
            [(self.img1, 'ABCXYZ.jpg'),
             (self.img2, 'xyz.abc'),
             (self.img3, 'abc.png'),
             (self.img4, 'xyz.jpg')])

        response = self.get_browse(image_name='abc xyz')
        self.assert_browse_results(
            response, [self.img1, self.img2])

    def test_filter_by_image_name_punctuation(self):
        # Punctuation is considered part of search tokens
        self.update_multiple_metadatas(
            'name',
            [(self.img1, '1-1.png'),
             (self.img2, '1*1.png'),
             (self.img3, '2-1-1.jpg'),
             (self.img4, '1-1-2.png')])

        response = self.get_browse(image_name='1-1.')
        self.assert_browse_results(
            response, [self.img1, self.img3])

    def test_filter_by_multiple_fields(self):
        self.update_multiple_metadatas(
            'photo_date',
            [(self.img1, datetime.date(2012, 3, 9)),
             (self.img2, datetime.date(2013, 3, 10)),
             (self.img3, datetime.date(2012, 5, 17)),
             (self.img4, datetime.date(2013, 10, 12))])
        self.update_multiple_metadatas(
            'aux4',
            [(self.img1, 'A4'),
             (self.img2, 'A4'),
             (self.img3, 'A5'),
             (self.img4, 'A6')])

        response = self.get_browse(
            photo_date_0='year', photo_date_1=2013, aux4='A4')
        self.assert_browse_results(
            response, [self.img2])


class FormInitializationTest(BaseBrowseImagesTest):

    def test_no_submit(self):
        """Page landing, no search performed yet."""
        response = self.get_browse()

        self.assertIsNotNone(
            self.get_search_form_field(response, 'image_name'),
            msg="Basic search fields should be present")
        self.assert_no_hidden_fields(response)
        self.assert_not_invalid_params(response)

    @override_settings(
        # Ensures we do have multiple pages of results.
        BROWSE_DEFAULT_THUMBNAILS_PER_PAGE=3,
    )
    def test_no_submit_page_2(self):
        """
        Page landing, then move to page 2, without searching.
        More detailed tests of multiple pages are in ResultsAndPagesTest.
        """
        response = self.get_browse(page=2)

        # Same checks as page 1
        self.assertIsNotNone(
            self.get_search_form_field(response, 'image_name'),
            msg="Basic search fields should be present")
        self.assert_no_hidden_fields(response)
        self.assert_not_invalid_params(response)

    def test_default_search(self):
        response = self.get_browse(**self.default_search_params)

        self.assertIsNotNone(
            self.get_search_form_field(response, 'image_name'),
            msg="Basic search fields should be present")
        self.assert_has_hidden_fields(response)
        self.assert_not_invalid_params(response)

    def test_basic_field_after_submit(self):
        # Ensure the results of the search aren't completely empty,
        # so that the hidden form is rendered.
        self.update_multiple_metadatas(
            'name',
            [(self.images[0], 'DSC_0001.jpg')])

        response = self.get_browse(image_name='DSC')

        search_field = self.get_search_form_field(response, 'image_name')
        self.assertEqual(
            search_field.attrs.get('value'), 'DSC',
            msg="Field value should be present in the search form")

        hidden_field = self.get_hidden_field(response, 'image_name')
        self.assertEqual(
            hidden_field.attrs.get('value'), 'DSC',
            msg="Field value should be present in the hidden form")

    def test_blank_basic_field_after_submit(self):
        response = self.get_browse(search='true', image_name='')

        search_field = self.get_search_form_field(response, 'image_name')
        self.assertIsNone(
            search_field.attrs.get('value'),
            msg="Blank field should be present in the search form")

        hidden_field = self.get_hidden_field(response, 'image_name')
        self.assertIsNone(
            hidden_field,
            msg="Field should not be present in the hidden form")

    # The following field-specific test classes have further field
    # initialization tests.


class AuxMetadataSearchTest(BaseBrowseImagesTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.img1, cls.img2, cls.img3, cls.img4, cls.img5 = cls.images

    def test_filter_by_aux1(self):
        self.update_multiple_metadatas(
            'aux1',
            [(self.img1, 'Site1'),
             (self.img2, 'Site3'),
             (self.img3, 'Site3')])

        response = self.get_browse(aux1='Site3')
        self.assert_browse_results(
            response, [self.img2, self.img3])

    def test_filter_by_aux1_none(self):
        self.update_multiple_metadatas(
            'aux1',
            [(self.img1, 'Site1'),
             (self.img2, 'Site3')])

        response = self.get_browse(aux1='(none)')
        self.assert_browse_results(
            response, [self.img3, self.img4, self.img5])

    def test_aux1_choices(self):
        self.update_multiple_metadatas(
            'aux1',
            [(self.img1, 'Site1'),
             (self.img2, 'Site3')])

        response = self.get_browse()
        self.assert_search_field_choices(
            response, 'aux1', ['', 'Site1', 'Site3', '(none)'])

    def test_filter_by_aux5(self):
        self.update_multiple_metadatas(
            'aux5',
            [(self.img1, 'C'),
             (self.img2, 'D'),
             (self.img3, 'D')])

        response = self.get_browse(aux5='D')
        self.assert_browse_results(
            response, [self.img2, self.img3])

    def test_only_show_metadata_field_if_multiple_values(self):
        # aux1 is blank for every image
        self.update_multiple_metadatas(
            'aux1', ['', '', '', '', ''])
        # aux2 has multiple unique non-blank values
        self.update_multiple_metadatas(
            'aux2',
            ['5m', '10m', '10m', '5m', '10m'])
        # aux3 has the same non-blank value for every image
        self.update_multiple_metadatas(
            'aux3',
            ['Transect4', 'Transect4', 'Transect4', 'Transect4', 'Transect4'])
        # aux4 has one unique non-blank value as well as blanks
        self.update_multiple_metadatas(
            'aux4',
            ['', '', 'Q3', '', ''])

        response = self.get_browse()

        self.assertIsNone(self.get_search_form_field(response, 'aux1'))
        self.assertIsNotNone(self.get_search_form_field(response, 'aux2'))
        self.assertIsNone(self.get_search_form_field(response, 'aux3'))
        self.assertIsNotNone(self.get_search_form_field(response, 'aux4'))


class DateSearchTest(BaseBrowseImagesTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.img1, cls.img2, cls.img3, cls.img4, cls.img5 = cls.images

    # Photo date

    def test_photo_date_type_choices(self):
        response = self.get_browse()

        self.assert_search_field_choices(
            response, 'photo_date_0',
            [('', "Any"),
             ('year', "Year"),
             ('date', "Exact date"),
             ('date_range', "Date range"),
             ('(none)', "(None)")],
        )

    def test_filter_by_photo_date_any(self):
        self.update_multiple_metadatas(
            'photo_date',
            [(self.img1, datetime.date(2011, 12, 28)),
             (self.img2, datetime.date(2012, 1, 13))])
        # 3 other images left with no date

        response = self.get_browse(photo_date_0='')
        self.assert_browse_results(
            response, self.images,
            msg_prefix="Should include both non-null and null dates")

    def test_filter_by_photo_date_none(self):
        self.update_multiple_metadatas(
            'photo_date',
            [(self.img1, datetime.date(2011, 12, 28)),
             (self.img2, datetime.date(2012, 1, 13)),
             (self.img3, datetime.date(2013, 8, 4))])
        # 2 other images left with no date

        response = self.get_browse(photo_date_0='(none)')
        self.assert_browse_results(
            response, [self.img4, self.img5])

    def test_filter_by_photo_date_year(self):
        self.update_multiple_metadatas(
            'photo_date',
            [(self.img1, datetime.date(2011, 12, 28)),
             (self.img2, datetime.date(2012, 1, 13)),
             (self.img3, datetime.date(2012, 8, 4))])

        response = self.get_browse(photo_date_0='year', photo_date_1=2012)
        self.assert_browse_results(
            response, [self.img2, self.img3])

    def test_photo_date_year_choices(self):
        self.update_multiple_metadatas(
            'photo_date',
            [(self.img1, datetime.date(2011, 12, 28)),
             (self.img2, datetime.date(2012, 1, 13)),
             (self.img3, datetime.date(2013, 8, 4))])

        response = self.get_browse()
        self.assert_search_field_choices(
            response, 'photo_date_1', ['', '2011', '2012', '2013'])

    def test_filter_by_photo_date_exact_date(self):
        self.update_multiple_metadatas(
            'photo_date',
            [(self.img1, datetime.date(2012, 1, 12)),
             (self.img2, datetime.date(2012, 1, 13)),
             (self.img3, datetime.date(2012, 1, 13))])
        # 2 other images left with no date

        response = self.get_browse(
            photo_date_0='date', photo_date_2=datetime.date(2012, 1, 13))
        self.assert_browse_results(
            response, [self.img2, self.img3])

    def test_filter_by_photo_date_range(self):
        self.update_multiple_metadatas(
            'photo_date',
            [(self.img1, datetime.date(2012, 3, 9)),
             (self.img2, datetime.date(2012, 3, 10)),
             (self.img3, datetime.date(2012, 3, 15)),
             (self.img4, datetime.date(2012, 3, 20)),
             (self.img5, datetime.date(2012, 3, 21))])

        response = self.get_browse(
            photo_date_0='date_range',
            photo_date_3=datetime.date(2012, 3, 10),
            photo_date_4=datetime.date(2012, 3, 20),
        )
        self.assert_browse_results(
            response, [self.img2, self.img3, self.img4])

    def test_photo_date_negative_range(self):
        self.update_multiple_metadatas(
            'photo_date',
            [(self.img1, datetime.date(2012, 3, 9)),
             (self.img2, datetime.date(2012, 3, 10))])

        response = self.get_browse(
            photo_date_0='date_range',
            photo_date_3=datetime.date(2012, 3, 10),
            photo_date_4=datetime.date(2012, 3, 9),
        )
        self.assert_browse_results(response, [])

    def test_photo_date_type_invalid(self):
        response = self.get_browse(photo_date_0='abc')
        self.assert_invalid_params(
            response, 'photo_date',
            "Select a valid choice. abc is not one of the available choices.")

    def test_photo_date_year_missing(self):
        response = self.get_browse(photo_date_0='year')
        self.assert_invalid_params(
            response, 'photo_date', "Must specify a year.")

    def test_photo_date_year_invalid(self):
        response = self.get_browse(
            photo_date_0='year', photo_date_1='not a year')
        self.assert_invalid_params(
            response, 'photo_date',
            "Select a valid choice. not a year is not one of the"
            " available choices.")

    def test_photo_date_exact_date_missing(self):
        response = self.get_browse(photo_date_0='date')
        self.assert_invalid_params(
            response, 'photo_date', "Must specify a date.")

    def test_photo_date_exact_date_invalid(self):
        response = self.get_browse(
            photo_date_0='date', photo_date_2='not a date')
        self.assert_invalid_params(
            response, 'photo_date', "Enter a valid date.")

    def test_photo_date_start_date_missing(self):
        response = self.get_browse(
            photo_date_0='date_range',
            photo_date_4=datetime.date(2012, 3, 10),
        )
        self.assert_invalid_params(
            response, 'photo_date', "Must specify a start date.")

    def test_photo_date_end_date_missing(self):
        response = self.get_browse(
            photo_date_0='date_range',
            photo_date_3=datetime.date(2012, 3, 10),
        )
        self.assert_invalid_params(
            response, 'photo_date', "Must specify an end date.")

    # Last annotation date

    def test_annotation_date_type_choices(self):
        response = self.get_browse()
        self.assert_search_field_choices(
            response, 'last_annotated_0',
            [('', "Any"),
             ('year', "Year"),
             ('date', "Exact date"),
             ('date_range', "Date range"),
             ('(none)', "(None)")],
        )

    def test_filter_by_annotation_date_any(self):
        self.set_last_annotation(
            self.img1, dt=datetime.datetime(2011, 12, 28, tzinfo=tz))
        self.set_last_annotation(
            self.img2, dt=datetime.datetime(2012, 1, 13, tzinfo=tz))
        # 3 other images left with no last annotation

        response = self.get_browse(last_annotated_0='')
        self.assert_browse_results(
            response, self.images,
            msg_prefix="Should include both annotated"
                       " and non-annotated images")

    def test_filter_by_annotation_date_none(self):
        self.set_last_annotation(
            self.img1, dt=datetime.datetime(2011, 12, 28, tzinfo=tz))
        self.set_last_annotation(
            self.img2, dt=datetime.datetime(2012, 1, 13, tzinfo=tz))
        self.set_last_annotation(
            self.img3, dt=datetime.datetime(2013, 8, 4, tzinfo=tz))
        # 2 other images left with no last annotation

        response = self.get_browse(last_annotated_0='(none)')
        self.assert_browse_results(
            response, [self.img4, self.img5])

    def test_annotation_date_year_choices(self):
        self.set_last_annotation(
            self.img1, dt=datetime.datetime(2011, 12, 28, tzinfo=tz))
        self.set_last_annotation(
            self.img2, dt=datetime.datetime(2012, 1, 13, tzinfo=tz))

        self.source.create_date = datetime.datetime(2010, 1, 1, tzinfo=tz)
        self.source.save()

        current_year = timezone.now().year

        response = self.get_browse()
        # Choices should be based on the source create date and the
        # current year, not based on existing annotation dates. It's done this
        # way for a slight speed optimization.
        self.assert_search_field_choices(
            response, 'last_annotated_1',
            [''] + [str(year) for year in range(2010, current_year+1)],
        )

    def test_filter_by_annotation_date_exact_date(self):
        # The entire 24 hours of the given date should be included.
        # As an implementation detail, 00:00 of the next day is also included,
        # so we just make sure 00:01 of the next day isn't in.
        self.set_last_annotation(
            self.img1, dt=datetime.datetime(2012, 1, 12, 23, 59, tzinfo=tz))
        self.set_last_annotation(
            self.img2, dt=datetime.datetime(2012, 1, 13, 0, 0, tzinfo=tz))
        self.set_last_annotation(
            self.img3, dt=datetime.datetime(2012, 1, 13, 23, 59, tzinfo=tz))
        self.set_last_annotation(
            self.img4, dt=datetime.datetime(2012, 1, 14, 0, 1, tzinfo=tz))

        response = self.get_browse(
            last_annotated_0='date',
            last_annotated_2=datetime.date(2012, 1, 13),
        )
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

    def test_date_year_after_submit(self):
        self.update_multiple_metadatas(
            'photo_date',
            [(self.img1, datetime.date(2012, 3, 6))])

        response = self.get_browse(photo_date_0='year', photo_date_1='2012')

        self.assert_multi_field_values(
            response, 'photo_date', ['year', '2012', '', '', ''])

    def test_exact_date_after_submit(self):
        self.update_multiple_metadatas(
            'photo_date',
            [(self.img1, datetime.date(2012, 3, 6))])

        response = self.get_browse(
            photo_date_0='date', photo_date_2=datetime.date(2012, 3, 6))

        self.assert_multi_field_values(
            response, 'photo_date', ['date', '', '2012-03-06', '', ''])

    def test_date_range_after_submit(self):
        self.update_multiple_metadatas(
            'photo_date',
            [(self.img1, datetime.date(2012, 10, 21))])

        response = self.get_browse(
            photo_date_0='date_range',
            photo_date_3=datetime.date(2012, 3, 6),
            photo_date_4=datetime.date(2013, 4, 7),
        )

        self.assert_multi_field_values(
            response, 'photo_date',
            ['date_range', '', '', '2012-03-06', '2013-04-07'])


class LastAnnotatorSearchTest(BaseBrowseImagesTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.img1, cls.img2, cls.img3, cls.img4, cls.img5 = cls.images

    def test_filter_by_annotator_any(self):
        # Regular user
        self.add_annotations(self.user, self.img1, {1: 'A', 2: 'B'})
        # Imported
        self.set_last_annotation(self.img2, annotator=get_imported_user())
        # Alleviate
        self.set_last_annotation(self.img3, annotator=get_alleviate_user())
        # Machine
        robot = self.create_robot(self.source)
        self.add_robot_annotations(robot, self.img4)

        response = self.get_browse(last_annotator_0='')
        self.assert_browse_results(
            response, self.images,
            msg_prefix="Should include both annotated"
                       " and non-annotated images")

    def test_filter_by_annotator_tool_any_user(self):
        # Tool user
        self.add_annotations(self.user, self.img1, {1: 'A', 2: 'B'})

        # Another tool user
        user2 = self.create_user()
        self.add_source_member(
            self.user, self.source, user2, Source.PermTypes.EDIT.code)
        self.add_annotations(user2, self.img2, {1: 'A', 2: 'B'})

        # Non annotation tool
        self.set_last_annotation(self.img3, annotator=get_imported_user())
        self.set_last_annotation(self.img4, annotator=get_alleviate_user())
        robot = self.create_robot(self.source)
        self.add_robot_annotations(robot, self.img5)

        # Unannotated
        self.upload_image(self.user, self.source)

        response = self.get_browse(last_annotator_0='annotation_tool')
        self.assert_browse_results(
            response, [self.img1, self.img2])

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

    def test_annotator_tool_choices(self):
        self.add_annotations(self.user, self.img1, {1: 'A', 2: 'B'})

        # We ensure self.user2's username is alphabetically later than
        # self.user's. (The choices are sorted by username.)
        user2 = self.create_user(username=self.user.username + '_')
        self.add_source_member(
            self.user, self.source, user2, Source.PermTypes.EDIT.code)
        self.add_annotations(user2, self.img2, {1: 'A', 2: 'B'})

        user3 = self.create_user()
        self.add_source_member(
            self.user, self.source, user3, Source.PermTypes.EDIT.code)

        response = self.get_browse()
        # Choices should be based on existing annotations in the source, not
        # based on the source's member list. So, no user3.
        self.assert_search_field_choices(
            response, 'last_annotator_1',
            [('', "Any user"),
             (str(self.user.pk), self.user.username),
             (str(user2.pk), user2.username)],
        )

    def test_filter_by_annotator_alleviate(self):
        self.add_annotations(self.user, self.img1, {1: 'A', 2: 'B'})
        self.set_last_annotation(self.img2, annotator=get_imported_user())
        self.set_last_annotation(self.img3, annotator=get_alleviate_user())
        robot = self.create_robot(self.source)
        self.add_robot_annotations(robot, self.img4)

        response = self.get_browse(last_annotator_0='alleviate')
        self.assert_browse_results(
            response, [self.img3])

    def test_filter_by_annotator_importing(self):
        self.add_annotations(self.user, self.img1, {1: 'A', 2: 'B'})
        self.set_last_annotation(self.img2, annotator=get_imported_user())
        self.set_last_annotation(self.img3, annotator=get_alleviate_user())
        robot = self.create_robot(self.source)
        self.add_robot_annotations(robot, self.img4)

        response = self.get_browse(last_annotator_0='imported')
        self.assert_browse_results(
            response, [self.img2])

    def test_filter_by_annotator_machine(self):
        self.add_annotations(self.user, self.img1, {1: 'A', 2: 'B'})
        self.set_last_annotation(self.img2, annotator=get_imported_user())
        self.set_last_annotation(self.img3, annotator=get_alleviate_user())
        robot = self.create_robot(self.source)
        self.add_robot_annotations(robot, self.img4)

        response = self.get_browse(last_annotator_0='machine')
        self.assert_browse_results(
            response, [self.img4])

    def test_filter_by_annotator_considering_latest_only(self):
        self.add_annotations(self.user, self.img1, {1: 'A', 2: 'B'})

        user2 = self.create_user()
        self.add_source_member(
            self.user, self.source, user2, Source.PermTypes.EDIT.code)
        self.add_annotations(user2, self.img1, {1: 'B'})

        # user isn't the latest annotator of any image now.
        response = self.get_browse(
            last_annotator_0='annotation_tool',
            last_annotator_1=self.user.pk,
        )
        self.assert_browse_results(
            response, [])
        # user2 is.
        response = self.get_browse(
            last_annotator_0='annotation_tool',
            last_annotator_1=user2.pk,
        )
        self.assert_browse_results(
            response, [self.img1])

    def test_annotator_non_tool_after_submit(self):
        self.set_last_annotation(self.img1, annotator=get_alleviate_user())

        response = self.get_browse(
            last_annotator_0='alleviate',
        )

        self.assert_multi_field_values(
            response, 'last_annotator', ['alleviate', ''])

    def test_annotator_tool_any_after_submit(self):
        self.add_annotations(self.user, self.img1, {1: 'A', 2: 'B'})

        response = self.get_browse(
            last_annotator_0='annotation_tool',
        )

        self.assert_multi_field_values(
            response, 'last_annotator', ['annotation_tool', ''])

    def test_annotator_tool_user_after_submit(self):
        self.add_annotations(self.user, self.img1, {1: 'A', 2: 'B'})

        response = self.get_browse(
            last_annotator_0='annotation_tool',
            last_annotator_1=self.user.pk,
        )

        self.assert_multi_field_values(
            response, 'last_annotator',
            ['annotation_tool', str(self.user.pk)])


class ImageIdsTest(BaseBrowseImagesTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.img1, cls.img2, cls.img3, cls.img4, cls.img5 = cls.images

    def test_filter_by_image_id_list(self):
        response = self.get_browse(
            image_id_list=f'{self.img2.pk}_{self.img3.pk}'
                           f'_{self.img5.pk}')
        self.assert_browse_results(
            response, [self.img2, self.img3, self.img5])

        # It's OK to have image IDs not in the source. Those will just
        # be ignored.
        response = self.get_browse(
            image_id_list=f'{self.img2.pk}_1000000000000'
                           f'_2000000000000')
        self.assert_browse_results(
            response, [self.img2])

    def test_non_integer_image_id_list(self):
        response = self.get_browse(
            image_id_list=f'{self.img2.pk}_a_{self.img5.pk}')
        self.assert_invalid_params(
            response, 'image_id_list',
            "Enter only digits separated by underscores.")

        response = self.get_browse(
            image_id_list=f'{self.img2.pk}_4.3_{self.img5.pk}')
        self.assert_invalid_params(
            response, 'image_id_list',
            "Enter only digits separated by underscores.")

    def test_image_id_list_max_length(self):
        response = self.get_browse(
            image_id_list='_'.join(['1'] * 100))
        self.assert_not_invalid_params(response)

        response = self.get_browse(
            image_id_list='_'.join(['1'] * 101))
        self.assert_invalid_params(
            response, 'image_id_list',
            "Too many ID numbers.")

    def test_dont_get_other_sources_images_id_list(self):
        source_2 = self.create_source(self.user)
        other_image = self.upload_image(self.user, source_2)

        # Just source 1's applicable images, not source 2's
        response = self.get_browse(
            image_id_list=f'{self.img2.pk}_{other_image.pk}'
                           f'_{self.img5.pk}')
        self.assert_browse_results(
            response, [self.img2, self.img5])

    def test_filter_by_image_id_range(self):
        """
        This field should be tested more thoroughly in edit-metadata
        where we are more expecting the field to be used.
        """
        response = self.get_browse(
            image_id_range=f'{self.img2.pk}_{self.img4.pk}')
        self.assert_browse_results(
            response, [self.img2, self.img3, self.img4])

    def test_image_id_list_after_submit(self):
        """
        Although this field can be used to filter the images,
        it's meant as a one-off search filter which is not combinable with
        other filters.
        Thus, the field should not be in the HTML search form.
        """
        id_list = f'{self.img1.pk}_{self.img2.pk}_{self.img3.pk}'
        response = self.get_browse(
            image_id_list=id_list,
        )
        self.assert_not_invalid_params(response)

        search_field = self.get_search_form_field(response, 'image_id_list')
        self.assertIsNone(
            search_field,
            msg="This field isn't supposed to be in the search form")

        hidden_field = self.get_hidden_field(response, 'image_id_list')
        self.assertEqual(
            hidden_field.attrs.get('value'), id_list,
            msg="Field value should be present in the hidden form")

    def test_image_id_range_after_submit(self):
        """
        Similar to image_id_list.
        """
        id_range = f'{self.img1.pk}_{self.img3.pk}'
        response = self.get_browse(
            image_id_range=id_range,
        )
        self.assert_not_invalid_params(response)

        search_field = self.get_search_form_field(response, 'image_id_range')
        self.assertIsNone(
            search_field,
            msg="This field isn't supposed to be in the search form")

        hidden_field = self.get_hidden_field(response, 'image_id_range')
        self.assertEqual(
            hidden_field.attrs.get('value'), id_range,
            msg="Field value should be present in the hidden form")


@override_settings(
    # Make processing of the full results, not of the page results,
    # dominate query count.
    BROWSE_DEFAULT_THUMBNAILS_PER_PAGE=2,
)
class ImageIdListQueriesTest(BaseBrowseImagesTest):

    setup_image_count = 80

    def test(self):
        id_list = '_'.join([str(image.pk) for image in self.images])

        # Should run less than 1 query per image.
        with self.assert_queries_less_than(self.setup_image_count):
            response = self.get_browse(
                image_id_list=id_list,
            )

        self.assert_browse_results(
            response, [self.images[0], self.images[1]],
            msg_prefix="Shouldn't have any issues preventing correct results",
        )


class SortTest(BaseBrowseImagesTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.img1, cls.img2, cls.img3, cls.img4, cls.img5 = cls.images

    def test_by_name(self):
        self.update_multiple_metadatas(
            'name',
            ['B', 'A', 'C', 'D', 'E'])

        response = self.get_browse(
            sort_method='',
            sort_direction='',
        )
        self.assert_browse_results(
            response, [self.images[i] for i in [1,0,2,3,4]])

        response = self.get_browse(
            sort_method='',
            sort_direction='desc',
        )
        self.assert_browse_results(
            response, [self.images[i] for i in [4,3,2,0,1]])

    def test_by_upload(self):
        response = self.get_browse(
            sort_method='upload_date',
            sort_direction='',
        )
        self.assert_browse_results(
            response, [self.images[i] for i in [0,1,2,3,4]])

        response = self.get_browse(
            sort_method='upload_date',
            sort_direction='desc',
        )
        self.assert_browse_results(
            response, [self.images[i] for i in [4,3,2,1,0]])

    def test_by_photo_date(self):
        self.update_multiple_metadatas(
            'photo_date',
            [datetime.date(2012, 3, 2),
             datetime.date(2012, 3, 1),
             None,
             None,
             datetime.date(2012, 3, 1)])
        # Null dates will be ordered after the ones with dates.
        # pk is the tiebreaker.

        response = self.get_browse(
            sort_method='photo_date',
            sort_direction='',
        )
        self.assert_browse_results(
            response, [self.images[i] for i in [1,4,0,2,3]])

        response = self.get_browse(
            sort_method='photo_date',
            sort_direction='desc',
        )
        self.assert_browse_results(
            response, [self.images[i] for i in [3,2,0,4,1]])

    def test_by_last_annotated(self):
        self.set_last_annotation(
            self.img1, dt=datetime.datetime(2012, 3, 2, 0, 0, tzinfo=tz))
        self.set_last_annotation(
            self.img2, dt=datetime.datetime(2012, 3, 1, 22, 15, tzinfo=tz))
        self.set_last_annotation(
            self.img5, dt=datetime.datetime(2012, 3, 1, 22, 15, tzinfo=tz))
        # Other 2 have null date and will be ordered after the ones with date.
        # pk is the tiebreaker.

        response = self.get_browse(
            sort_method='last_annotation_date',
            sort_direction='',
        )
        self.assert_browse_results(
            response, [self.images[i] for i in [1,4,0,2,3]])

        response = self.get_browse(
            sort_method='last_annotation_date',
            sort_direction='desc',
        )
        self.assert_browse_results(
            response, [self.images[i] for i in [3,2,0,4,1]])


@override_settings(
    # Require fewer uploads to get multiple pages of results.
    BROWSE_DEFAULT_THUMBNAILS_PER_PAGE=3,
)
class PagesTest(BaseBrowseImagesTest):

    setup_image_count = 10

    def test_one_page_results(self):
        self.update_multiple_metadatas(
            'aux1',
            [(self.images[0], 'Site1'),
             (self.images[1], 'Site1')])

        response = self.get_browse(aux1='Site1')
        self.assert_page_results(
            response, 2, "Showing 1-2 of 2", "Page 1 of 1")

    def test_multiple_pages_results(self):
        response = self.get_browse(photo_date_0='(none)')
        self.assert_page_results(
            response, 10, "Showing 1-3 of 10", "Page 1 of 4")

    def test_page_two(self):
        response = self.get_browse(photo_date_0='(none)', page=2)
        self.assert_page_results(
            response, 10, "Showing 4-6 of 10", "Page 2 of 4")

    def test_page_urls_no_params(self):
        response = self.get_browse(page=2)
        self.assert_page_links(response, '?page=1', '?page=3')

    def test_page_urls_with_search_params(self):
        response = self.get_browse(
            annotation_status='unclassified',
            page=2,
        )
        self.assert_page_links(
            response,
            '?annotation_status=unclassified&page=1',
            '?annotation_status=unclassified&page=3',
        )


class ImageStatusIndicatorTest(BaseBrowseImagesTest):
    """
    Test the border styling which indicates the status of each image.
    """
    setup_image_count = 4

    def test_status_indicator(self):
        robot = self.create_robot(self.source)

        img_unannotated = self.images[0]

        img_unconfirmed = self.images[1]
        self.add_robot_annotations(robot, img_unconfirmed)

        img_partially_confirmed = self.images[2]
        self.add_robot_annotations(robot, img_partially_confirmed)
        self.add_annotations(self.user, img_partially_confirmed, {1: 'A'})

        img_confirmed = self.images[3]
        self.add_robot_annotations(robot, img_confirmed)
        self.add_annotations(self.user, img_confirmed, {1: 'A', 2: 'B'})

        response = self.get_browse()

        # Check that each image is rendered with the expected styling.

        expected_thumb_set = {
            (reverse('image_detail', args=[img_unannotated.pk]),
             'thumb unclassified media-async'),
            (reverse('image_detail', args=[img_unconfirmed.pk]),
             'thumb unconfirmed media-async'),
            (reverse('image_detail', args=[img_partially_confirmed.pk]),
             'thumb unconfirmed media-async'),
            (reverse('image_detail', args=[img_confirmed.pk]),
             'thumb confirmed media-async'),
        }

        response_soup = BeautifulSoup(response.content, 'html.parser')
        thumb_wrappers = response_soup.find_all('span', class_='thumb_wrapper')
        actual_thumb_set = set()
        for thumb_wrapper in thumb_wrappers:
            a_element = thumb_wrapper.find('a')
            img_element = thumb_wrapper.find('img')
            actual_thumb_set.add(
                (a_element.attrs.get('href'),
                 ' '.join(img_element.attrs.get('class')))
            )
        self.assertSetEqual(expected_thumb_set, actual_thumb_set)
