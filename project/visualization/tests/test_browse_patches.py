import datetime
from unittest import mock

from bs4 import BeautifulSoup
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.utils import get_alleviate_user, get_imported_user
from annotations.models import Annotation
from lib.tests.utils import BasePermissionTest, ClientTest
from sources.models import Source

tz = timezone.get_current_timezone()
default_search_params = dict(submit='search')


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


class SearchTest(ClientTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()

        cls.source = cls.create_source(
            cls.user,
            default_point_generation_method=dict(type='simple', points=10),
        )
        cls.labels = cls.create_labels(
            cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, cls.labels)

        cls.user_editor = cls.create_user()
        cls.add_source_member(
            cls.user, cls.source, cls.user_editor, Source.PermTypes.EDIT.code)

        cls.img1 = cls.upload_image(cls.user, cls.source)

        cls.url = reverse('browse_patches', args=[cls.source.pk])

    def set_annotation(
            self, point_number, image=None,
            dt=None, annotator=None, label='A'):
        if not image:
            image = self.img1
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

    def submit_search(self, **search_kwargs):
        """
        Submit the search form with the given kwargs, and return the response.
        """
        return self.client.get(self.url, search_kwargs)

    def assert_search_results(self, search_kwargs, expected_points):
        """
        Assert that the given search-form kwargs return the expected images,
        in any order.
        Each element of expected_points should be an integer denoting a point
        number of self.img1. (None of the tests so far involve results from
        other images.)
        """
        self.client.force_login(self.user)
        response = self.submit_search(**search_kwargs)
        actual_pks = {
            annotation.pk
            for annotation in response.context['page_results'].object_list
        }

        expected_pks = set()
        for expected_point in expected_points:
            point_number = expected_point
            try:
                expected_annotation = Annotation.objects.get(
                    image=self.img1, point__point_number=point_number)
            except Annotation.DoesNotExist:
                raise AssertionError(
                    "Point {} was expected to have an annotation,"
                    " but it doesn't.".format(point_number))
            expected_pks.add(expected_annotation.pk)

        self.assertSetEqual(actual_pks, expected_pks)

    def test_page_landing(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertContains(
            response,
            "Use the form to retrieve image patches"
            " corresponding to annotated points."
        )

    def test_default_search(self):
        self.add_annotations(
            self.user, self.img1,
            {1: 'A', 2: 'A', 3: 'A'})

        self.assert_search_results(
            default_search_params,
            [1, 2, 3])

    def test_filter_by_annotation_status_confirmed(self):
        robot = self.create_robot(self.source)
        # 10 points per image
        self.add_robot_annotations(robot, self.img1)
        self.add_annotations(
            self.user, self.img1,
            {1: 'A', 2: 'A', 3: 'A'})

        self.assert_search_results(
            dict(patch_annotation_status='confirmed'),
            [1, 2, 3])

    def test_filter_by_annotation_status_unconfirmed(self):
        robot = self.create_robot(self.source)
        # 10 points per image
        self.add_robot_annotations(robot, self.img1)
        self.add_annotations(
            self.user, self.img1,
            {1: 'A', 2: 'A', 3: 'A'})

        self.assert_search_results(
            dict(patch_annotation_status='unconfirmed'),
            [4, 5, 6, 7, 8, 9, 10])

    def test_filter_by_label(self):
        self.add_annotations(
            self.user, self.img1,
            {1: 'A', 2: 'A', 3: 'A', 4: 'B', 5: 'B'})

        self.assert_search_results(
            dict(patch_label=self.source.labelset.get_global_by_code('A').pk),
            [1, 2, 3])

    def test_label_choices(self):
        self.add_annotations(
            self.user, self.img1,
            {1: 'A', 2: 'A', 3: 'A', 4: 'B', 5: 'B'})

        self.client.force_login(self.user)
        response = self.client.get(self.url)

        search_form = response.context['patch_search_form']
        field = search_form.fields['patch_label']
        self.assertListEqual(
            list(field.choices),
            [('', "Any"),
             (self.source.labelset.get_global_by_code('A').pk, "A"),
             (self.source.labelset.get_global_by_code('B').pk, "B")]
        )

    def test_date_type_choices(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)

        search_form = response.context['patch_search_form']
        field = search_form.fields['patch_annotation_date'].fields[0]
        self.assertListEqual(
            list(field.choices),
            [('', "Any"),
             ('year', "Year"),
             ('date', "Exact date"),
             ('date_range', "Date range")]
        )

    def test_filter_by_date_any(self):
        self.set_annotation(1, dt=datetime.datetime(2011, 12, 28, tzinfo=tz))
        self.set_annotation(2, dt=datetime.datetime(2012, 1, 13, tzinfo=tz))

        self.assert_search_results(
            default_search_params,
            [1, 2])

    def test_date_year_choices(self):
        self.set_annotation(1, dt=datetime.datetime(2011, 12, 28, tzinfo=tz))
        self.set_annotation(2, dt=datetime.datetime(2012, 1, 13, tzinfo=tz))

        self.source.create_date = datetime.datetime(2010, 1, 1, tzinfo=tz)
        self.source.save()

        current_year = timezone.now().year

        self.client.force_login(self.user)
        response = self.client.get(self.url)

        search_form = response.context['patch_search_form']
        year_field = search_form.fields['patch_annotation_date'].fields[1]
        year_choices = [value for value, label in year_field.choices]
        # Choices should be based on the source create date and the
        # current year, not based on existing annotation dates. It's done this
        # way for a slight speed optimization.
        self.assertListEqual(
            year_choices,
            [''] + [str(year) for year in range(2010, current_year+1)],
        )

    def test_filter_by_exact_date(self):
        # The entire 24 hours of the given date should be included.
        # As an implementation detail, 00:00 of the next day is also included,
        # so we just make sure 00:01 of the next day isn't in.
        self.set_annotation(
            1, dt=datetime.datetime(2012, 1, 12, 23, 59, tzinfo=tz))
        self.set_annotation(
            2, dt=datetime.datetime(2012, 1, 13, 0, 0, tzinfo=tz))
        self.set_annotation(
            3, dt=datetime.datetime(2012, 1, 13, 23, 59, tzinfo=tz))
        self.set_annotation(
            4, dt=datetime.datetime(2012, 1, 14, 0, 1, tzinfo=tz))

        self.assert_search_results(
            dict(
                patch_annotation_date_0='date',
                patch_annotation_date_2=datetime.date(2012, 1, 13),
            ),
            [2, 3])

    def test_filter_by_date_range(self):
        # The given range should be included from day 1 00:00 to day n+1 00:00.
        self.set_annotation(
            1, dt=datetime.datetime(2012, 3, 9, 23, 59, tzinfo=tz))
        self.set_annotation(
            2, dt=datetime.datetime(2012, 3, 10, 0, 0, tzinfo=tz))
        self.set_annotation(
            3, dt=datetime.datetime(2012, 3, 15, 12, 34, tzinfo=tz))
        self.set_annotation(
            4, dt=datetime.datetime(2012, 3, 20, 23, 59, tzinfo=tz))
        self.set_annotation(
            5, dt=datetime.datetime(2012, 3, 21, 0, 1, tzinfo=tz))

        self.assert_search_results(
            dict(
                patch_annotation_date_0='date_range',
                patch_annotation_date_3=datetime.date(2012, 3, 10),
                patch_annotation_date_4=datetime.date(2012, 3, 20),
            ),
            [2, 3, 4])

    def test_filter_by_annotator_tool_any_user(self):
        robot = self.create_robot(self.source)
        self.add_robot_annotations(robot, self.img1)

        # Tool users
        self.add_annotations(self.user, self.img1, {1: 'A'})
        self.add_annotations(self.user_editor, self.img1, {2: 'B'})

        # Non annotation tool
        self.set_annotation(3, annotator=get_imported_user())
        self.set_annotation(4, annotator=get_alleviate_user())

        self.assert_search_results(
            dict(patch_annotator_0='annotation_tool'),
            [1, 2])

    def test_filter_by_annotator_tool_specific_user(self):
        self.add_annotations(
            self.user, self.img1,
            {1: 'A', 2: 'A', 3: 'A'})
        self.add_annotations(
            self.user_editor, self.img1,
            {4: 'A', 5: 'A'})

        params = dict(
            patch_annotator_0='annotation_tool',
            patch_annotator_1=self.user.pk,
        )

        self.client.force_login(self.user)
        response = self.client.get(self.url, params)
        self.assertEqual(
            response.context['page_results'].paginator.count, 3)

    def test_annotator_choices(self):
        self.add_annotations(
            self.user, self.img1,
            {1: 'A', 2: 'A', 3: 'A'})
        self.add_annotations(
            self.user_editor, self.img1,
            {4: 'A', 5: 'A'})

        self.client.force_login(self.user)
        response = self.client.get(self.url)

        search_form = response.context['patch_search_form']
        field = search_form.fields['patch_annotator'].fields[1]
        self.assertListEqual(
            list(field.choices),
            [('', "Any user"), (self.user.pk, self.user.username),
             (self.user_editor.pk, self.user_editor.username)]
        )

    def test_filter_by_annotator_alleviate(self):
        robot = self.create_robot(self.source)
        self.add_robot_annotations(robot, self.img1)

        self.add_annotations(self.user, self.img1, {1: 'A', 2: 'B'})
        self.set_annotation(3, annotator=get_imported_user())
        self.set_annotation(4, annotator=get_alleviate_user())

        self.assert_search_results(
            dict(patch_annotator_0='alleviate'),
            [4])

    def test_dont_get_other_sources_patches(self):
        self.add_annotations(
            self.user, self.img1,
            {1: 'A', 2: 'A', 3: 'A'})

        source2 = self.create_source(
            self.user,
            default_point_generation_method=dict(type='simple', points=2))
        self.create_labelset(self.user, source2, self.labels)
        s2_img = self.upload_image(self.user, source2)
        self.add_annotations(self.user, s2_img, {1: 'A', 2: 'A'})

        # Should include patches from img1, but not s2_img
        self.assert_search_results(
            default_search_params,
            [1, 2, 3])

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


@override_settings(
    # Require fewer annotations to get multiple pages of results.
    BROWSE_DEFAULT_THUMBNAILS_PER_PAGE=3,
)
class ResultsAndPagesTest(ClientTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user,
            default_point_generation_method=dict(type='simple', points=2))
        cls.labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, cls.labels)
        cls.url = reverse('browse_patches', args=[cls.source.pk])

        cls.images = [cls.upload_image(cls.user, cls.source) for _ in range(5)]
        cls.add_annotations(cls.user, cls.images[0], {1: 'A', 2: 'A'})
        cls.add_annotations(cls.user, cls.images[1], {1: 'A', 2: 'A'})
        cls.add_annotations(cls.user, cls.images[2], {1: 'A', 2: 'A'})
        cls.add_annotations(cls.user, cls.images[3], {1: 'A', 2: 'B'})
        cls.add_annotations(cls.user, cls.images[4], {1: 'B', 2: 'B'})

    def request_browse(self, request_params):
        self.client.force_login(self.user)
        return self.client.get(self.url, request_params)

    def assert_page_results(
        self, response,
        expected_count, expected_summary=None, expected_page_status=None,
    ):
        self.assertEqual(
            response.context['page_results'].paginator.count, expected_count,
            msg="Result count should be as expected")

        if expected_summary is not None:
            self.assertContains(
                response, f"<span>{expected_summary}</span>", html=True,
                msg_prefix="Page results summary should be as expected")

        if expected_page_status is not None:
            self.assertContains(
                response, f"<span>{expected_page_status}</span>", html=True,
                msg_prefix="Page status text should be as expected")

    def test_zero_results(self):
        params = dict(
            photo_date_0='date',
            photo_date_2=datetime.date(2000, 1, 1),
        )
        response = self.request_browse(params)
        self.assert_page_results(response, 0)
        self.assertContains(response, "No patch results.")

    def test_one_page_results(self):
        params = dict(
            patch_label=self.labels.get(default_code='B').pk,
        )
        response = self.request_browse(params)
        self.assert_page_results(
            response, 3,
            expected_summary="Showing 1-3 of 3",
            expected_page_status="Page 1 of 1",
        )

    def test_multiple_pages_results(self):
        params = dict(
            patch_label=self.labels.get(default_code='A').pk,
        )
        response = self.request_browse(params)
        self.assert_page_results(
            response, 7,
            expected_summary="Showing 1-3 of 7",
            expected_page_status="Page 1 of 3",
        )

    def test_page_two(self):
        params = dict(
            patch_label=self.labels.get(default_code='A').pk,
            page=2,
        )
        response = self.request_browse(params)
        self.assert_page_results(
            response, 7,
            expected_summary="Showing 4-6 of 7",
            expected_page_status="Page 2 of 3",
        )

    def assert_page_links(
        self, request_params, expected_prev_href, expected_next_href
    ):
        """
        We don't need to test everything about pagination links here,
        as that's the job of the app that implements such links.
        However, we do want to test that the query string, which
        originates from Browse's app, is as expected.

        We assume both previous and next page links are present,
        for simplicity.
        """
        self.client.force_login(self.user)
        response = self.client.get(self.url, request_params)
        response_soup = BeautifulSoup(response.content, 'html.parser')
        page_links_soup = response_soup.findAll(
            'a', class_='prev-next-page')

        self.assertEqual(
            page_links_soup[0].attrs.get('href'),
            expected_prev_href,
            msg="Previous page link is as expected")
        self.assertEqual(
            page_links_soup[1].attrs.get('href'),
            expected_next_href,
            msg="Next page link is as expected")

    def test_page_urls_no_additional_filters(self):
        params = dict(page=2)
        self.assert_page_links(
            params,
            '?page=1&',
            '?page=3&')

    def test_page_urls_with_search_filters(self):
        label_a_pk = self.labels.get(default_code='A').pk
        params = dict(
            patch_label=label_a_pk,
            page=2,
        )
        self.assert_page_links(
            params,
            f'?page=1&patch_label={label_a_pk}',
            f'?page=3&patch_label={label_a_pk}',
        )


class NoLabelsetTest(ClientTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)
        cls.img1 = cls.upload_image(cls.user, cls.source)
        cls.url = reverse('browse_patches', args=[cls.source.pk])

    def test_default_search(self):
        """
        No labelset shouldn't be an error case.
        It just won't return anything exciting.
        """
        self.client.force_login(self.user)
        response = self.client.get(self.url, dict(submit='search'))
        self.assertContains(response, "No patch results.")
