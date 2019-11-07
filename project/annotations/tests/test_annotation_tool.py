from __future__ import unicode_literals
import six

from bs4 import BeautifulSoup
from django.db import IntegrityError
from django.shortcuts import resolve_url
from django.urls import reverse
from mock import patch

from accounts.utils import is_alleviate_user, is_robot_user
from annotations.models import Annotation, AnnotationToolSettings
from images.model_utils import PointGen
from images.models import Source
from lib.tests.utils import ClientTest


class PermissionTest(ClientTest):
    """
    Test page and Ajax-submit permissions.
    """
    @classmethod
    def setUpTestData(cls):
        super(PermissionTest, cls).setUpTestData()

        cls.user = cls.create_user()

        cls.source = cls.create_source(cls.user)
        labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, labels)

        cls.user_viewer = cls.create_user()
        cls.add_source_member(
            cls.user, cls.source, cls.user_viewer, Source.PermTypes.VIEW.code)
        cls.user_editor = cls.create_user()
        cls.add_source_member(
            cls.user, cls.source, cls.user_editor, Source.PermTypes.EDIT.code)

        cls.img = cls.upload_image(cls.user, cls.source)

    def test_load_page_anonymous(self):
        """
        Don't have permission.
        """
        url = reverse('annotation_tool', args=[self.img.pk])
        response = self.client.get(url)
        self.assertStatusOK(response)
        self.assertTemplateUsed(response, self.PERMISSION_DENIED_TEMPLATE)

    def test_load_page_as_source_viewer(self):
        """
        Don't have permission.
        """
        url = reverse('annotation_tool', args=[self.img.pk])
        self.client.force_login(self.user_viewer)
        response = self.client.get(url)
        self.assertStatusOK(response)
        self.assertTemplateUsed(response, self.PERMISSION_DENIED_TEMPLATE)

    def test_load_page_as_source_editor(self):
        """
        Can load.
        """
        url = reverse('annotation_tool', args=[self.img.pk])
        self.client.force_login(self.user_editor)
        response = self.client.get(url)
        self.assertStatusOK(response)
        self.assertTemplateUsed(response, 'annotations/annotation_tool.html')

    def test_save_annotations_anonymous(self):
        """
        Don't have permission.
        """
        url = reverse('save_annotations_ajax', args=[self.img.pk])
        response = self.client.post(url, dict()).json()
        # Response should include an error that contains the word "permission"
        self.assertTrue(
            'error' in response and "permission" in response['error'])

    def test_save_annotations_as_source_viewer(self):
        """
        Don't have permission.
        """
        url = reverse('save_annotations_ajax', args=[self.img.pk])
        self.client.force_login(self.user_viewer)
        response = self.client.post(url, dict()).json()
        # Response should include an error that contains the word "permission"
        self.assertTrue(
            'error' in response and "permission" in response['error'])

    def test_save_annotations_as_source_editor(self):
        """
        Can submit.
        """
        url = reverse('save_annotations_ajax', args=[self.img.pk])
        self.client.force_login(self.user_editor)
        response = self.client.post(url, dict()).json()
        # Response may include an error, but if it does, it shouldn't contain
        # the word "permission"
        self.assertFalse(
            'error' in response and "permission" in response['error'])

    def test_check_annotation_done_anonymous(self):
        """
        Don't have permission.
        """
        url = reverse('is_annotation_all_done_ajax', args=[self.img.pk])
        response = self.client.post(url, dict()).json()
        # Response should include an error that contains the word "permission"
        self.assertTrue(
            'error' in response and "permission" in response['error'])

    def test_check_annotation_done_as_source_viewer(self):
        """
        Can check.
        """
        url = reverse('is_annotation_all_done_ajax', args=[self.img.pk])
        self.client.force_login(self.user_viewer)
        response = self.client.post(url, dict()).json()
        # Response should include an error that contains the word "permission"
        self.assertFalse(
            'error' in response and "permission" in response['error'])

    def test_save_annotation_tool_settings_anonymous(self):
        """
        Must be logged in.
        """
        url = reverse('annotation_tool_settings_save')
        response = self.client.post(url, dict()).json()
        # Response should include an error that contains the words "signed in"
        self.assertTrue(
            'error' in response and "signed in" in response['error'])


class LoadImageTest(ClientTest):
    @classmethod
    def setUpTestData(cls):
        super(LoadImageTest, cls).setUpTestData()

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
        super(NavigationTest, cls).setUpTestData()

        cls.user = cls.create_user()

        cls.source = cls.create_source(cls.user)
        labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, labels)

        cls.img1 = cls.upload_image(
            cls.user, cls.source, dict(filename='1.png'))
        cls.img2 = cls.upload_image(
            cls.user, cls.source, dict(filename='2.png'))
        cls.img3 = cls.upload_image(
            cls.user, cls.source, dict(filename='3.png'))

        cls.default_search_params = dict(
            image_form_type='search',
            aux1='', aux2='', aux3='', aux4='', aux5='',
            height_in_cm='', latitude='', longitude='', depth='',
            photographer='', framing='', balance='',
            date_filter_0='year', date_filter_1='',
            date_filter_2='', date_filter_3='',
            annotation_status='',
        )

    def test_next(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('annotation_tool', args=[self.img2.pk]))
        self.assertEqual(response.context['next_image'].pk, self.img3.pk)

    def test_prev(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('annotation_tool', args=[self.img2.pk]))
        self.assertEqual(response.context['prev_image'].pk, self.img1.pk)

    def test_next_wrap_to_first(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('annotation_tool', args=[self.img3.pk]))
        self.assertEqual(response.context['next_image'].pk, self.img1.pk)

    def test_prev_wrap_to_last(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('annotation_tool', args=[self.img1.pk]))
        self.assertEqual(response.context['prev_image'].pk, self.img3.pk)

    def test_next_with_search_filter(self):
        self.img1.metadata.aux1 = 'SiteA'
        self.img1.metadata.save()
        self.img2.metadata.aux1 = 'SiteB'
        self.img2.metadata.save()
        self.img3.metadata.aux1 = 'SiteA'
        self.img3.metadata.save()

        # Exclude img2 with the filter
        post_data = self.default_search_params.copy()
        post_data['aux1'] = 'SiteA'

        self.client.force_login(self.user)
        response = self.client.post(
            reverse('annotation_tool', args=[self.img1.pk]), post_data)
        self.assertEqual(response.context['next_image'].pk, self.img3.pk)

    def test_prev_with_image_id_filter(self):
        # Exclude img2 with the filter
        post_data = self.default_search_params.copy()
        post_data['image_form_type'] = 'ids'
        post_data['ids'] = ','.join([str(self.img1.pk), str(self.img3.pk)])

        self.client.force_login(self.user)
        response = self.client.post(
            reverse('annotation_tool', args=[self.img3.pk]), post_data)
        self.assertEqual(response.context['prev_image'].pk, self.img1.pk)


class LoadAnnotationFormTest(ClientTest):
    """
    Test that the annotation form (with one label-code field per point)
    loads the existing annotations correctly.
    """
    @classmethod
    def setUpTestData(cls):
        super(LoadAnnotationFormTest, cls).setUpTestData()

        cls.user = cls.create_user()

        cls.source = cls.create_source(
            cls.user, visibility=Source.VisibilityTypes.PUBLIC,
            point_generation_type=PointGen.Types.SIMPLE,
            simple_number_of_points=3,
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
        super(IsAnnotationAllDoneTest, cls).setUpTestData()

        cls.user = cls.create_user()

        cls.source = cls.create_source(
            cls.user, visibility=Source.VisibilityTypes.PUBLIC,
            point_generation_type=PointGen.Types.SIMPLE,
            simple_number_of_points=3,
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


def mock_update_annotation(point, label, now_confirmed, user_or_robot_version):
    """
    When the save_annotations_ajax view tries to actually save the
    annotations to the DB, this patched function should raise an
    IntegrityError for point 2, making the view return an appropriate
    error message.

    We'll let other points save normally, so that we can confirm that those
    points' annotations don't get committed if point 2 fails.

    We use a mock.patch approach for this because raising IntegrityError
    legitimately involves replicating a race condition, which is much
    trickier to do reliably.
    """
    if point.point_number == 2:
        raise IntegrityError

    # This is a simple saving case (for brevity) which works for this
    # particular test.
    new_annotation = Annotation(
        point=point, image=point.image,
        source=point.image.source, label=label, user=user_or_robot_version)
    new_annotation.save()


class SaveAnnotationsTest(ClientTest):
    """Test submitting the annotation form which is available at the right side
    of the annotation tool."""
    @classmethod
    def setUpTestData(cls):
        super(SaveAnnotationsTest, cls).setUpTestData()

        cls.user = cls.create_user()

        cls.source = cls.create_source(
            cls.user, visibility=Source.VisibilityTypes.PUBLIC,
            point_generation_type=PointGen.Types.SIMPLE,
            simple_number_of_points=3,
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
        self.assertEqual(
            Annotation.objects.filter(image__pk=self.img.pk).count(), 0)

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

        self.img.refresh_from_db()
        # Image should not be marked as confirmed
        self.assertFalse(self.img.confirmed)

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

        self.img.refresh_from_db()
        # Image should be marked as confirmed
        self.assertTrue(self.img.confirmed)

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

    @patch(
        'annotations.models.Annotation.objects.update_point_annotation_if_applicable',
        mock_update_annotation)
    def test_integrity_error_when_saving(self):
        data = dict(
            label_1='A', label_2='B', label_3='B',
            robot_1='false', robot_2='false', robot_3='false',
        )
        # Due to the mocked method, this should get an IntegrityError when
        # trying to save point 2.
        self.client.force_login(self.user)
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


class AlleviateTest(ClientTest):
    """Test the Alleviate feature, where confident-enough machine annotations
    get auto-confirmed when entering the annotation tool."""
    @classmethod
    def setUpTestData(cls):
        super(AlleviateTest, cls).setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user,
            point_generation_type=PointGen.Types.SIMPLE,
            simple_number_of_points=2,
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
        self.img.refresh_from_db()
        self.assertFalse(self.img.confirmed)
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
        self.img.refresh_from_db()
        self.assertTrue(self.img.confirmed)
        all_done_response = self.client.get(self.all_done_url).json()
        self.assertTrue(all_done_response['all_done'])


class SettingsTest(ClientTest):
    """
    Test annotation tool settings.
    """
    @classmethod
    def setUpTestData(cls):
        super(SettingsTest, cls).setUpTestData()

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
        for field_name in six.iterkeys(cls.field_names_to_types):
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

        for field_name, field_type in six.iteritems(self.field_names_to_types):
            field_value = self.get_field_value_from_soup(field_name, form_soup)
            field_meta = AnnotationToolSettings._meta.get_field(field_name)
            expected_value = field_meta.default
            self.assertEqual(
                field_value, expected_value,
                field_name + " has the expected value")

    def test_tool_uses_saved_settings_when_present(self):
        self.client.force_login(self.user)
        response = self.client.get(self.tool_url)

        # Scrape the annotation tool's HTML to ensure the settings values are
        # as expected.
        response_soup = BeautifulSoup(response.content, 'html.parser')
        form_soup = response_soup.find(
            'form', dict(id='annotationToolSettingsForm'))

        for field_name, field_type in six.iteritems(self.field_names_to_types):
            field_value = self.get_field_value_from_soup(field_name, form_soup)
            field_meta = AnnotationToolSettings._meta.get_field(field_name)
            expected_value = field_meta.default
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
        for field_name, setting in six.iteritems(self.sample_settings):
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
        for field_name, sample_setting in six.iteritems(self.sample_settings):
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
