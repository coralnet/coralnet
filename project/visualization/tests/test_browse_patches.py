import datetime
import re
from unittest import mock

from bs4 import BeautifulSoup
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.utils import get_alleviate_user, get_imported_user
from annotations.models import Annotation
from lib.tests.utils import BasePermissionTest
from sources.models import Source
from .utils import BaseBrowsePageTest

tz = timezone.get_current_timezone()


class PermissionTest(BasePermissionTest):
    """
    Test page permissions.
    """
    def test_browse_patches(self):
        url = reverse('browse_patches', args=[self.source.pk])
        template = 'visualization/browse_patches.html'

        self.source_to_private()
        self.assertPermissionLevel(url, self.SOURCE_VIEW, template=template)
        self.source_to_public()
        self.assertPermissionLevel(url, self.SIGNED_OUT, template=template)


class BaseBrowsePatchesTest(BaseBrowsePageTest):

    url_name = 'browse_patches'

    all_possible_results = [
        (1,1), (1,2),
        (2,1), (2,2),
        (3,1), (3,2),
        (4,1), (4,2),
        (5,1), (5,2),
    ]

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user_editor = cls.create_user()
        cls.add_source_member(
            cls.user, cls.source, cls.user_editor, Source.PermTypes.EDIT.code)

    @staticmethod
    def thumb_wrapper_to_annotation_result(thumb_wrapper):
        anchor = thumb_wrapper.find('a')
        # The only number in the thumbnail's link should be the
        # image ID.
        match = re.search(r'(\d+)', anchor.attrs.get('href'))
        image_id = int(match.groups()[0])

        img = anchor.find('img')
        # The *first* number in the image element's title should be
        # the point number. (Starts with "Point <number> ...")
        match = re.search(r'(\d+)', img.attrs.get('title'))
        point_number = int(match.groups()[0])

        return image_id, point_number

    def assert_browse_results(
        self, response,
        # Tuples of (Image instance/number, point number)
        expected_results: list[tuple['Image|int', int]],
        msg_prefix=None,
    ):
        response_soup = BeautifulSoup(response.content, 'html.parser')
        thumb_wrappers = response_soup.find_all('span', class_='thumb_wrapper')
        actual_results = [
            # The only number in the thumbnail's link should be the
            # image ID.
            self.thumb_wrapper_to_annotation_result(thumb_wrapper)
            for thumb_wrapper in thumb_wrappers
        ]

        expected_results_2 = []
        for image_repr, point_number in expected_results:
            if isinstance(image_repr, int):
                # Image number in the self.images list
                image = self.images[image_repr - 1]
            else:
                # The Image itself
                image = image_repr
            expected_results_2.append((image.pk, point_number))

        # Patches are ordered randomly, so can't compare ordered lists.
        self.assertSetEqual(
            set(actual_results), set(expected_results_2),
            # This is a message prefix, not a message replacement,
            # as long as longMessage is True.
            msg=msg_prefix,
        )

    def assert_no_results(self, response):
        response_soup = BeautifulSoup(response.content, 'html.parser')
        self.assertIsNone(
            response_soup.find('span', class_='thumb_wrapper'))

    def set_annotation(
        self, image_number, point_number,
        dt=None, annotator=None, label='A',
    ):
        image = self.images[image_number - 1]
        if not dt:
            dt = timezone.now()
        if not annotator:
            annotator = self.user

        point = image.point_set.get(point_number=point_number)
        try:
            # If the point has an annotation, delete it.
            point.annotation.delete()
        except Annotation.DoesNotExist:
            pass

        # Add a new annotation to the point.
        annotation = Annotation(
            source=image.source, image=image, point=point,
            user=annotator, label=self.labels.get(default_code=label))
        # Fake the current date when saving the annotation, in order to
        # set the annotation_date field to what we want.
        # https://devblog.kogan.com/blog/testing-auto-now-datetime-fields-in-django/
        with mock.patch('django.utils.timezone.now') as mock_now:
            mock_now.return_value = dt
            annotation.save()

        image.annoinfo.last_annotation = annotation
        image.annoinfo.save()


# Many of the tests from here onward mirror tests from
# test_browse_images.py.


class FiltersTest(BaseBrowsePatchesTest):

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
            "Use the form to retrieve image patches"
            " corresponding to annotated points."
        )

    def test_default_search(self):
        for image in self.images:
            self.add_annotations(self.user, image)

        response = self.get_browse(**self.default_search_params)
        self.assert_browse_results(
            response, self.all_possible_results)
        self.assertNotContains(
            response,
            "Use the form to retrieve image patches"
            " corresponding to annotated points."
        )

    def test_zero_results(self):
        response = self.get_browse(image_name='DSC')

        self.assert_no_results(response)
        self.assert_not_invalid_params(response)
        self.assertContains(response, "No patch results.")

    def test_one_result(self):
        self.add_annotations(self.user, self.img1, {1: 'A', 2: 'B'})
        response = self.get_browse(patch_label=self.labels.get(name='B').pk)

        self.assert_browse_results(response, [(self.img1, 2)])
        self.assert_not_invalid_params(response)
        self.assertNotContains(response, "No patch results.")

    def test_dont_get_other_sources_patches(self):
        self.add_annotations(self.user, self.img1)

        source2 = self.create_source(
            self.user,
            default_point_generation_method=dict(type='simple', points=2))
        self.create_labelset(self.user, source2, self.labels)
        s2_image = self.upload_image(self.user, source2)
        self.add_annotations(self.user, s2_image)

        response = self.get_browse(**self.default_search_params)
        self.assert_browse_results(
            response, [(self.img1, 1), (self.img1, 2)],
            msg_prefix="Should include patches from only the first source",
        )

    def test_post_request(self):
        self.client.force_login(self.user)

        response = self.client.post(self.url, {}, follow=False)
        self.assertRedirects(
            response, self.url,
            msg_prefix="Should redirect back to browse patches")

        response = self.client.post(self.url, {}, follow=True)
        self.assertContains(
            response, "An error occurred; please try another search.",
            msg_prefix="Should show a message indicating the search didn't"
                       " actually work due to POST being used")

    # Specific filters.

    def test_filter_by_annotation_status_confirmed(self):
        robot = self.create_robot(self.source)
        for image in self.images:
            self.add_robot_annotations(robot, image)
        # 3 manually annotated points; the other 7 remain
        # robot annotated.
        self.add_annotations(
            self.user, self.img1, {1: 'A', 2: 'A'})
        self.add_annotations(
            self.user, self.img4, {1: 'B'})

        response = self.get_browse(patch_annotation_status='confirmed')
        self.assert_browse_results(
            response, [(1,1), (1,2), (4,1)])

    def test_filter_by_annotation_status_unconfirmed(self):
        robot = self.create_robot(self.source)
        for image in self.images:
            self.add_robot_annotations(robot, image)
        # 3 manually annotated points; the other 7 remain
        # robot annotated.
        self.add_annotations(
            self.user, self.img1, {1: 'A', 2: 'A'})
        self.add_annotations(
            self.user, self.img4, {1: 'B'})

        response = self.get_browse(patch_annotation_status='unconfirmed')
        self.assert_browse_results(
            response, [(2,1), (2,2), (3,1), (3,2), (4,2), (5,1), (5,2)])

    def test_filter_by_label(self):
        self.add_annotations(
            self.user, self.img1, {1: 'A', 2: 'A'})
        self.add_annotations(
            self.user, self.img2, {1: 'A', 2: 'B'})
        self.add_annotations(
            self.user, self.img3, {1: 'B', 2: 'A'})

        response = self.get_browse(patch_label=self.labels.get(name='A').pk)
        self.assert_browse_results(response, [(1,1), (1,2), (2,1), (3,2)])

    def test_label_choices(self):
        # This label, which is not in the source labelset, should
        # not appear in the choices.
        self.create_labels(self.user, ['C'], 'GroupA')

        response = self.get_browse()
        self.assert_search_field_choices(
            response, 'patch_label',
            [('', "Any"),
             (str(self.labels.get(name='A').pk), "A"),
             (str(self.labels.get(name='B').pk), "B")],
        )

    def test_date_type_choices(self):
        response = self.get_browse()

        self.assert_search_field_choices(
            response, 'patch_annotation_date_0',
            [('', "Any"),
             ('year', "Year"),
             ('date', "Exact date"),
             ('date_range', "Date range")]
        )

    def test_filter_by_date_any(self):
        self.set_annotation(1, 1, dt=datetime.datetime(2011, 12, 28, tzinfo=tz))
        self.set_annotation(1, 2, dt=datetime.datetime(2013, 1, 13, tzinfo=tz))

        # Any date, as long as there is an annotation on the point
        # at all.
        response = self.get_browse(**self.default_search_params)
        self.assert_browse_results(response, [(1,1), (1,2)])

    def test_date_year_choices(self):
        self.set_annotation(1, 1, dt=datetime.datetime(2011, 12, 28, tzinfo=tz))
        self.set_annotation(1, 2, dt=datetime.datetime(2013, 1, 13, tzinfo=tz))

        self.source.create_date = datetime.datetime(2010, 1, 1, tzinfo=tz)
        self.source.save()

        current_year = timezone.now().year

        response = self.get_browse()

        # Choices should be based on the source create date and the
        # current year, not based on existing annotation dates. It's done this
        # way for a slight speed optimization.
        self.assert_search_field_choices(
            response, 'patch_annotation_date_1',
            [''] + [str(year) for year in range(2010, current_year+1)],
        )

    def test_filter_by_exact_date(self):
        # The entire 24 hours of the given date should be included.
        # As an implementation detail, 00:00 of the next day is also included,
        # so we just make sure 00:01 of the next day isn't in.
        self.set_annotation(
            1, 1, dt=datetime.datetime(2012, 1, 12, 23, 59, tzinfo=tz))
        self.set_annotation(
            1, 2, dt=datetime.datetime(2012, 1, 13, 0, 0, tzinfo=tz))
        self.set_annotation(
            2, 1, dt=datetime.datetime(2012, 1, 13, 23, 59, tzinfo=tz))
        self.set_annotation(
            2, 2, dt=datetime.datetime(2012, 1, 14, 0, 1, tzinfo=tz))

        response = self.get_browse(
            patch_annotation_date_0='date',
            patch_annotation_date_2=datetime.date(2012, 1, 13),
        )
        self.assert_browse_results(
            response, [(1,2), (2,1)],
        )

    def test_filter_by_date_range(self):
        # The given range should be included from day 1 00:00 to day n+1 00:00.
        self.set_annotation(
            1, 1, dt=datetime.datetime(2012, 3, 9, 23, 59, tzinfo=tz))
        self.set_annotation(
            1, 2, dt=datetime.datetime(2012, 3, 10, 0, 0, tzinfo=tz))
        self.set_annotation(
            2, 1, dt=datetime.datetime(2012, 3, 15, 12, 34, tzinfo=tz))
        self.set_annotation(
            2, 2, dt=datetime.datetime(2012, 3, 20, 23, 59, tzinfo=tz))
        self.set_annotation(
            3, 1, dt=datetime.datetime(2012, 3, 21, 0, 1, tzinfo=tz))

        response = self.get_browse(
            patch_annotation_date_0='date_range',
            patch_annotation_date_3=datetime.date(2012, 3, 10),
            patch_annotation_date_4=datetime.date(2012, 3, 20),
        )
        self.assert_browse_results(
            response, [(1,2), (2,1), (2,2)])

    def test_filter_by_annotator(self):
        # Robot
        robot = self.create_robot(self.source)
        for image in self.images:
            self.add_robot_annotations(robot, image)

        # Tool users
        self.add_annotations(self.user, self.img2)
        self.add_annotations(self.user_editor, self.img3)

        # Not robot, but not annotation tool
        self.set_annotation(4, 1, annotator=get_imported_user())
        self.set_annotation(4, 2, annotator=get_imported_user())
        self.set_annotation(5, 1, annotator=get_alleviate_user())
        self.set_annotation(5, 2, annotator=get_alleviate_user())

        # Annotation tool, any user
        response = self.get_browse(patch_annotator_0='annotation_tool')
        self.assert_browse_results(
            response, [(2,1), (2,2), (3,1), (3,2)])

        # Annotation tool, specific user
        response = self.get_browse(
            patch_annotator_0='annotation_tool',
            patch_annotator_1=self.user_editor.pk,
        )
        self.assert_browse_results(
            response, [(3,1), (3,2)])

        # Imported
        response = self.get_browse(
            patch_annotator_0='imported',
        )
        self.assert_browse_results(
            response, [(4,1), (4,2)])

        # Alleviate
        response = self.get_browse(
            patch_annotator_0='alleviate',
        )
        self.assert_browse_results(
            response, [(5,1), (5,2)])

    def test_annotator_tool_choices(self):
        self.add_annotations(self.user, self.img1)
        self.add_annotations(self.user_editor, self.img2)

        response = self.get_browse()
        self.assert_search_field_choices(
            response, 'patch_annotator_1',
            [('', "Any user"),
             (str(self.user.pk), self.user.username),
             (str(self.user_editor.pk), self.user_editor.username)],
        )

    # These filters should be tested more thoroughly in test_browse_images.py.

    def test_filter_by_aux1(self):
        self.update_multiple_metadatas(
            'aux1',
            [(self.img1, 'Site1'),
             (self.img2, 'Site3'),
             (self.img3, 'Site3')])
        for image in self.images:
            self.add_annotations(self.user, image)

        response = self.get_browse(aux1='Site3')
        self.assert_browse_results(
            response, [(2,1), (2,2), (3,1), (3,2)])

    def test_filter_by_photo_date_year(self):
        self.update_multiple_metadatas(
            'photo_date',
            [(self.img1, datetime.date(2011, 12, 28)),
             (self.img2, datetime.date(2012, 1, 13)),
             (self.img3, datetime.date(2012, 8, 4))])
        for image in self.images:
            self.add_annotations(self.user, image)

        response = self.get_browse(photo_date_0='year', photo_date_1=2012)
        self.assert_browse_results(
            response, [(2,1), (2,2), (3,1), (3,2)])


class FormInitializationTest(BaseBrowsePatchesTest):

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


@override_settings(
    # Require fewer annotations to get multiple pages of results.
    BROWSE_DEFAULT_THUMBNAILS_PER_PAGE=3,
)
class PagesTest(BaseBrowsePatchesTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.add_annotations(cls.user, cls.images[0], {1: 'A', 2: 'A'})
        cls.add_annotations(cls.user, cls.images[1], {1: 'A', 2: 'A'})
        cls.add_annotations(cls.user, cls.images[2], {1: 'A', 2: 'A'})
        cls.add_annotations(cls.user, cls.images[3], {1: 'A', 2: 'B'})
        cls.add_annotations(cls.user, cls.images[4], {1: 'B', 2: 'B'})

    def test_one_page_results(self):
        response = self.get_browse(
            patch_label=self.labels.get(default_code='B').pk,
        )
        self.assert_page_results(
            response, 3,
            expected_summary="Showing 1-3 of 3",
            expected_page_status="Page 1 of 1",
        )

    def test_multiple_pages_results(self):
        response = self.get_browse(
            patch_label=self.labels.get(default_code='A').pk,
        )
        self.assert_page_results(
            response, 7,
            expected_summary="Showing 1-3 of 7",
            expected_page_status="Page 1 of 3",
        )

    def test_page_two(self):
        response = self.get_browse(
            patch_label=self.labels.get(default_code='A').pk,
            page=2,
        )
        self.assert_page_results(
            response, 7,
            expected_summary="Showing 4-6 of 7",
            expected_page_status="Page 2 of 3",
        )

    # test_page_urls_no_params() doesn't apply here because
    # Browse Patches requires params to show any results.

    def test_page_urls_with_search_params(self):
        label_a_pk = self.labels.get(default_code='A').pk
        response = self.get_browse(
            patch_label=label_a_pk,
            page=2,
        )
        self.assert_page_links(
            response,
            f'?patch_label={label_a_pk}&page=1',
            f'?patch_label={label_a_pk}&page=3',
        )

    # Only Browse Patches has a result-count limit.

    @override_settings(BROWSE_PATCHES_RESULT_LIMIT=8)
    def test_result_limit(self):
        # There are 10 total patches, more than the limit.

        explanation = (
            "Due to site performance limitations, this is the last page"
            " of search results we can show.")

        response = self.get_browse(**self.default_search_params)
        self.assert_page_results(
            response, 8,
            expected_summary="Showing 1-3 of 8 or more",
            expected_page_status="Page 1 of 3",
        )
        self.assertNotContains(response, explanation)

        response = self.get_browse(page=3, **self.default_search_params)
        self.assert_page_results(
            response, 8,
            expected_summary="Showing 7-8 of 8 or more",
            expected_page_status="Page 3 of 3",
        )
        self.assertContains(response, explanation)

        response = self.get_browse(page=4, **self.default_search_params)
        self.assert_page_results(
            response, 8,
            expected_summary="Showing 7-8 of 8 or more",
            expected_page_status="Page 3 of 3",
        )
        self.assertContains(response, explanation)

        # Here the limit is not reached.
        label_a_pk = self.labels.get(default_code='A').pk
        response = self.get_browse(page=3, patch_label=label_a_pk)
        self.assert_page_results(
            response, 7,
            expected_summary="Showing 7-7 of 7",
            expected_page_status="Page 3 of 3",
        )
        self.assertNotContains(response, explanation)


class NoLabelsetTest(BaseBrowsePatchesTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.source.labelset = None
        cls.source.save()

    def test_default_search(self):
        """
        No labelset shouldn't be an error case.
        It just won't return anything exciting.
        """
        response = self.get_browse(**self.default_search_params)
        self.assert_no_results(response)
        self.assertContains(response, "No patch results.")


@override_settings(
    # More results per page, to really make clear how the query count
    # depends on results per page.
    BROWSE_DEFAULT_THUMBNAILS_PER_PAGE=100,
)
class QueriesTest(BaseBrowsePatchesTest):

    setup_image_count = 5
    points_per_image = 20

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        for image in cls.images:
            cls.add_annotations(cls.user, image)

    def test(self):
        # Should run less than 1 query per patch.
        with self.assert_queries_less_than(100):
            response = self.get_browse(**self.default_search_params)

        self.assert_browse_results(
            response,
            [(i, p) for i in range(1, 5+1) for p in range(1, 20+1)],
            msg_prefix="Shouldn't have any issues preventing correct results",
        )
