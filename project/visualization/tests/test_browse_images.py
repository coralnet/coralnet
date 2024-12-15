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
from visualization.tests.utils import BrowseActionsFormTest

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


default_search_params = dict(
    image_form_type='search',
    aux1='', aux2='', aux3='', aux4='', aux5='',
    height_in_cm='', latitude='', longitude='', depth='',
    photographer='', framing='', balance='',
    photo_date_0='', photo_date_1='', photo_date_2='',
    photo_date_3='', photo_date_4='',
    image_name='', annotation_status='',
    last_annotated_0='', last_annotated_1='', last_annotated_2='',
    last_annotated_3='', last_annotated_4='',
    last_annotator_0='', last_annotator_1='',
    sort_method='name', sort_direction='asc',
)


class AnnotateFormAvailabilityTest(BrowseActionsFormTest):
    form_id = 'annotate-all-form'

    def test_available(self):
        self.client.force_login(self.user)
        response = self.client.post(self.browse_url)
        self.assert_form_available(response)

    def test_view_perms_only(self):
        self.client.force_login(self.user_viewer)
        response = self.client.post(self.browse_url)
        self.assert_form_absent(response)


class BaseSearchTest(ClientTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user,
            # Make it easy to have confirmed and partially annotated images
            default_point_generation_method=dict(type='simple', points=2),
        )
        cls.labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, cls.labels)

        cls.url = reverse('browse_images', args=[cls.source.pk])

        cls.imgs = [
            cls.upload_image(cls.user, cls.source) for _ in range(5)
        ]

    @staticmethod
    def update_multiple_metadatas(field_name, image_value_pairs):
        """Update a particular metadata field on multiple images."""
        for image, value in image_value_pairs:
            setattr(image.metadata, field_name, value)
            image.metadata.save()

    def set_last_annotation(self, image, dt=None, annotator=None):
        """
        Update the image's last annotation. This simply assigns the desired
        annotation field values to the image's first point.
        """
        if not dt:
            dt = timezone.now()
        if not annotator:
            annotator = self.user

        first_point = image.point_set.get(point_number=1)
        try:
            # If the first point has an annotation, delete it.
            first_point.annotation.delete()
        except Annotation.DoesNotExist:
            pass

        # Add a new annotation to the first point.
        annotation = Annotation(
            source=image.source, image=image, point=first_point,
            user=annotator, label=self.labels.get(default_code='A'))
        # Fake the current date when saving the annotation, in order to
        # set the annotation_date field to what we want.
        # https://devblog.kogan.com/blog/testing-auto-now-datetime-fields-in-django/
        with mock.patch('django.utils.timezone.now') as mock_now:
            mock_now.return_value = dt
            annotation.save()

        image.annoinfo.last_annotation = annotation
        image.annoinfo.save()

    def submit_search(self, **kwargs):
        """
        Submit the search form with the given kwargs, and return the response.
        """
        data = default_search_params.copy()
        data.update(**kwargs)
        response = self.client.post(self.url, data, follow=True)
        return response

    def assert_search_results(self, search_kwargs, expected_images):
        """
        Assert that the given search-form kwargs return the expected images,
        in any order.
        """
        self.client.force_login(self.user)
        response = self.submit_search(**search_kwargs)
        actual_pks = {
            image.pk for image in response.context['page_results'].object_list}
        expected_pks = {image.pk for image in expected_images}
        self.assertSetEqual(actual_pks, expected_pks)

    def assert_search_results_ordered(self, search_kwargs, expected_images):
        """
        Assert that the given search-form kwargs return the expected images,
        in the specified order.
        """
        self.client.force_login(self.user)
        response = self.submit_search(**search_kwargs)
        actual_pks = [
            image.pk for image in response.context['page_results'].object_list]
        expected_pks = [image.pk for image in expected_images]
        self.assertListEqual(actual_pks, expected_pks)

    def assert_invalid_search(self, **search_kwargs):
        self.client.force_login(self.user)
        response = self.submit_search(**search_kwargs)

        self.assertContains(response, "Search parameters were invalid.")
        self.assertEqual(
            response.context['page_results'].paginator.count, 0)


class SearchTest(BaseSearchTest):

    def test_page_landing(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(
            response.context['page_results'].paginator.count, 5)

    def test_default_search(self):
        self.client.force_login(self.user)
        response = self.submit_search()
        self.assertEqual(
            response.context['page_results'].paginator.count, 5)

    def test_filter_by_annotation_status_confirmed(self):
        robot = self.create_robot(self.source)
        # 2 points per image
        # confirmed, confirmed, unconfirmed, partial
        self.add_annotations(self.user, self.imgs[0], {1: 'A', 2: 'B'})
        self.add_annotations(self.user, self.imgs[1], {1: 'B', 2: 'A'})
        self.add_robot_annotations(robot, self.imgs[2])
        self.add_annotations(self.user, self.imgs[3], {1: 'B'})

        self.assert_search_results(
            dict(annotation_status='confirmed'),
            [self.imgs[0], self.imgs[1]])

    def test_filter_by_annotation_status_unconfirmed(self):
        robot = self.create_robot(self.source)
        # 2 points per image
        # confirmed, unconfirmed, unconfirmed, partial
        self.add_annotations(self.user, self.imgs[0], {1: 'A', 2: 'B'})
        self.add_robot_annotations(robot, self.imgs[1])
        self.add_robot_annotations(robot, self.imgs[2])
        self.add_annotations(self.user, self.imgs[3], {1: 'B'})

        self.assert_search_results(
            dict(annotation_status='unconfirmed'),
            [self.imgs[1], self.imgs[2]])

    def test_filter_by_annotation_status_unclassified(self):
        robot = self.create_robot(self.source)
        # 2 points per image
        # confirmed, unconfirmed, partial (counts as unclassified)
        self.add_annotations(self.user, self.imgs[0], {1: 'A', 2: 'B'})
        self.add_robot_annotations(robot, self.imgs[1])
        self.add_annotations(self.user, self.imgs[2], {1: 'B'})

        self.assert_search_results(
            dict(annotation_status='unclassified'),
            [self.imgs[2], self.imgs[3], self.imgs[4]])

    def test_filter_by_aux1(self):
        self.update_multiple_metadatas(
            'aux1',
            [(self.imgs[0], 'Site1'),
             (self.imgs[1], 'Site3'),
             (self.imgs[2], 'Site3')])

        self.assert_search_results(
            dict(aux1='Site3'),
            [self.imgs[1], self.imgs[2]])

    def test_filter_by_aux1_none(self):
        self.update_multiple_metadatas(
            'aux1',
            [(self.imgs[0], 'Site1'),
             (self.imgs[1], 'Site3')])

        self.assert_search_results(
            dict(aux1='(none)'),
            [self.imgs[2], self.imgs[3], self.imgs[4]])

    def test_aux1_choices(self):
        self.update_multiple_metadatas(
            'aux1',
            [(self.imgs[0], 'Site1'),
             (self.imgs[1], 'Site3')])

        self.client.force_login(self.user)
        response = self.client.get(self.url)

        search_form = response.context['image_search_form']
        field = search_form.fields['aux1']
        choices = [value for value, label in field.choices]
        self.assertListEqual(
            choices,
            ['', 'Site1', 'Site3', '(none)']
        )

    def test_filter_by_aux5(self):
        self.update_multiple_metadatas(
            'aux5',
            [(self.imgs[0], 'C'),
             (self.imgs[1], 'D'),
             (self.imgs[2], 'D')])

        self.assert_search_results(
            dict(aux5='D'),
            [self.imgs[1], self.imgs[2]])

    def test_filter_by_height_cm(self):
        self.update_multiple_metadatas(
            'height_in_cm',
            [(self.imgs[0], 25),
             (self.imgs[1], 25),
             (self.imgs[2], 30)])

        self.assert_search_results(
            dict(height_in_cm=25),
            [self.imgs[0], self.imgs[1]])

    def test_filter_by_height_cm_none(self):
        self.update_multiple_metadatas(
            'height_in_cm',
            [(self.imgs[0], 25),
             (self.imgs[1], 25),
             (self.imgs[2], None),
             (self.imgs[3], 50),
             (self.imgs[4], 50)])

        self.assert_search_results(
            dict(height_in_cm='(none)'),
            [self.imgs[2]])

    def test_height_cm_choices(self):
        self.update_multiple_metadatas(
            'height_in_cm',
            [(self.imgs[0], 25),
             (self.imgs[1], 30)])

        self.client.force_login(self.user)
        response = self.client.get(self.url)

        search_form = response.context['image_search_form']
        field = search_form.fields['height_in_cm']
        choices = [value for value, label in field.choices]
        self.assertListEqual(
            choices,
            ['', 25, 30, '(none)']
        )

    def test_filter_by_latitude(self):
        self.update_multiple_metadatas(
            'latitude',
            [(self.imgs[0], '12.34'),
             (self.imgs[1], '-56.78'),
             (self.imgs[2], '-56.78')])

        self.assert_search_results(
            dict(latitude='-56.78'),
            [self.imgs[1], self.imgs[2]])

    def test_filter_by_latitude_none(self):
        self.update_multiple_metadatas(
            'latitude',
            [(self.imgs[0], '12.34'),
             (self.imgs[1], '-56.78')])

        self.assert_search_results(
            dict(latitude='(none)'),
            [self.imgs[2], self.imgs[3], self.imgs[4]])

    def test_filter_by_camera(self):
        self.update_multiple_metadatas(
            'camera',
            [(self.imgs[0], 'Nikon'),
             (self.imgs[1], 'Canon'),
             (self.imgs[2], 'Canon')])

        self.assert_search_results(
            dict(camera='Canon'),
            [self.imgs[1], self.imgs[2]])

    def test_filter_by_camera_none(self):
        self.update_multiple_metadatas(
            'camera',
            [(self.imgs[0], 'Nikon'),
             (self.imgs[1], 'Canon')])

        self.assert_search_results(
            dict(camera='(none)'),
            [self.imgs[2], self.imgs[3], self.imgs[4]])

    def test_filter_by_image_name_one_token(self):
        self.update_multiple_metadatas(
            'name',
            [(self.imgs[0], 'XYZ.jpg'),
             (self.imgs[1], 'abcxyzdef.png'),
             (self.imgs[2], 'xydefz.png')])

        self.assert_search_results(
            dict(image_name='xyz'),
            [self.imgs[0], self.imgs[1]])

    def test_filter_by_image_name_two_tokens(self):
        # Both search tokens must be present
        self.update_multiple_metadatas(
            'name',
            [(self.imgs[0], 'ABCXYZ.jpg'),
             (self.imgs[1], 'xyz.abc'),
             (self.imgs[2], 'abc.png'),
             (self.imgs[3], 'xyz.jpg')])

        self.assert_search_results(
            dict(image_name='abc xyz'),
            [self.imgs[0], self.imgs[1]])

    def test_filter_by_image_name_punctuation(self):
        # Punctuation is considered part of search tokens
        self.update_multiple_metadatas(
            'name',
            [(self.imgs[0], '1-1.png'),
             (self.imgs[1], '1*1.png'),
             (self.imgs[2], '2-1-1.jpg'),
             (self.imgs[3], '1-1-2.png')])

        self.assert_search_results(
            dict(image_name='1-1.'),
            [self.imgs[0], self.imgs[2]])

    def test_filter_by_multiple_fields(self):
        self.update_multiple_metadatas(
            'photo_date',
            [(self.imgs[0], datetime.date(2012, 3, 9)),
             (self.imgs[1], datetime.date(2013, 3, 10)),
             (self.imgs[2], datetime.date(2012, 5, 17)),
             (self.imgs[3], datetime.date(2013, 10, 12))])
        self.update_multiple_metadatas(
            'height_in_cm',
            [(self.imgs[0], 30),
             (self.imgs[1], 30),
             (self.imgs[2], 25),
             (self.imgs[3], 25)])

        self.assert_search_results(
            dict(photo_date_0='year', photo_date_1=2013, height_in_cm=30),
            [self.imgs[1]])

    def test_dont_get_other_sources_images(self):
        source2 = self.create_source(self.user)
        self.upload_image(self.user, source2)

        # Just source 1's images, not source 2's
        self.assert_search_results(
            dict(),
            [self.imgs[0], self.imgs[1], self.imgs[2],
             self.imgs[3], self.imgs[4]])


class DateSearchTest(BaseSearchTest):

    # Photo date

    def test_photo_date_type_choices(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)

        search_form = response.context['image_search_form']
        field = search_form.fields['photo_date'].fields[0]
        self.assertListEqual(
            list(field.choices),
            [('', "Any"),
             ('year', "Year"),
             ('date', "Exact date"),
             ('date_range', "Date range"),
             ('(none)', "(None)")]
        )

    def test_filter_by_photo_date_any(self):
        self.update_multiple_metadatas(
            'photo_date',
            [(self.imgs[0], datetime.date(2011, 12, 28)),
             (self.imgs[1], datetime.date(2012, 1, 13))])
        # 3 other images left with no date

        # Should include non-null and null dates
        self.assert_search_results(
            dict(),
            [self.imgs[0], self.imgs[1], self.imgs[2],
             self.imgs[3], self.imgs[4]])

    def test_filter_by_photo_date_none(self):
        self.update_multiple_metadatas(
            'photo_date',
            [(self.imgs[0], datetime.date(2011, 12, 28)),
             (self.imgs[1], datetime.date(2012, 1, 13)),
             (self.imgs[2], datetime.date(2013, 8, 4))])
        # 2 other images left with no date

        self.assert_search_results(
            dict(photo_date_0='(none)'),
            [self.imgs[3], self.imgs[4]])

    def test_filter_by_photo_date_year(self):
        self.update_multiple_metadatas(
            'photo_date',
            [(self.imgs[0], datetime.date(2011, 12, 28)),
             (self.imgs[1], datetime.date(2012, 1, 13)),
             (self.imgs[2], datetime.date(2012, 8, 4))])

        self.assert_search_results(
            dict(photo_date_0='year', photo_date_1=2012),
            [self.imgs[1], self.imgs[2]])

    def test_photo_date_year_choices(self):
        self.update_multiple_metadatas(
            'photo_date',
            [(self.imgs[0], datetime.date(2011, 12, 28)),
             (self.imgs[1], datetime.date(2012, 1, 13)),
             (self.imgs[2], datetime.date(2013, 8, 4))])

        self.client.force_login(self.user)
        response = self.client.get(self.url)

        search_form = response.context['image_search_form']
        year_field = search_form.fields['photo_date'].fields[1]
        year_choices = [value for value, label in year_field.choices]
        self.assertListEqual(
            year_choices,
            ['2011', '2012', '2013'])

    def test_filter_by_photo_date_exact_date(self):
        self.update_multiple_metadatas(
            'photo_date',
            [(self.imgs[0], datetime.date(2012, 1, 12)),
             (self.imgs[1], datetime.date(2012, 1, 13)),
             (self.imgs[2], datetime.date(2012, 1, 13))])
        # 2 other images left with no date

        self.assert_search_results(
            dict(photo_date_0='date', photo_date_2=datetime.date(2012, 1, 13)),
            [self.imgs[1], self.imgs[2]])

    def test_filter_by_photo_date_range(self):
        self.update_multiple_metadatas(
            'photo_date',
            [(self.imgs[0], datetime.date(2012, 3, 9)),
             (self.imgs[1], datetime.date(2012, 3, 10)),
             (self.imgs[2], datetime.date(2012, 3, 15)),
             (self.imgs[3], datetime.date(2012, 3, 20)),
             (self.imgs[4], datetime.date(2012, 3, 21))])

        self.assert_search_results(
            dict(
                photo_date_0='date_range',
                photo_date_3=datetime.date(2012, 3, 10),
                photo_date_4=datetime.date(2012, 3, 20),
            ),
            [self.imgs[1], self.imgs[2], self.imgs[3]])

    def test_photo_date_negative_range(self):
        self.update_multiple_metadatas(
            'photo_date',
            [(self.imgs[0], datetime.date(2012, 3, 9)),
             (self.imgs[1], datetime.date(2012, 3, 10))])

        self.assert_search_results(
            dict(
                photo_date_0='date_range',
                photo_date_3=datetime.date(2012, 3, 10),
                photo_date_4=datetime.date(2012, 3, 9),
            ),
            [])

    def test_photo_date_type_invalid(self):
        self.assert_invalid_search(photo_date_0='abc')

    def test_photo_date_year_missing(self):
        self.assert_invalid_search(photo_date_0='year')

    def test_photo_date_year_invalid(self):
        self.assert_invalid_search(
            photo_date_0='year', photo_date_1='not a year')

    def test_photo_date_exact_date_missing(self):
        self.assert_invalid_search(photo_date_0='date')

    def test_photo_date_exact_date_invalid(self):
        self.assert_invalid_search(
            photo_date_0='date', photo_date_2='not a date')

    def test_photo_date_start_date_missing(self):
        self.assert_invalid_search(
            photo_date_0='date_range', photo_date_4=datetime.date(2012, 3, 10))

    def test_photo_date_end_date_missing(self):
        self.assert_invalid_search(
            photo_date_0='date_range', photo_date_3=datetime.date(2012, 3, 10))

    # Last annotation date

    def test_annotation_date_type_choices(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)

        search_form = response.context['image_search_form']
        field = search_form.fields['last_annotated'].fields[0]
        self.assertListEqual(
            list(field.choices),
            [('', "Any"),
             ('year', "Year"),
             ('date', "Exact date"),
             ('date_range', "Date range"),
             ('(none)', "(None)")]
        )

    def test_filter_by_annotation_date_any(self):
        self.set_last_annotation(
            self.imgs[0], dt=datetime.datetime(2011, 12, 28, tzinfo=tz))
        self.set_last_annotation(
            self.imgs[1], dt=datetime.datetime(2012, 1, 13, tzinfo=tz))
        # 3 other images left with no last annotation

        # Should include both null and non-null dates
        self.assert_search_results(
            dict(),
            [self.imgs[0], self.imgs[1], self.imgs[2],
             self.imgs[3], self.imgs[4]])

    def test_filter_by_annotation_date_none(self):
        self.set_last_annotation(
            self.imgs[0], dt=datetime.datetime(2011, 12, 28, tzinfo=tz))
        self.set_last_annotation(
            self.imgs[1], dt=datetime.datetime(2012, 1, 13, tzinfo=tz))
        self.set_last_annotation(
            self.imgs[2], dt=datetime.datetime(2013, 8, 4, tzinfo=tz))
        # 2 other images left with no last annotation

        self.assert_search_results(
            dict(last_annotated_0='(none)'),
            [self.imgs[3], self.imgs[4]])

    def test_annotation_date_year_choices(self):
        self.set_last_annotation(
            self.imgs[0], dt=datetime.datetime(2011, 12, 28, tzinfo=tz))
        self.set_last_annotation(
            self.imgs[1], dt=datetime.datetime(2012, 1, 13, tzinfo=tz))

        self.source.create_date = datetime.datetime(2010, 1, 1, tzinfo=tz)
        self.source.save()

        current_year = timezone.now().year

        self.client.force_login(self.user)
        response = self.client.get(self.url)

        search_form = response.context['image_search_form']
        year_field = search_form.fields['last_annotated'].fields[1]
        year_choices = [value for value, label in year_field.choices]
        # Choices should be based on the source create date and the
        # current year, not based on existing annotation dates. It's done this
        # way for a slight speed optimization.
        self.assertListEqual(
            year_choices,
            [str(year) for year in range(2010, current_year+1)])

    def test_filter_by_annotation_date_exact_date(self):
        # The entire 24 hours of the given date should be included.
        # As an implementation detail, 00:00 of the next day is also included,
        # so we just make sure 00:01 of the next day isn't in.
        self.set_last_annotation(
            self.imgs[0], dt=datetime.datetime(2012, 1, 12, 23, 59, tzinfo=tz))
        self.set_last_annotation(
            self.imgs[1], dt=datetime.datetime(2012, 1, 13, 0, 0, tzinfo=tz))
        self.set_last_annotation(
            self.imgs[2], dt=datetime.datetime(2012, 1, 13, 23, 59, tzinfo=tz))
        self.set_last_annotation(
            self.imgs[3], dt=datetime.datetime(2012, 1, 14, 0, 1, tzinfo=tz))

        self.assert_search_results(
            dict(
                last_annotated_0='date',
                last_annotated_2=datetime.date(2012, 1, 13),
            ),
            [self.imgs[1], self.imgs[2]])

    def test_filter_by_annotation_date_range(self):
        # The given range should be included from day 1 00:00 to day n+1 00:00.
        self.set_last_annotation(
            self.imgs[0], dt=datetime.datetime(2012, 3, 9, 23, 59, tzinfo=tz))
        self.set_last_annotation(
            self.imgs[1], dt=datetime.datetime(2012, 3, 10, 0, 0, tzinfo=tz))
        self.set_last_annotation(
            self.imgs[2], dt=datetime.datetime(2012, 3, 15, 12, 34, tzinfo=tz))
        self.set_last_annotation(
            self.imgs[3], dt=datetime.datetime(2012, 3, 20, 23, 59, tzinfo=tz))
        self.set_last_annotation(
            self.imgs[4], dt=datetime.datetime(2012, 3, 21, 0, 1, tzinfo=tz))

        self.assert_search_results(
            dict(
                last_annotated_0='date_range',
                last_annotated_3=datetime.date(2012, 3, 10),
                last_annotated_4=datetime.date(2012, 3, 20),
            ),
            [self.imgs[1], self.imgs[2], self.imgs[3]])


class LastAnnotatorSearchTest(BaseSearchTest):

    def test_filter_by_annotator_any(self):
        # Regular user
        self.add_annotations(self.user, self.imgs[0], {1: 'A', 2: 'B'})
        # Imported
        self.set_last_annotation(self.imgs[1], annotator=get_imported_user())
        # Alleviate
        self.set_last_annotation(self.imgs[2], annotator=get_alleviate_user())
        # Machine
        robot = self.create_robot(self.source)
        self.add_robot_annotations(robot, self.imgs[3])

        self.assert_search_results(
            dict(),
            [self.imgs[0], self.imgs[1], self.imgs[2],
             self.imgs[3], self.imgs[4]])

    def test_filter_by_annotator_tool_any_user(self):
        # Tool user
        self.add_annotations(self.user, self.imgs[0], {1: 'A', 2: 'B'})

        # Another tool user
        user2 = self.create_user()
        self.add_source_member(
            self.user, self.source, user2, Source.PermTypes.EDIT.code)
        self.add_annotations(user2, self.imgs[1], {1: 'A', 2: 'B'})

        # Non annotation tool
        self.set_last_annotation(self.imgs[2], annotator=get_imported_user())
        self.set_last_annotation(self.imgs[3], annotator=get_alleviate_user())
        robot = self.create_robot(self.source)
        self.add_robot_annotations(robot, self.imgs[4])

        # Unannotated
        self.upload_image(self.user, self.source)

        self.assert_search_results(
            dict(last_annotator_0='annotation_tool'),
            [self.imgs[0], self.imgs[1]])

    def test_filter_by_annotator_tool_specific_user(self):
        self.add_annotations(self.user, self.imgs[0], {1: 'A', 2: 'B'})

        user2 = self.create_user()
        self.add_source_member(
            self.user, self.source, user2, Source.PermTypes.EDIT.code)
        self.add_annotations(user2, self.imgs[1], {1: 'A', 2: 'B'})

        self.assert_search_results(
            dict(
                last_annotator_0='annotation_tool',
                last_annotator_1=user2.pk,
            ),
            [self.imgs[1]])

    def test_annotator_tool_choices(self):
        self.add_annotations(self.user, self.imgs[0], {1: 'A', 2: 'B'})

        user2 = self.create_user()
        self.add_source_member(
            self.user, self.source, user2, Source.PermTypes.EDIT.code)
        self.add_annotations(user2, self.imgs[1], {1: 'A', 2: 'B'})

        user3 = self.create_user()
        self.add_source_member(
            self.user, self.source, user3, Source.PermTypes.EDIT.code)

        self.client.force_login(self.user)
        response = self.client.get(self.url)

        search_form = response.context['image_search_form']
        user_field = search_form.fields['last_annotator'].fields[1]
        user_choices = [username for value, username in user_field.choices]
        # Choices should be based on existing annotations in the source, not
        # based on the source's member list.
        self.assertListEqual(
            user_choices,
            ["Any user"] + sorted([self.user.username, user2.username]))

    def test_filter_by_annotator_alleviate(self):
        self.add_annotations(self.user, self.imgs[0], {1: 'A', 2: 'B'})
        self.set_last_annotation(self.imgs[1], annotator=get_imported_user())
        self.set_last_annotation(self.imgs[2], annotator=get_alleviate_user())
        robot = self.create_robot(self.source)
        self.add_robot_annotations(robot, self.imgs[3])

        self.assert_search_results(
            dict(last_annotator_0='alleviate'),
            [self.imgs[2]])

    def test_filter_by_annotator_importing(self):
        self.add_annotations(self.user, self.imgs[0], {1: 'A', 2: 'B'})
        self.set_last_annotation(self.imgs[1], annotator=get_imported_user())
        self.set_last_annotation(self.imgs[2], annotator=get_alleviate_user())
        robot = self.create_robot(self.source)
        self.add_robot_annotations(robot, self.imgs[3])

        self.assert_search_results(
            dict(last_annotator_0='imported'),
            [self.imgs[1]])

    def test_filter_by_annotator_machine(self):
        self.add_annotations(self.user, self.imgs[0], {1: 'A', 2: 'B'})
        self.set_last_annotation(self.imgs[1], annotator=get_imported_user())
        self.set_last_annotation(self.imgs[2], annotator=get_alleviate_user())
        robot = self.create_robot(self.source)
        self.add_robot_annotations(robot, self.imgs[3])

        self.assert_search_results(
            dict(last_annotator_0='machine'),
            [self.imgs[3]])

    def test_filter_by_annotator_considering_latest_only(self):
        self.add_annotations(self.user, self.imgs[0], {1: 'A', 2: 'B'})

        user2 = self.create_user()
        self.add_source_member(
            self.user, self.source, user2, Source.PermTypes.EDIT.code)
        self.add_annotations(user2, self.imgs[0], {1: 'B'})

        # user isn't the latest annotator of any image now.
        self.assert_search_results(
            dict(
                last_annotator_0='annotation_tool',
                last_annotator_1=self.user.pk,
            ),
            [])
        # user2 is.
        self.assert_search_results(
            dict(
                last_annotator_0='annotation_tool',
                last_annotator_1=user2.pk,
            ),
            [self.imgs[0]])


class SortTest(BaseSearchTest):

    def test_by_name(self):
        self.update_multiple_metadatas(
            'name',
            [(self.imgs[0], 'B'),
             (self.imgs[1], 'A'),
             (self.imgs[2], 'C'),
             (self.imgs[3], 'D'),
             (self.imgs[4], 'E')])

        self.assert_search_results_ordered(
            dict(
                sort_method='name',
                sort_direction='asc',
            ),
            [self.imgs[1], self.imgs[0], self.imgs[2],
             self.imgs[3], self.imgs[4]])

        self.assert_search_results_ordered(
            dict(
                sort_method='name',
                sort_direction='desc',
            ),
            [self.imgs[4], self.imgs[3], self.imgs[2],
             self.imgs[0], self.imgs[1]])

    def test_by_upload(self):
        self.assert_search_results_ordered(
            dict(
                sort_method='upload_date',
                sort_direction='asc',
            ),
            [self.imgs[0], self.imgs[1], self.imgs[2],
             self.imgs[3], self.imgs[4]])

        self.assert_search_results_ordered(
            dict(
                sort_method='upload_date',
                sort_direction='desc',
            ),
            [self.imgs[4], self.imgs[3], self.imgs[2],
             self.imgs[1], self.imgs[0]])

    def test_by_photo_date(self):
        self.update_multiple_metadatas(
            'photo_date',
            [(self.imgs[0], datetime.date(2012, 3, 2)),
             (self.imgs[1], datetime.date(2012, 3, 1)),
             (self.imgs[4], datetime.date(2012, 3, 1))])
        # Other 2 have null date and will be ordered after the ones with date.
        # pk is the tiebreaker.

        self.assert_search_results_ordered(
            dict(
                sort_method='photo_date',
                sort_direction='asc',
            ),
            [self.imgs[1], self.imgs[4], self.imgs[0],
             self.imgs[2], self.imgs[3]])

        self.assert_search_results_ordered(
            dict(
                sort_method='photo_date',
                sort_direction='desc',
            ),
            [self.imgs[3], self.imgs[2], self.imgs[0],
             self.imgs[4], self.imgs[1]])

    def test_by_last_annotated(self):
        self.set_last_annotation(
            self.imgs[0], dt=datetime.datetime(2012, 3, 2, 0, 0, tzinfo=tz))
        self.set_last_annotation(
            self.imgs[1], dt=datetime.datetime(2012, 3, 1, 22, 15, tzinfo=tz))
        self.set_last_annotation(
            self.imgs[4], dt=datetime.datetime(2012, 3, 1, 22, 15, tzinfo=tz))
        # Other 2 have null date and will be ordered after the ones with date.
        # pk is the tiebreaker.

        self.assert_search_results_ordered(
            dict(
                sort_method='last_annotation_date',
                sort_direction='asc',
            ),
            [self.imgs[1], self.imgs[4], self.imgs[0],
             self.imgs[2], self.imgs[3]])

        self.assert_search_results_ordered(
            dict(
                sort_method='last_annotation_date',
                sort_direction='desc',
            ),
            [self.imgs[3], self.imgs[2], self.imgs[0],
             self.imgs[4], self.imgs[1]])


class SearchFormInitializationTest(BaseSearchTest):

    def test_dont_show_metadata_field_if_all_blank_values(self):
        """
        If a metadata field has a blank value for every image, don't show
        that metadata field on the search form.
        """
        self.client.force_login(self.user)
        response = self.client.get(self.url)

        search_form = response.context['image_search_form']
        self.assertFalse('latitude' in search_form.fields)

    def test_dont_show_metadata_field_if_all_same_value(self):
        """
        If a metadata field has the same value for every image, don't show
        that metadata field on the search form.
        """
        self.update_multiple_metadatas(
            'height_in_cm',
            [(self.imgs[0], 50),
             (self.imgs[1], 50),
             (self.imgs[2], 50),
             (self.imgs[3], 50),
             (self.imgs[4], 50)])

        self.client.force_login(self.user)
        response = self.client.get(self.url)

        search_form = response.context['image_search_form']
        self.assertFalse('height_in_cm' in search_form.fields)

    def test_basic_field_after_submit(self):
        self.client.force_login(self.user)
        response = self.submit_search(image_name='DSC')

        search_form = response.context['image_search_form']
        self.assertEqual(search_form['image_name'].data, 'DSC')

    def test_date_year_after_submit(self):
        self.client.force_login(self.user)
        response = self.submit_search(photo_date_0='year', photo_date_1='2012')

        search_form = response.context['image_search_form']
        self.assertListEqual(
            search_form['photo_date'].data, ['year', '2012', '', '', ''])

    def test_exact_date_after_submit(self):
        self.client.force_login(self.user)
        response = self.submit_search(
            photo_date_0='date', photo_date_2=datetime.date(2012, 3, 6))

        search_form = response.context['image_search_form']
        self.assertListEqual(
            search_form['photo_date'].data, ['date', '', '2012-03-06', '', ''])

    def test_date_range_after_submit(self):
        self.client.force_login(self.user)
        response = self.submit_search(
            photo_date_0='date_range',
            photo_date_3=datetime.date(2012, 3, 6),
            photo_date_4=datetime.date(2013, 4, 7),
        )

        search_form = response.context['image_search_form']
        self.assertListEqual(
            search_form['photo_date'].data,
            ['date_range', '', '', '2012-03-06', '2013-04-07'])

    def test_annotator_non_tool_after_submit(self):
        self.client.force_login(self.user)
        response = self.submit_search(
            last_annotator_0='alleviate',
        )

        search_form = response.context['image_search_form']
        self.assertListEqual(
            search_form['last_annotator'].data,
            ['alleviate', ''])

    def test_annotator_tool_any_after_submit(self):
        self.client.force_login(self.user)
        response = self.submit_search(
            last_annotator_0='annotation_tool',
        )

        search_form = response.context['image_search_form']
        self.assertListEqual(
            search_form['last_annotator'].data,
            ['annotation_tool', ''])

    def test_annotator_tool_user_after_submit(self):
        self.client.force_login(self.user)
        self.add_annotations(self.user, self.imgs[0], {1: 'A', 2: 'B'})
        response = self.submit_search(
            last_annotator_0='annotation_tool',
            last_annotator_1=self.user.pk,
        )

        search_form = response.context['image_search_form']
        self.assertListEqual(
            search_form['last_annotator'].data,
            ['annotation_tool', str(self.user.pk)])


# Make it easy to get multiple pages of results.
@override_settings(BROWSE_DEFAULT_THUMBNAILS_PER_PAGE=3)
class ResultsAndPagesTest(ClientTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)
        cls.url = reverse('browse_images', args=[cls.source.pk])

        cls.imgs = [
            cls.upload_image(cls.user, cls.source) for _ in range(10)
        ]

    def test_zero_results(self):
        post_data = default_search_params.copy()
        post_data['photo_date_0'] = 'date'
        post_data['photo_date_2'] = datetime.date(2000, 1, 1)

        self.client.force_login(self.user)
        response = self.client.post(self.url, post_data)
        self.assertEqual(
            response.context['page_results'].paginator.count, 0)

        self.assertContains(response, "No image results.")

    def test_one_page_results(self):
        post_data = default_search_params.copy()
        post_data['aux1'] = 'Site1'

        self.imgs[0].metadata.aux1 = 'Site1'
        self.imgs[0].metadata.save()
        self.imgs[1].metadata.aux1 = 'Site1'
        self.imgs[1].metadata.save()

        self.client.force_login(self.user)
        response = self.client.post(self.url, post_data)
        self.assertEqual(
            response.context['page_results'].paginator.count, 2)

        # html=True is used so that extra whitespace is ignored.
        # There is a tradeoff though: The element name (span) and attributes
        # (none here) must be matched as well.
        self.assertContains(
            response, "<span>Showing 1-2 of 2</span>", html=True)
        self.assertContains(response, "<span>Page 1 of 1</span>", html=True)

    def test_multiple_pages_results(self):
        post_data = default_search_params.copy()
        post_data['aux1'] = ''

        self.client.force_login(self.user)
        response = self.client.post(self.url, post_data)
        self.assertEqual(
            response.context['page_results'].paginator.count, 10)

        self.assertContains(
            response, "<span>Showing 1-3 of 10</span>", html=True)
        self.assertContains(response, "<span>Page 1 of 4</span>", html=True)

    def test_page_two(self):
        post_data = default_search_params.copy()
        post_data['aux1'] = ''
        post_data['page'] = 2

        self.client.force_login(self.user)
        response = self.client.post(self.url, post_data)
        self.assertEqual(
            response.context['page_results'].paginator.count, 10)

        self.assertContains(
            response, "<span>Showing 4-6 of 10</span>", html=True)
        self.assertContains(response, "<span>Page 2 of 4</span>", html=True)


class ImageStatusIndicatorTest(ClientTest):
    """
    Test the border styling which indicate the status of each image.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user,
            # Make it easy to have confirmed and partially annotated images
            default_point_generation_method=dict(type='simple', points=2))
        labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, labels)

    def test_status_indicator(self):
        robot = self.create_robot(self.source)

        img_unannotated = self.upload_image(self.user, self.source)

        img_unconfirmed = self.upload_image(self.user, self.source)
        self.add_robot_annotations(robot, img_unconfirmed)

        img_partially_confirmed = self.upload_image(self.user, self.source)
        self.add_robot_annotations(robot, img_partially_confirmed)
        self.add_annotations(self.user, img_partially_confirmed, {1: 'A'})

        img_confirmed = self.upload_image(self.user, self.source)
        self.add_robot_annotations(robot, img_confirmed)
        self.add_annotations(self.user, img_confirmed, {1: 'A', 2: 'B'})

        response = self.client.get(
            reverse('browse_images', args=[self.source.pk]))

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
