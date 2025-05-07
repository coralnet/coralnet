import datetime
from unittest import mock

from bs4 import BeautifulSoup
from django.core.cache import cache
from django.db import IntegrityError
from django.shortcuts import resolve_url
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape as html_escape

from accounts.utils import is_alleviate_user, is_robot_user
from lib.tests.utils import BasePermissionTest, ClientTest
from sources.models import Source
from visualization.tests.utils import BROWSE_IMAGES_DEFAULT_SEARCH_PARAMS
from ..models import Annotation, AnnotationToolAccess, AnnotationToolSettings
from .utils import AnnotationHistoryTestMixin

tz = timezone.get_current_timezone()


class PermissionTest(BasePermissionTest):
    """
    Test page and Ajax-submit permissions for annotation tool related views.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.img = cls.upload_image(cls.user, cls.source)
        cls.labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, cls.labels)

    def test_annotation_tool(self):
        url = reverse('annotation_tool', args=[self.img.pk])
        template = 'annotations/annotation_tool.html'

        self.source_to_private()
        self.assertPermissionLevel(url, self.SOURCE_EDIT, template=template)
        self.source_to_public()
        self.assertPermissionLevel(url, self.SOURCE_EDIT, template=template)

    def test_save_annotations_ajax(self):
        url = reverse('save_annotations_ajax', args=[self.img.pk])

        self.source_to_private()
        self.assertPermissionLevel(
            url, self.SOURCE_EDIT, is_json=True, post_data={})
        self.source_to_public()
        self.assertPermissionLevel(
            url, self.SOURCE_EDIT, is_json=True, post_data={})

    def test_is_annotation_all_done_ajax(self):
        url = reverse('is_annotation_all_done_ajax', args=[self.img.pk])

        self.source_to_private()
        self.assertPermissionLevel(
            url, self.SOURCE_VIEW, is_json=True, post_data={})
        self.source_to_public()
        self.assertPermissionLevel(
            url, self.SOURCE_VIEW, is_json=True, post_data={})

    def test_annotation_tool_settings_save(self):
        url = reverse('annotation_tool_settings_save')

        self.assertPermissionLevel(
            url, self.SIGNED_IN, is_json=True, post_data={},
            deny_type=self.REQUIRE_LOGIN)


class NoLabelsetTest(ClientTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)
        cls.img = cls.upload_image(cls.user, cls.source)

    def test(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('annotation_tool', args=[self.img.pk]),
        )
        self.assertContains(
            response, html_escape(
                "You need to create a labelset for your source"
                " before you can annotate images."))
        self.assertTemplateUsed(response, 'labels/labelset_required.html')


class LoadImageTest(ClientTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()

        cls.source = cls.create_source(cls.user)
        labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, labels)

    def test_small_image(self):
        img = self.upload_image(
            self.user, self.source, dict(width=400, height=300))
        url = reverse('annotation_tool', args=[img.pk])

        self.client.force_login(self.user)
        response = self.client.get(url)
        self.assertStatusOK(response)
        self.assertTemplateUsed(response, 'annotations/annotation_tool.html')

        # Try fetching the page a second time, to make sure thumbnail
        # generation doesn't go nuts.
        response = self.client.get(url)
        self.assertStatusOK(response)

    def test_large_image(self):
        img = self.upload_image(
            self.user, self.source, dict(width=1600, height=1200))
        url = reverse('annotation_tool', args=[img.pk])

        self.client.force_login(self.user)
        response = self.client.get(url)
        self.assertStatusOK(response)
        self.assertTemplateUsed(response, 'annotations/annotation_tool.html')

        # Try fetching the page a second time, to make sure thumbnail
        # generation doesn't go nuts.
        response = self.client.get(url)
        self.assertStatusOK(response)


class NavigationTest(ClientTest):
    """
    Test the annotation tool buttons that let you navigate to other images.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()

        cls.source = cls.create_source(cls.user)
        cls.labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, cls.labels)

        cls.img1 = cls.upload_image(cls.user, cls.source)
        cls.img2 = cls.upload_image(cls.user, cls.source)
        cls.img3 = cls.upload_image(cls.user, cls.source)
        cls.img4 = cls.upload_image(cls.user, cls.source)
        cls.img5 = cls.upload_image(cls.user, cls.source)
        # Default ordering is by name, so this ensures they're in order
        cls.update_multiple_metadatas(
            'name',
            [(cls.img1, '1.png'),
             (cls.img2, '2.png'),
             (cls.img3, '3.png'),
             (cls.img4, '4.png'),
             (cls.img5, '5.png')])

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

    def enter_annotation_tool(self, search_kwargs, current_image):
        data = BROWSE_IMAGES_DEFAULT_SEARCH_PARAMS.copy()
        data.update(**search_kwargs)
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('annotation_tool', args=[current_image.pk]), data)
        return response

    def assert_navigation_details(
            self, search_kwargs, current_image,
            expected_prev=None, expected_next=None,
            expected_x_of_y_display=None, expected_search_display=None):

        response = self.enter_annotation_tool(search_kwargs, current_image)

        if expected_prev:
            self.assertEqual(
                response.context['prev_image'].pk, expected_prev.pk)
        if expected_next:
            self.assertEqual(
                response.context['next_image'].pk, expected_next.pk)
        if expected_x_of_y_display:
            # This isn't a particularly strict check; it just checks that the
            # given text is on the page.
            self.assertContains(response, expected_x_of_y_display)
        if expected_search_display:
            # Also not a particularly strict check.
            self.assertContains(response, expected_search_display)

    def test_basic_prev_next(self):
        self.assert_navigation_details(
            dict(), self.img2,
            expected_prev=self.img1, expected_next=self.img3)

    def test_next_wrap_to_first(self):
        self.assert_navigation_details(
            dict(), self.img5,
            expected_next=self.img1)

    def test_prev_wrap_to_last(self):
        self.assert_navigation_details(
            dict(), self.img1,
            expected_prev=self.img5)

    def test_search_filter_aux_meta(self):
        # Exclude img2 with the filter
        self.update_multiple_metadatas(
            'aux1',
            [(self.img1, 'SiteA'),
             (self.img2, 'SiteB'),
             (self.img3, 'SiteA')])

        # img1 next -> img3
        self.assert_navigation_details(
            dict(aux1='SiteA'), self.img1,
            expected_next=self.img3,
            expected_x_of_y_display="Image 1 of 2",
            expected_search_display="Filtering by aux1;")

    def test_search_filter_photo_date_year(self):
        # Exclude img2 with the filter
        self.update_multiple_metadatas(
            'photo_date',
            [(self.img1, datetime.date(2020, 4, 9)),
             (self.img2, datetime.date(2019, 12, 31)),
             (self.img3, datetime.date(2020, 1, 1))])

        self.assert_navigation_details(
            dict(photo_date_0='year', photo_date_1='2020'), self.img1,
            expected_next=self.img3,
            expected_x_of_y_display="Image 1 of 2",
            expected_search_display="Filtering by photo date;")

    def test_search_filter_photo_date_exact_date(self):
        # Exclude img2 with the filter
        self.update_multiple_metadatas(
            'photo_date',
            [(self.img1, datetime.date(2020, 4, 1)),
             (self.img2, datetime.date(2020, 4, 2)),
             (self.img3, datetime.date(2020, 4, 1))])

        self.assert_navigation_details(
            dict(photo_date_0='date', photo_date_2='2020-04-01'), self.img1,
            expected_next=self.img3,
            expected_x_of_y_display="Image 1 of 2",
            expected_search_display="Filtering by photo date;")

    def test_search_filter_photo_date_range(self):
        # Exclude img2 with the filter
        self.update_multiple_metadatas(
            'photo_date',
            [(self.img1, datetime.date(2020, 3, 18)),
             (self.img2, datetime.date(2020, 3, 21)),
             (self.img3, datetime.date(2020, 3, 12))])

        self.assert_navigation_details(
            dict(
                photo_date_0='date_range',
                photo_date_3='2020-03-10',
                photo_date_4='2020-03-20',
            ),
            self.img1,
            expected_next=self.img3,
            expected_x_of_y_display="Image 1 of 2",
            expected_search_display="Filtering by photo date;")

    def test_search_filter_annotation_date_range(self):
        # Exclude img2 with the filter
        self.set_last_annotation(
            self.img1, dt=datetime.datetime(2020, 3, 10, 0, 0, tzinfo=tz))
        self.set_last_annotation(
            self.img2, dt=datetime.datetime(2020, 3, 21, 0, 1, tzinfo=tz))
        self.set_last_annotation(
            self.img3, dt=datetime.datetime(2020, 3, 20, 23, 59, tzinfo=tz))

        self.assert_navigation_details(
            dict(
                last_annotated_0='date_range',
                last_annotated_3='2020-03-10',
                last_annotated_4='2020-03-20',
            ),
            self.img1,
            expected_next=self.img3,
            expected_x_of_y_display="Image 1 of 2",
            expected_search_display="Filtering by last annotation date;")

    def test_search_filter_annotator(self):
        user2 = self.create_user()
        self.add_source_member(
            self.user, self.source, user2, Source.PermTypes.EDIT.code)

        # Exclude img2 with the filter
        self.set_last_annotation(
            self.img1, annotator=self.user)
        self.set_last_annotation(
            self.img2, annotator=user2)
        self.set_last_annotation(
            self.img3, annotator=self.user)

        self.assert_navigation_details(
            dict(
                last_annotator_0='annotation_tool',
                last_annotator_1=self.user.pk,
            ),
            self.img1,
            expected_next=self.img3,
            expected_x_of_y_display="Image 1 of 2",
            expected_search_display="Filtering by last annotator;")

    def test_image_id_range_filter(self):
        # Exclude img1 and img5 with the filter
        self.assert_navigation_details(
            dict(
                image_id_range=f'{self.img2.pk}_{self.img4.pk}',
            ),
            self.img3,
            expected_prev=self.img2,
            expected_next=self.img4,
            expected_x_of_y_display="Image 2 of 3",
            expected_search_display=(
                "Filtering by upload date;"))

    def test_search_filter_multiple_keys(self):
        user2 = self.create_user()
        self.add_source_member(
            self.user, self.source, user2, Source.PermTypes.EDIT.code)

        img4 = self.upload_image(self.user, self.source)

        # Exclude img2 and img3 with the filters
        self.set_last_annotation(
            self.img1, annotator=self.user,
            dt=datetime.datetime(2020, 3, 10, 0, 0, tzinfo=tz))
        # In date range, but wrong user
        self.set_last_annotation(
            self.img2, annotator=user2,
            dt=datetime.datetime(2020, 3, 10, 0, 0, tzinfo=tz))
        # Right user, but not in date range
        self.set_last_annotation(
            self.img3, annotator=self.user,
            dt=datetime.datetime(2020, 3, 21, 0, 1, tzinfo=tz))
        self.set_last_annotation(
            img4, annotator=self.user,
            dt=datetime.datetime(2020, 3, 20, 23, 59, tzinfo=tz))

        self.assert_navigation_details(
            dict(
                last_annotator_0='annotation_tool',
                last_annotator_1=self.user.pk,
                last_annotated_0='date_range',
                last_annotated_3='2020-03-10',
                last_annotated_4='2020-03-20',
            ),
            self.img1,
            expected_next=img4,
            expected_x_of_y_display="Image 1 of 2",
            expected_search_display=(
                "Filtering by last annotation date, last annotator;"),
        )

    def test_image_id_set_filter(self):
        # Exclude img2 with the filter
        self.assert_navigation_details(
            dict(
                image_form_type='ids',
                ids=','.join([str(self.img1.pk), str(self.img3.pk)]),
            ),
            self.img3,
            expected_prev=self.img1,
            expected_x_of_y_display="Image 2 of 2",
            expected_search_display=(
                "Filtering to a specific set of images"))

    def test_sort_by_name(self):
        self.update_multiple_metadatas(
            'name',
            [(self.img1, 'B'),
             (self.img2, 'A'),
             (self.img3, 'C'),
             (self.img4, 'D'),
             (self.img5, 'E')])

        # Ascending

        self.assert_navigation_details(
            dict(sort_method='name', sort_direction='asc'), self.img2,
            expected_prev=self.img5, expected_next=self.img1,
            expected_x_of_y_display="Image 1 of 5",
            expected_search_display=(
                "Sorting by name, ascending"))

        self.assert_navigation_details(
            dict(sort_method='name', sort_direction='asc'), self.img3,
            expected_prev=self.img1, expected_next=self.img4,
            expected_x_of_y_display="Image 3 of 5")

        self.assert_navigation_details(
            dict(sort_method='name', sort_direction='asc'), self.img5,
            expected_prev=self.img4, expected_next=self.img2,
            expected_x_of_y_display="Image 5 of 5")

        # Descending

        self.assert_navigation_details(
            dict(sort_method='name', sort_direction='desc'), self.img5,
            expected_prev=self.img2, expected_next=self.img4,
            expected_x_of_y_display="Image 1 of 5",
            expected_search_display=(
                "Sorting by name, descending"))

        self.assert_navigation_details(
            dict(sort_method='name', sort_direction='desc'), self.img3,
            expected_prev=self.img4, expected_next=self.img1,
            expected_x_of_y_display="Image 3 of 5")

        self.assert_navigation_details(
            dict(sort_method='name', sort_direction='desc'), self.img2,
            expected_prev=self.img1, expected_next=self.img5,
            expected_x_of_y_display="Image 5 of 5")

    def test_sort_by_upload(self):

        # Ascending

        self.assert_navigation_details(
            dict(sort_method='upload_date', sort_direction='asc'), self.img1,
            expected_prev=self.img5, expected_next=self.img2,
            expected_x_of_y_display="Image 1 of 5",
            expected_search_display=(
                "Sorting by upload date, ascending"))

        self.assert_navigation_details(
            dict(sort_method='upload_date', sort_direction='asc'), self.img3,
            expected_prev=self.img2, expected_next=self.img4,
            expected_x_of_y_display="Image 3 of 5")

        self.assert_navigation_details(
            dict(sort_method='upload_date', sort_direction='asc'), self.img5,
            expected_prev=self.img4, expected_next=self.img1,
            expected_x_of_y_display="Image 5 of 5")

        # Descending

        self.assert_navigation_details(
            dict(sort_method='upload_date', sort_direction='desc'), self.img5,
            expected_prev=self.img1, expected_next=self.img4,
            expected_x_of_y_display="Image 1 of 5",
            expected_search_display=(
                "Sorting by upload date, descending"))

        self.assert_navigation_details(
            dict(sort_method='upload_date', sort_direction='desc'), self.img3,
            expected_prev=self.img4, expected_next=self.img2,
            expected_x_of_y_display="Image 3 of 5")

        self.assert_navigation_details(
            dict(sort_method='upload_date', sort_direction='desc'), self.img1,
            expected_prev=self.img2, expected_next=self.img5,
            expected_x_of_y_display="Image 5 of 5")

    def test_sort_by_photo_date(self):
        self.update_multiple_metadatas(
            'photo_date',
            [(self.img1, datetime.date(2012, 3, 2)),
             (self.img2, datetime.date(2012, 3, 1)),
             (self.img5, datetime.date(2012, 3, 1))])
        # Other 2 have null date and will be ordered after the ones with date.
        # pk is the tiebreaker.

        # Ascending
        # We'll test more images to make sure ties behave as expected.

        self.assert_navigation_details(
            dict(sort_method='photo_date', sort_direction='asc'), self.img2,
            expected_prev=self.img4, expected_next=self.img5,
            expected_x_of_y_display="Image 1 of 5",
            expected_search_display=(
                "Sorting by photo date, ascending"))

        self.assert_navigation_details(
            dict(sort_method='photo_date', sort_direction='asc'), self.img5,
            expected_prev=self.img2, expected_next=self.img1,
            expected_x_of_y_display="Image 2 of 5")

        self.assert_navigation_details(
            dict(sort_method='photo_date', sort_direction='asc'), self.img1,
            expected_prev=self.img5, expected_next=self.img3,
            expected_x_of_y_display="Image 3 of 5")

        self.assert_navigation_details(
            dict(sort_method='photo_date', sort_direction='asc'), self.img3,
            expected_prev=self.img1, expected_next=self.img4,
            expected_x_of_y_display="Image 4 of 5")

        self.assert_navigation_details(
            dict(sort_method='photo_date', sort_direction='asc'), self.img4,
            expected_prev=self.img3, expected_next=self.img2,
            expected_x_of_y_display="Image 5 of 5")

        # Descending

        self.assert_navigation_details(
            dict(sort_method='photo_date', sort_direction='desc'), self.img4,
            expected_prev=self.img2, expected_next=self.img3,
            expected_x_of_y_display="Image 1 of 5",
            expected_search_display=(
                "Sorting by photo date, descending"))

        self.assert_navigation_details(
            dict(sort_method='photo_date', sort_direction='desc'), self.img3,
            expected_prev=self.img4, expected_next=self.img1,
            expected_x_of_y_display="Image 2 of 5")

        self.assert_navigation_details(
            dict(sort_method='photo_date', sort_direction='desc'), self.img1,
            expected_prev=self.img3, expected_next=self.img5,
            expected_x_of_y_display="Image 3 of 5")

        self.assert_navigation_details(
            dict(sort_method='photo_date', sort_direction='desc'), self.img5,
            expected_prev=self.img1, expected_next=self.img2,
            expected_x_of_y_display="Image 4 of 5")

        self.assert_navigation_details(
            dict(sort_method='photo_date', sort_direction='desc'), self.img2,
            expected_prev=self.img5, expected_next=self.img4,
            expected_x_of_y_display="Image 5 of 5")

    def test_sort_by_last_annotated(self):
        self.set_last_annotation(
            self.img1, dt=datetime.datetime(2012, 3, 2, 0, 0, tzinfo=tz))
        self.set_last_annotation(
            self.img2, dt=datetime.datetime(2012, 3, 1, 22, 15, tzinfo=tz))
        self.set_last_annotation(
            self.img5, dt=datetime.datetime(2012, 3, 1, 22, 15, tzinfo=tz))
        # Other 2 have null date and will be ordered after the ones with date.
        # pk is the tiebreaker.

        # Ascending

        self.assert_navigation_details(
            dict(sort_method='last_annotation_date', sort_direction='asc'),
            self.img2,
            expected_prev=self.img4, expected_next=self.img5,
            expected_x_of_y_display="Image 1 of 5",
            expected_search_display=(
                "Sorting by last annotation date, ascending"))

        self.assert_navigation_details(
            dict(sort_method='last_annotation_date', sort_direction='asc'),
            self.img5,
            expected_prev=self.img2, expected_next=self.img1,
            expected_x_of_y_display="Image 2 of 5")

        self.assert_navigation_details(
            dict(sort_method='last_annotation_date', sort_direction='asc'),
            self.img1,
            expected_prev=self.img5, expected_next=self.img3,
            expected_x_of_y_display="Image 3 of 5")

        self.assert_navigation_details(
            dict(sort_method='last_annotation_date', sort_direction='asc'),
            self.img3,
            expected_prev=self.img1, expected_next=self.img4,
            expected_x_of_y_display="Image 4 of 5")

        self.assert_navigation_details(
            dict(sort_method='last_annotation_date', sort_direction='asc'),
            self.img4,
            expected_prev=self.img3, expected_next=self.img2,
            expected_x_of_y_display="Image 5 of 5")

        # Descending

        self.assert_navigation_details(
            dict(sort_method='last_annotation_date', sort_direction='desc'),
            self.img4,
            expected_prev=self.img2, expected_next=self.img3,
            expected_x_of_y_display="Image 1 of 5",
            expected_search_display=(
                "Sorting by last annotation date, descending"))

        self.assert_navigation_details(
            dict(sort_method='last_annotation_date', sort_direction='desc'),
            self.img3,
            expected_prev=self.img4, expected_next=self.img1,
            expected_x_of_y_display="Image 2 of 5")

        self.assert_navigation_details(
            dict(sort_method='last_annotation_date', sort_direction='desc'),
            self.img1,
            expected_prev=self.img3, expected_next=self.img5,
            expected_x_of_y_display="Image 3 of 5")

        self.assert_navigation_details(
            dict(sort_method='last_annotation_date', sort_direction='desc'),
            self.img5,
            expected_prev=self.img1, expected_next=self.img2,
            expected_x_of_y_display="Image 4 of 5")

        self.assert_navigation_details(
            dict(sort_method='last_annotation_date', sort_direction='desc'),
            self.img2,
            expected_prev=self.img5, expected_next=self.img4,
            expected_x_of_y_display="Image 5 of 5")


class ReturnToBrowseTest(ClientTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()

        cls.source = cls.create_source(cls.user)
        cls.labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, cls.labels)

        cls.img1 = cls.upload_image(
            cls.user, cls.source, dict(filename='1.png'))
        cls.img2 = cls.upload_image(
            cls.user, cls.source, dict(filename='2.png'))
        cls.img3 = cls.upload_image(
            cls.user, cls.source, dict(filename='3.png'))

    def assert_return_to_browse_link(
        self, search_kwargs, current_image
    ):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('annotation_tool', args=[current_image.pk]), search_kwargs)

        response_soup = BeautifulSoup(response.content, 'html.parser')
        return_link = response_soup.find(
            'a', dict(id='return-to-browse-link'))
        href = return_link.attrs.get('href')

        expected_base_url = reverse('browse_images', args=[self.source.pk])
        if search_kwargs is not None:
            expected_query_string = '&'.join(
                [f'{k}={v.replace(",", "%2C")}'
                 for k, v in search_kwargs.items()])
            expected_href = f'{expected_base_url}?{expected_query_string}'
        else:
            expected_href = expected_base_url

        self.assertEqual(
            href,
            expected_href,
            msg="Return-to-browse link href should be as expected",
        )

    def test_return_to_browse_no_filters(self):
        self.assert_return_to_browse_link(None, self.img1)

    def test_return_to_browse_with_search_filters(self):
        search_kwargs = dict(
            image_form_type='search',
            sort_method='name',
            sort_direction='asc',
            image_name='1',
        )
        self.assert_return_to_browse_link(search_kwargs, self.img1)

    def test_return_to_browse_with_id_set_filter(self):
        search_kwargs = dict(
            image_form_type='ids',
            ids=','.join([str(self.img1.pk), str(self.img3.pk)]),
        )
        self.assert_return_to_browse_link(search_kwargs, self.img1)


class LoadAnnotationFormTest(ClientTest):
    """
    Test that the annotation form (with one label-code field per point)
    loads the existing annotations correctly.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()

        cls.source = cls.create_source(
            cls.user, visibility=Source.VisibilityTypes.PUBLIC,
            default_point_generation_method=dict(type='simple', points=3),
        )
        labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, labels)

        cls.img = cls.upload_image(cls.user, cls.source)

    def assert_annotation_form_values_equal(
            self, response, expected_form_values):

        response_soup = BeautifulSoup(response.content, 'html.parser')
        annotation_list = response_soup.find('form', dict(id='annotationForm'))

        for point_num, pair in enumerate(expected_form_values, 1):
            label_code, is_robot = pair

            label_code_field = annotation_list.find(
                'input', dict(name='label_{n}'.format(n=point_num)))
            self.assertEqual(label_code_field.attrs.get('value'), label_code)

            robot_field = annotation_list.find(
                'input', dict(name='robot_{n}'.format(n=point_num)))
            self.assertEqual(robot_field.attrs.get('value'), is_robot)

    def test_all_annotations_blank(self):
        self.client.force_login(self.user)
        response = self.client.get(resolve_url('annotation_tool', self.img.id))
        self.assert_annotation_form_values_equal(
            response, [(None, 'null'), (None, 'null'), (None, 'null')])

    def test_all_unconfirmed(self):
        robot = self.create_robot(self.source)
        self.add_robot_annotations(robot, self.img, {1: 'A', 2: 'B', 3: 'A'})

        # Create a settings object with default settings
        self.user.annotationtoolsettings = AnnotationToolSettings()
        self.user.annotationtoolsettings.save()
        self.client.force_login(self.user)

        # Showing machine annotations
        self.user.annotationtoolsettings.show_machine_annotations = True
        self.user.annotationtoolsettings.save()
        response = self.client.get(resolve_url('annotation_tool', self.img.id))
        self.assert_annotation_form_values_equal(
            response, [('A', 'true'), ('B', 'true'), ('A', 'true')])

        # Not showing machine annotations
        self.user.annotationtoolsettings.show_machine_annotations = False
        self.user.annotationtoolsettings.save()
        response = self.client.get(resolve_url('annotation_tool', self.img.id))
        self.assert_annotation_form_values_equal(
            response, [(None, 'null'), (None, 'null'), (None, 'null')])

    def test_some_confirmed_some_blank(self):
        annotations = {1: 'A', 3: 'B'}
        self.add_annotations(self.user, self.img, annotations)

        self.client.force_login(self.user)
        response = self.client.get(resolve_url('annotation_tool', self.img.id))
        self.assert_annotation_form_values_equal(
            response, [('A', 'false'), (None, 'null'), ('B', 'false')])

    def test_some_confirmed_some_unconfirmed(self):
        robot = self.create_robot(self.source)
        self.add_robot_annotations(robot, self.img, {1: 'A', 2: 'B', 3: 'A'})
        self.add_annotations(self.user, self.img, {1: 'B', 2: 'B'})

        # Create a settings object with default settings
        self.user.annotationtoolsettings = AnnotationToolSettings()
        self.user.annotationtoolsettings.save()
        self.client.force_login(self.user)

        # Showing machine annotations
        self.user.annotationtoolsettings.show_machine_annotations = True
        self.user.annotationtoolsettings.save()
        response = self.client.get(resolve_url('annotation_tool', self.img.id))
        self.assert_annotation_form_values_equal(
            response, [('B', 'false'), ('B', 'false'), ('A', 'true')])

        # Not showing machine annotations
        self.user.annotationtoolsettings.show_machine_annotations = False
        self.user.annotationtoolsettings.save()
        response = self.client.get(resolve_url('annotation_tool', self.img.id))
        self.assert_annotation_form_values_equal(
            response, [('B', 'false'), ('B', 'false'), (None, 'null')])

    def test_all_confirmed(self):
        self.add_annotations(self.user, self.img, {1: 'A', 2: 'B', 3: 'A'})

        self.client.force_login(self.user)
        response = self.client.get(resolve_url('annotation_tool', self.img.id))
        self.assert_annotation_form_values_equal(
            response, [('A', 'false'), ('B', 'false'), ('A', 'false')])


class IsAnnotationAllDoneTest(ClientTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()

        cls.source = cls.create_source(
            cls.user, visibility=Source.VisibilityTypes.PUBLIC,
            default_point_generation_method=dict(type='simple', points=3),
        )
        labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, labels)

        cls.img = cls.upload_image(cls.user, cls.source)
        cls.url = reverse(
            'is_annotation_all_done_ajax', args=[cls.img.pk])

    def test_some_confirmed(self):
        annotations = {1: 'A', 2: 'B'}
        self.add_annotations(self.user, self.img, annotations)

        self.client.force_login(self.user)
        response = self.client.get(self.url).json()

        self.assertTrue('error' not in response)
        # Not done
        self.assertFalse(response['all_done'])

    def test_some_confirmed_others_unconfirmed(self):
        robot = self.create_robot(self.source)
        # Unconfirmed
        self.add_robot_annotations(robot, self.img, {1: 'A', 2: 'A', 3: 'B'})
        # Confirmed
        self.add_annotations(self.user, self.img, {1: 'A', 2: 'B'})

        self.client.force_login(self.user)
        response = self.client.get(self.url).json()

        self.assertTrue('error' not in response)
        # Not done
        self.assertFalse(response['all_done'])

    def test_all_confirmed(self):
        annotations = {1: 'A', 2: 'B', 3: 'A'}
        self.add_annotations(self.user, self.img, annotations)

        self.client.force_login(self.user)
        response = self.client.get(self.url).json()

        self.assertTrue('error' not in response)
        # Done
        self.assertTrue(response['all_done'])


class SaveAnnotationsTest(ClientTest, AnnotationHistoryTestMixin):
    """Test submitting the annotation form which is available at the right side
    of the annotation tool."""
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()

        cls.source = cls.create_source(
            cls.user, visibility=Source.VisibilityTypes.PUBLIC,
            default_point_generation_method=dict(type='simple', points=3),
        )
        labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, labels)

        cls.user_editor = cls.create_user()
        cls.add_source_member(
            cls.user, cls.source, cls.user_editor, Source.PermTypes.EDIT.code)

        cls.img = cls.upload_image(cls.user, cls.source)
        cls.url = reverse(
            'save_annotations_ajax', kwargs=dict(image_id=cls.img.pk))

    def assert_didnt_save_anything(self):
        self.assertEqual(self.img.annotation_set.count(), 0)

        response = self.view_history(self.user, img=self.img)
        self.assert_history_table_equals(
            response,
            []
        )

    def test_cant_delete_existing_annotation(self):
        """If a point already has an annotation in the DB, submitting a blank
        field has no effect on that annotation."""
        robot = self.create_robot(self.source)
        self.add_robot_annotations(robot, self.img, {1: 'A', 2: 'B', 3: 'B'})
        self.add_annotations(self.user, self.img, {2: 'A'})

        # Attempt to delete 1 (unconfirmed) and 2 (confirmed)
        data = dict(
            label_1='', label_2='', label_3='B',
            robot_1='null', robot_2='null', robot_3='true',
        )
        self.client.force_login(self.user)
        response = self.client.post(self.url, data).json()
        self.assertTrue('error' not in response)

        # Those annotations should still exist
        annotation_1 = Annotation.objects.get(
            image__pk=self.img.pk, point__point_number=1)
        self.assertEqual(annotation_1.label_code, 'A')
        self.assertTrue(is_robot_user(annotation_1.user))
        annotation_2 = Annotation.objects.get(
            image__pk=self.img.pk, point__point_number=2)
        self.assertEqual(annotation_2.label_code, 'A')
        self.assertEqual(annotation_2.user.username, self.user.username)

    def test_cant_add_unconfirmed_annotation(self):
        """No annotation -> unconfirmed annotation is not possible through
        the annotation tool. This is a weird case, but it's still a good
        regression test to see if annotation logic has changed in any way."""
        # Try to add 3
        data = dict(
            label_1='', label_2='', label_3='B',
            robot_1='null', robot_2='null', robot_3='true',
        )
        self.client.force_login(self.user)
        response = self.client.post(self.url, data).json()
        self.assertTrue('error' not in response)

        # There should still be no annotation for this point
        self.assertRaises(
            Annotation.DoesNotExist,
            Annotation.objects.get,
            image__pk=self.img.pk, point__point_number=3)

    def test_newly_annotated_point(self):
        """No annotation -> confirmed annotation."""
        # Add 3
        data = dict(
            label_1='', label_2='', label_3='B',
            robot_1='null', robot_2='null', robot_3='false',
        )
        self.client.force_login(self.user)
        response = self.client.post(self.url, data).json()
        self.assertTrue('error' not in response)

        annotation_3 = Annotation.objects.get(
            image__pk=self.img.pk, point__point_number=3)
        self.assertEqual(annotation_3.label_code, 'B')
        self.assertEqual(annotation_3.user.username, self.user.username)

        response = self.view_history(self.user)
        self.assert_history_table_equals(
            response,
            [
                ['Point 3: B',
                 f'{self.user.username}'],
            ]
        )

    def test_confirm_an_unconfirmed_annotation(self):
        robot = self.create_robot(self.source)
        self.add_robot_annotations(robot, self.img, {1: 'A', 2: 'B', 3: 'B'})

        # Confirm 1
        data = dict(
            label_1='A', label_2='B', label_3='B',
            robot_1='false', robot_2='true', robot_3='true',
        )
        self.client.force_login(self.user)
        response = self.client.post(self.url, data).json()
        self.assertTrue('error' not in response)

        annotation_1 = Annotation.objects.get(
            image__pk=self.img.pk, point__point_number=1)
        self.assertEqual(annotation_1.label_code, 'A')
        self.assertEqual(annotation_1.user.username, self.user.username)

        response = self.view_history(self.user)
        self.assert_history_table_equals(
            response,
            [
                ['Point 1: A',
                 f'{self.user.username}'],
                ['Point 1: A<br/>Point 2: B<br/>Point 3: B',
                 f'Robot {robot.pk}'],
            ]
        )

    def test_change_an_unconfirmed_annotation(self):
        robot = self.create_robot(self.source)
        self.add_robot_annotations(robot, self.img, {1: 'A', 2: 'B', 3: 'B'})

        # Change 1
        data = dict(
            label_1='B', label_2='B', label_3='B',
            robot_1='false', robot_2='true', robot_3='true',
        )
        self.client.force_login(self.user)
        response = self.client.post(self.url, data).json()
        self.assertTrue('error' not in response)

        annotation_1 = Annotation.objects.get(
            image__pk=self.img.pk, point__point_number=1)
        self.assertEqual(annotation_1.label_code, 'B')
        self.assertEqual(annotation_1.user.username, self.user.username)

        response = self.view_history(self.user)
        self.assert_history_table_equals(
            response,
            [
                ['Point 1: B',
                 f'{self.user.username}'],
                ['Point 1: A<br/>Point 2: B<br/>Point 3: B',
                 f'Robot {robot.pk}'],
            ]
        )

    def test_change_a_confirmed_annotation(self):
        self.add_annotations(self.user, self.img, {1: 'A'})

        # Change 1
        data = dict(
            label_1='B', label_2='', label_3='',
            robot_1='false', robot_2='null', robot_3='null',
        )
        self.client.force_login(self.user)
        response = self.client.post(self.url, data).json()
        self.assertTrue('error' not in response)

        annotation_1 = Annotation.objects.get(
            image__pk=self.img.pk, point__point_number=1)
        self.assertEqual(annotation_1.label_code, 'B')
        self.assertEqual(annotation_1.user.username, self.user.username)

        response = self.view_history(self.user)
        self.assert_history_table_equals(
            response,
            [
                ['Point 1: B',
                 f'{self.user.username}'],
                ['Point 1: A',
                 f'{self.user.username}'],
            ]
        )

    def test_change_a_confirmed_annotation_from_another_user(self):
        # Add 1 as admin
        self.add_annotations(self.user, self.img, {1: 'A'})

        # Create other user and add them to the source
        other_user = self.create_user()
        self.add_source_member(
            self.user, self.source, other_user, Source.PermTypes.EDIT.code)

        # Change 1 as other user
        data = dict(
            label_1='B', label_2='', label_3='',
            robot_1='false', robot_2='null', robot_3='null',
        )
        self.client.force_login(other_user)
        response = self.client.post(self.url, data).json()
        self.assertTrue('error' not in response)

        annotation_1 = Annotation.objects.get(
            image__pk=self.img.pk, point__point_number=1)
        self.assertEqual(annotation_1.label_code, 'B')
        self.assertEqual(annotation_1.user.username, other_user.username)

        response = self.view_history(self.user)
        self.assert_history_table_equals(
            response,
            [
                ['Point 1: B',
                 f'{other_user.username}'],
                ['Point 1: A',
                 f'{self.user.username}'],
            ]
        )

    def test_robot_value_null_with_non_blank_label_code(self):
        """This happens when a user loads the annotation tool, fills in a
        previously blank label, and submits. This happens because the form and
        JS here are a bit sloppy, but in any case, we handle it for now by
        treating null as false."""
        data = dict(
            label_1='A', label_2='B', label_3='B',
            robot_1='false', robot_2='null', robot_3='false',
        )
        self.client.force_login(self.user)
        response = self.client.post(self.url, data).json()
        self.assertTrue('error' not in response)

        annotation_2 = Annotation.objects.get(
            image__pk=self.img.pk, point__point_number=2)
        self.assertEqual(annotation_2.label_code, 'B')
        self.assertEqual(annotation_2.user.username, self.user.username)

    def test_mixed_changes(self):
        """Multiple of the above cases, submitted on different points."""
        robot = self.create_robot(self.source)
        self.add_robot_annotations(robot, self.img, {1: 'A', 2: 'B', 3: 'B'})
        self.add_annotations(self.user, self.img, {3: 'A'})

        # 1: unconfirmed, then confirmed
        # 2: unconfirmed, then changed + confirmed
        # 3: confirmed, then changed
        data = dict(
            label_1='A', label_2='A', label_3='B',
            robot_1='false', robot_2='false', robot_3='false',
        )
        self.client.force_login(self.user)
        response = self.client.post(self.url, data).json()
        self.assertTrue('error' not in response)

        annotation_1 = Annotation.objects.get(
            image__pk=self.img.pk, point__point_number=1)
        self.assertEqual(annotation_1.label_code, 'A')
        self.assertEqual(annotation_1.user.username, self.user.username)
        annotation_2 = Annotation.objects.get(
            image__pk=self.img.pk, point__point_number=2)
        self.assertEqual(annotation_2.label_code, 'A')
        self.assertEqual(annotation_2.user.username, self.user.username)
        annotation_3 = Annotation.objects.get(
            image__pk=self.img.pk, point__point_number=3)
        self.assertEqual(annotation_3.label_code, 'B')
        self.assertEqual(annotation_3.user.username, self.user.username)

    def test_not_all_done(self):
        """Check that 'all done' status is false when it should be."""
        data = dict(
            label_1='A', label_2='B', label_3='B',
            robot_1='false', robot_2='true', robot_3='false',
        )
        self.client.force_login(self.user)
        response = self.client.post(self.url, data).json()

        self.assertTrue('error' not in response)
        self.assertFalse(response['all_done'])

        self.img.annoinfo.refresh_from_db()
        # Image should not be marked as confirmed
        self.assertFalse(self.img.annoinfo.confirmed)

    def test_all_done(self):
        """Check that 'all done' status is true when it should be."""
        data = dict(
            label_1='A', label_2='B', label_3='B',
            robot_1='false', robot_2='false', robot_3='false',
        )
        self.client.force_login(self.user)
        response = self.client.post(self.url, data).json()

        self.assertTrue('error' not in response)
        self.assertTrue(response['all_done'])

        self.img.annoinfo.refresh_from_db()
        # Image should be marked as confirmed
        self.assertTrue(self.img.annoinfo.confirmed)

    def test_last_annotation_updated(self):
        """last_annotation field of the Image should get updated."""

        # For some reason this is needed when running the whole test class,
        # but not when running this individual test.
        self.img.annoinfo.refresh_from_db()

        self.assertIsNone(
            self.img.annoinfo.last_annotation,
            msg="Should not have a last annotation yet")

        # Annotate point 3
        data = dict(
            label_1='', label_2='', label_3='B',
            robot_1='null', robot_2='null', robot_3='false',
        )
        self.client.force_login(self.user)
        self.client.post(self.url, data)
        self.img.annoinfo.refresh_from_db()
        self.assertEqual(
            self.img.annoinfo.last_annotation.point.point_number, 3,
            msg="Last annotation should be updated")

        # Annotate point 1
        data = dict(
            label_1='A', label_2='', label_3='B',
            robot_1='false', robot_2='null', robot_3='false',
        )
        self.client.post(self.url, data)
        self.img.annoinfo.refresh_from_db()
        self.assertEqual(
            self.img.annoinfo.last_annotation.point.point_number, 1,
            msg="Last annotation should be updated")

        # Update point 3's annotation
        data = dict(
            label_1='A', label_2='', label_3='A',
            robot_1='false', robot_2='null', robot_3='false',
        )
        self.client.post(self.url, data)
        self.img.annoinfo.refresh_from_db()
        self.assertEqual(
            self.img.annoinfo.last_annotation.point.point_number, 3,
            msg="Last annotation should be updated")

        # Make the 'confirmed' status update
        data = dict(
            label_1='A', label_2='B', label_3='A',
            robot_1='false', robot_2='false', robot_3='false',
        )
        self.client.post(self.url, data)
        self.img.annoinfo.refresh_from_db()
        self.assertEqual(
            self.img.annoinfo.last_annotation.point.point_number, 2,
            msg="Last annotation should be updated")

    def test_label_code_missing(self):
        """This isn't supposed to happen unless we screwed up or the user
        crafted POST data.
        Note: for these error cases, we make the error case involve a point
        other than the first point (the second point in this case), so that
        we can test whether the first point got saved or not. (Saving and
        checking happens in point order.)"""
        data = dict(
            label_1='A', label_3='B',
            robot_1='false', robot_2='false', robot_3='false',
        )
        self.client.force_login(self.user)
        response = self.client.post(self.url, data).json()

        self.assertTrue('error' in response)
        self.assertEqual(response['error'], "Missing label field for point 2.")
        self.assert_didnt_save_anything()

    def test_label_code_invalid(self):
        """This isn't supposed to happen unless we screwed up, the user
        crafted POST data, or a local label was just deleted/changed."""
        data = dict(
            label_1='A', label_2='C', label_3='B',
            robot_1='false', robot_2='false', robot_3='false',
        )
        self.client.force_login(self.user)
        response = self.client.post(self.url, data).json()

        self.assertTrue('error' in response)
        self.assertEqual(
            response['error'], "The labelset has no label with code C.")
        self.assert_didnt_save_anything()

    def test_robot_value_missing(self):
        """This isn't supposed to happen unless we screwed up or the user
        crafted POST data."""
        data = dict(
            label_1='A', label_2='B', label_3='B',
            robot_1='false', robot_2='false',
        )
        self.client.force_login(self.user)
        response = self.client.post(self.url, data).json()

        self.assertTrue('error' in response)
        self.assertEqual(response['error'], "Missing robot field for point 3.")
        self.assert_didnt_save_anything()

    def test_robot_value_invalid(self):
        """This isn't supposed to happen unless we screwed up or the user
        crafted POST data."""
        data = dict(
            label_1='A', label_2='C', label_3='B',
            robot_1='false', robot_2='asdf', robot_3='false',
        )
        self.client.force_login(self.user)
        response = self.client.post(self.url, data).json()

        self.assertTrue('error' in response)
        self.assertEqual(response['error'], "Invalid robot field value: asdf")
        self.assert_didnt_save_anything()

    def test_integrity_error_when_saving(self):

        class UnexpectedPointOrderError(Exception):
            pass

        def mock_update_annotation(
            point, label, now_confirmed, user_or_robot_version
        ):
            """
            When the save_annotations_ajax view tries to actually save the
            annotations to the DB, this patched function should save the
            annotation for point 1, then raise an IntegrityError for point 2.
            This should make the view return an appropriate
            error message, and should make point 1 get rolled back.
            """
            # This is a simple saving case (for brevity) which works for this
            # particular test.
            new_annotation = Annotation(
                point=point, image=point.image,
                source=point.image.source, label=label,
                user=user_or_robot_version)
            new_annotation.save()

            if point.point_number == 1:
                cache.set('point_1_processed', True)
            if point.point_number == 2:
                if not cache.get('point_1_processed'):
                    # The point order, which the test depends on, isn't as
                    # expected. Raise a non-IntegrityError to fail the test.
                    raise UnexpectedPointOrderError
                # Save another Annotation for this Point, simulating a race
                # condition of some kind. Should get an IntegrityError.
                new_annotation.pk = None
                new_annotation.save()

        data = dict(
            label_1='A', label_2='B', label_3='B',
            robot_1='false', robot_2='false', robot_3='false',
        )
        # Due to the mocked method, this should get an IntegrityError when
        # trying to save point 2.
        self.client.force_login(self.user)

        with mock.patch(
            'annotations.models.Annotation.objects'
            '.update_point_annotation_if_applicable',
            mock_update_annotation
        ):
            response = self.client.post(self.url, data).json()

        self.assertTrue('error' in response)
        self.assertEqual(
            response['error'],
            "Failed to save annotations. It's possible that the"
            " annotations changed at the same time that you submitted."
            " Try again and see if it works.")

        # Although the error occurred on point 2, nothing should have been
        # saved, including point 1.
        self.assert_didnt_save_anything()


class AlleviateTest(ClientTest, AnnotationHistoryTestMixin):
    """Test the Alleviate feature, where confident-enough machine annotations
    get auto-confirmed when entering the annotation tool."""
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user,
            default_point_generation_method=dict(type='simple', points=2),
            confidence_threshold=80,
        )
        labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, labels)

        cls.img = cls.upload_image(cls.user, cls.source)
        cls.tool_url = resolve_url('annotation_tool', cls.img.pk)
        cls.all_done_url = resolve_url(
            'is_annotation_all_done_ajax', cls.img.pk)

    def test_point_confidence_too_low(self):
        robot = self.create_robot(self.source)
        self.add_robot_annotations(
            robot, self.img, {1: ('A', 51), 2: ('B', 79)})

        # Trigger Alleviate
        self.client.force_login(self.user)
        self.client.get(self.tool_url)

        # Still robot annotations
        annotation_1 = Annotation.objects.get(
            image__pk=self.img.pk, point__point_number=1)
        self.assertTrue(is_robot_user(annotation_1.user))
        annotation_2 = Annotation.objects.get(
            image__pk=self.img.pk, point__point_number=2)
        self.assertTrue(is_robot_user(annotation_2.user))

    def test_point_confidence_high_enough(self):
        robot = self.create_robot(self.source)
        self.add_robot_annotations(
            robot, self.img, {1: ('A', 81), 2: ('B', 99)})

        # Trigger Alleviate
        self.client.force_login(self.user)
        self.client.get(self.tool_url)

        # Now Alleviate annotations
        annotation_1 = Annotation.objects.get(
            image__pk=self.img.pk, point__point_number=1)
        self.assertTrue(is_alleviate_user(annotation_1.user))
        annotation_2 = Annotation.objects.get(
            image__pk=self.img.pk, point__point_number=2)
        self.assertTrue(is_alleviate_user(annotation_2.user))

    def test_dont_change_confirmed(self):
        robot = self.create_robot(self.source)
        self.add_robot_annotations(
            robot, self.img, {1: ('A', 81), 2: ('B', 99)})
        self.add_annotations(self.user, self.img, {2: 'A'})

        # Trigger Alleviate
        self.client.force_login(self.user)
        self.client.get(self.tool_url)

        # Annotation 2 should still belong to self.user
        annotation_2 = Annotation.objects.get(
            image__pk=self.img.pk, point__point_number=2)
        self.assertEqual(annotation_2.label_code, 'A')
        self.assertEqual(annotation_2.user.username, self.user.username)

    def test_not_all_done(self):
        robot = self.create_robot(self.source)
        self.add_robot_annotations(
            robot, self.img, {1: ('A', 79), 2: ('B', 81)})

        # Trigger Alleviate
        self.client.force_login(self.user)
        self.client.get(self.tool_url)

        # Not all points are confirmed
        self.img.annoinfo.refresh_from_db()
        self.assertFalse(self.img.annoinfo.confirmed)
        all_done_response = self.client.get(self.all_done_url).json()
        self.assertFalse(all_done_response['all_done'])

    def test_all_done(self):
        robot = self.create_robot(self.source)
        self.add_robot_annotations(
            robot, self.img, {1: ('A', 95), 2: ('B', 81)})

        # Trigger Alleviate
        self.client.force_login(self.user)
        self.client.get(self.tool_url)

        # All points are confirmed
        self.img.annoinfo.refresh_from_db()
        self.assertTrue(self.img.annoinfo.confirmed)
        all_done_response = self.client.get(self.all_done_url).json()
        self.assertTrue(all_done_response['all_done'])

    def test_last_annotation_updated(self):
        """
        last_annotation field of the Image should get updated, AND should be
        correctly reflected on the annotation tool page.
        """
        robot = self.create_robot(self.source)
        self.add_robot_annotations(
            robot, self.img, {1: ('A', 81), 2: ('B', 79)})

        # Trigger Alleviate on point 1
        self.client.force_login(self.user)
        response = self.client.get(self.tool_url)

        self.img.annoinfo.refresh_from_db()
        self.assertEqual(
            self.img.annoinfo.last_annotation.point.point_number, 1,
            msg="Last annotation should be on point 1")

        self.assertContains(
            response, "Last annotation update: Alleviate",
            msg_prefix=(
                "Last annotation should show on the"
                " annotation tool"))

        # Trigger Alleviate on point 2
        self.source.confidence_threshold = 75
        self.source.save()
        self.client.force_login(self.user)
        self.client.get(self.tool_url)

        self.img.annoinfo.refresh_from_db()
        self.assertEqual(
            self.img.annoinfo.last_annotation.point.point_number, 2,
            msg="Last annotation should be on point 2")

    def test_history(self):
        """
        Alleviate application should create an annotation history entry.
        """
        robot = self.create_robot(self.source)
        self.add_robot_annotations(
            robot, self.img,
            {1: ('A', 81), 2: ('B', 79)})

        # Access the annotation tool to trigger Alleviate
        self.client.force_login(self.user)
        self.client.get(reverse('annotation_tool', args=[self.img.pk]))

        response = self.view_history(self.user)
        self.assert_history_table_equals(
            response,
            [
                # 3rd: Access event
                ['Accessed annotation tool',
                 f'{self.user.username}'],
                # 2nd: Alleviate should have triggered for point 1
                ['Point 1: A',
                 'Alleviate'],
                # 1st: Robot annotation
                ['Point 1: A<br/>Point 2: B',
                 f'Robot {robot.pk}'],
            ]
        )

    def test_post_request(self):
        """
        Alleviate takes a different code path if the annotation tool request
        is POST instead of GET. This happens when the annotation tool is
        entered through a Browse search.
        """
        robot = self.create_robot(self.source)
        self.add_robot_annotations(
            robot, self.img,
            {1: ('A', 81), 2: ('B', 79)})

        # Access the annotation tool through a Browse search
        self.client.force_login(self.user)
        data = BROWSE_IMAGES_DEFAULT_SEARCH_PARAMS.copy()
        self.client.post(
            reverse('annotation_tool', args=[self.img.pk]), data)

        # Alleviate should have run
        annotation_1 = Annotation.objects.get(
            image__pk=self.img.pk, point__point_number=1)
        self.assertFalse(
            is_robot_user(annotation_1.user),
            "1 should no longer be a robot annotation")

        # History entry should be there
        response = self.view_history(self.user, img=self.img)
        self.assert_history_table_equals(
            response,
            [
                # 3rd: Access event
                ['Accessed annotation tool',
                 f'{self.user.username}'],
                # 2nd: Alleviate should have triggered for point 1
                ['Point 1: A',
                 'Alleviate'],
                # 1st: Robot annotation
                ['Point 1: A<br/>Point 2: B',
                 f'Robot {robot.pk}'],
            ]
        )

    def test_transaction_rollback(self):
        """
        If an error occurs after Alleviate is applied and before the annotation
        tool view completes, changes should be rolled back.
        """
        robot = self.create_robot(self.source)
        self.add_robot_annotations(
            robot, self.img, {1: ('A', 95), 2: ('B', 95)})

        def raise_error(self, *args, **kwargs):
            raise IntegrityError

        # Trigger Alleviate, with one of the view's calls mocked to raise an
        # error after Alleviate happens
        self.client.force_login(self.user)
        with mock.patch.object(AnnotationToolAccess, 'save', raise_error):
            with self.assertRaises(IntegrityError):
                self.client.get(self.tool_url)

        self.img.annoinfo.refresh_from_db()
        self.assertFalse(
            self.img.annoinfo.confirmed, "Image shouldn't be confirmed")
        all_done_response = self.client.get(self.all_done_url).json()
        self.assertFalse(
            all_done_response['all_done'], "Image shouldn't be all done")

        # History should only have the initial robot annotation action
        response = self.view_history(self.user)
        self.assert_history_table_equals(
            response,
            [
                # 1st: Robot annotation
                ['Point 1: A<br/>Point 2: B',
                 f'Robot {robot.pk}'],
            ]
        )


class SettingsTest(ClientTest):
    """
    Test annotation tool settings.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()

        cls.source = cls.create_source(cls.user)
        labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, labels)

        cls.img = cls.upload_image(cls.user, cls.source)
        cls.tool_url = reverse('annotation_tool', args=[cls.img.pk])
        cls.settings_url = reverse('annotation_tool_settings_save')

        cls.field_names_to_types = dict(
            point_marker='choice',
            point_marker_size='integer',
            point_marker_is_scaled='boolean',
            point_number_size='integer',
            point_number_is_scaled='boolean',
            unannotated_point_color='color',
            robot_annotated_point_color='color',
            human_annotated_point_color='color',
            selected_point_color='color',
            show_machine_annotations='boolean',
        )

        cls.sample_settings = dict(
            point_marker='box',
            point_marker_size=19,
            point_marker_is_scaled=True,
            point_number_size=9,
            point_number_is_scaled=True,
            unannotated_point_color='FF0000',
            robot_annotated_point_color='ABCDEF',
            human_annotated_point_color='012345',
            selected_point_color='FFBBBB',
            show_machine_annotations=False,
        )

        cls.field_names_to_defaults = dict()
        for field_name in cls.field_names_to_types.keys():
            field_meta = AnnotationToolSettings._meta.get_field(field_name)
            cls.field_names_to_defaults[field_name] = field_meta.default

    def get_field_value_from_soup(self, field_name, form_soup):
        field_type = self.field_names_to_types[field_name]

        if field_type == 'choice':
            field_soup = form_soup.find('select', dict(name=field_name))
            # `selected=True` checks for presence of the `selected` attribute.
            # https://stackoverflow.com/questions/14863495/find-the-selected-option-using-beautifulsoup
            option_soup = field_soup.find('option', dict(selected=True))
            field_value = option_soup.attrs['value']
        elif field_type == 'integer':
            field_soup = form_soup.find('input', dict(name=field_name))
            field_value = int(field_soup.attrs['value'])
        elif field_type == 'color':
            field_soup = form_soup.find('input', dict(name=field_name))
            field_value = field_soup.attrs['value']
        elif field_type == 'boolean':
            field_soup = form_soup.find('input', dict(name=field_name))
            field_value = 'checked' in field_soup.attrs
        else:
            raise ValueError("Not a recognized field type.")

        return field_value

    def test_tool_uses_defaults_if_never_saved_settings(self):
        self.client.force_login(self.user)
        response = self.client.get(self.tool_url)

        # Scrape the annotation tool's HTML to ensure the settings values are
        # as expected.
        response_soup = BeautifulSoup(response.content, 'html.parser')
        form_soup = response_soup.find(
            'form', dict(id='annotationToolSettingsForm'))

        for field_name, field_type in self.field_names_to_types.items():
            field_value = self.get_field_value_from_soup(field_name, form_soup)
            field_meta = AnnotationToolSettings._meta.get_field(field_name)
            expected_value = field_meta.default
            self.assertEqual(
                field_value, expected_value,
                field_name + " has the expected value")

    def test_tool_uses_saved_settings(self):
        self.client.force_login(self.user)

        # Save non-default settings.
        data = self.sample_settings
        self.client.post(self.settings_url, data)

        response = self.client.get(self.tool_url)

        # Scrape the annotation tool's HTML to ensure the settings values are
        # as expected.
        response_soup = BeautifulSoup(response.content, 'html.parser')
        form_soup = response_soup.find(
            'form', dict(id='annotationToolSettingsForm'))

        for field_name, field_type in self.field_names_to_types.items():
            field_value = self.get_field_value_from_soup(field_name, form_soup)
            expected_value = self.sample_settings[field_name]
            self.assertEqual(
                field_value, expected_value,
                field_name + " has the expected value")

    def test_save_settings_for_first_time(self):
        self.client.force_login(self.user)

        # Set settings.
        data = self.sample_settings
        response = self.client.post(self.settings_url, data).json()

        # Check response
        self.assertTrue('error' not in response)

        # Check settings in database
        settings = AnnotationToolSettings.objects.get(user=self.user)
        for field_name, setting in self.sample_settings.items():
            self.assertEqual(getattr(settings, field_name), setting)

    def test_update_existing_settings(self):
        self.client.force_login(self.user)

        # Set settings.
        data = self.sample_settings
        self.client.post(self.settings_url, data).json()
        # Update settings.
        data = self.sample_settings.copy()
        data.update(point_marker='crosshair and circle')
        response = self.client.post(self.settings_url, data).json()

        # Check response
        self.assertTrue('error' not in response)

        # Check settings in database
        settings = AnnotationToolSettings.objects.get(user=self.user)
        for field_name, sample_setting in self.sample_settings.items():
            if field_name == 'point_marker':
                self.assertEqual(
                    getattr(settings, field_name), 'crosshair and circle')
            else:
                self.assertEqual(getattr(settings, field_name), sample_setting)

    def test_missing_setting(self):
        self.client.force_login(self.user)

        data = self.sample_settings.copy()
        data.pop('point_marker')
        response = self.client.post(self.settings_url, data).json()

        self.assertTrue('error' in response)
        self.assertTrue(
            "Point marker: This field is required."
            in response['error'],
            msg=response['error'])

    def test_point_marker_not_recognized(self):
        self.client.force_login(self.user)

        data = self.sample_settings.copy()
        data['point_marker'] = 'Crosshair and box'
        response = self.client.post(self.settings_url, data).json()

        self.assertTrue('error' in response)
        self.assertTrue(
            "Point marker: Select a valid choice. Crosshair and box is not"
            " one of the available choices."
            in response['error'],
            msg=response['error'])

    def test_point_marker_size_not_an_integer(self):
        self.client.force_login(self.user)

        data = self.sample_settings.copy()
        data['point_marker_size'] = '15.5'
        response = self.client.post(self.settings_url, data).json()

        self.assertTrue('error' in response)
        self.assertTrue(
            "Point marker size: Enter a whole number."
            in response['error'],
            msg=response['error'])

    def test_point_marker_size_too_small(self):
        self.client.force_login(self.user)

        data = self.sample_settings.copy()
        data['point_marker_size'] = 0
        response = self.client.post(self.settings_url, data).json()

        self.assertTrue('error' in response)
        self.assertTrue(
            "Point marker size: Ensure this value is greater than or equal"
            " to 1."
            in response['error'],
            msg=response['error'])

    def test_point_marker_size_too_large(self):
        self.client.force_login(self.user)

        data = self.sample_settings.copy()
        data['point_marker_size'] = 31
        response = self.client.post(self.settings_url, data).json()

        self.assertTrue('error' in response)
        self.assertTrue(
            "Point marker size: Ensure this value is less than or equal to 30."
            in response['error'],
            msg=response['error'])

    def test_point_number_size_not_an_integer(self):
        self.client.force_login(self.user)

        data = self.sample_settings.copy()
        data['point_number_size'] = '0a'
        response = self.client.post(self.settings_url, data).json()

        self.assertTrue('error' in response)
        self.assertTrue(
            "Point number size: Enter a whole number."
            in response['error'],
            msg=response['error'])

    def test_point_number_size_too_small(self):
        self.client.force_login(self.user)

        data = self.sample_settings.copy()
        data['point_number_size'] = 0
        response = self.client.post(self.settings_url, data).json()

        self.assertTrue('error' in response)
        self.assertTrue(
            "Point number size: Ensure this value is greater than or equal"
            " to 1."
            in response['error'],
            msg=response['error'])

    def test_point_number_size_too_large(self):
        self.client.force_login(self.user)

        data = self.sample_settings.copy()
        data['point_number_size'] = 41
        response = self.client.post(self.settings_url, data).json()

        self.assertTrue('error' in response)
        self.assertTrue(
            "Point number size: Ensure this value is less than or equal to 40."
            in response['error'],
            msg=response['error'])

    # TODO: Implement color validation (6 digit uppercase hex string)
    # and test it here.
