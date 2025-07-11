# Test image_detail and image_detail_edit views.

import datetime

from bs4 import BeautifulSoup
from django.urls import reverse

from annotations.model_utils import AnnotationArea
from lib.tests.utils import BasePermissionTest, ClientTest
from ..model_utils import PointGen


class PermissionTest(BasePermissionTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.img = cls.upload_image(cls.user, cls.source)

    def test_image_detail(self):
        url = reverse('image_detail', args=[self.img.id])
        template = 'images/image_detail.html'

        self.source_to_private()
        self.assertPermissionLevel(url, self.SOURCE_VIEW, template=template)
        self.source_to_public()
        self.assertPermissionLevel(url, self.SIGNED_OUT, template=template)

    def test_image_detail_edit(self):
        url = reverse('image_detail_edit', args=[self.img.id])
        template = 'images/image_detail_edit.html'

        self.source_to_private()
        self.assertPermissionLevel(url, self.SOURCE_EDIT, template=template)
        self.source_to_public()
        self.assertPermissionLevel(url, self.SOURCE_EDIT, template=template)


class ImageDetailTest(ClientTest):
    """
    Test the image view/detail page.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user,
            default_point_generation_method=dict(type='simple', points=2))
        cls.labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, cls.labels)

    def test_page_with_small_image(self):
        small_image = self.upload_image(
            self.user, self.source, image_options=dict(width=400, height=400))
        url = reverse('image_detail', args=[small_image.pk])
        response = self.client.get(url)
        self.assertStatusOK(response)

        # Try fetching the page a second time, to make sure thumbnail
        # generation doesn't go nuts.
        response = self.client.get(url)
        self.assertStatusOK(response)

    def test_page_with_large_image(self):
        large_image = self.upload_image(
            self.user, self.source,
            image_options=dict(width=1600, height=1600))
        url = reverse('image_detail', args=[large_image.pk])
        response = self.client.get(url)
        self.assertStatusOK(response)

        # Try fetching the page a second time, to make sure thumbnail
        # generation doesn't go nuts.
        response = self.client.get(url)
        self.assertStatusOK(response)

    def test_prev_next_links(self):
        img1 = self.upload_image(
            self.user, self.source, image_options=dict(filename='1.png'))
        img2 = self.upload_image(
            self.user, self.source, image_options=dict(filename='2.png'))
        img3 = self.upload_image(
            self.user, self.source, image_options=dict(filename='3.png'))

        self.client.force_login(self.user)

        # Prev/next follows alphabetical order by name. So order is 1 > 2 > 3.

        response = self.client.get(reverse('image_detail', args=[img1.pk]))
        self.assertInHTML(
            '| <a href="{}" title="2.png"> Next &gt;</a>'.format(
                reverse('image_detail', args=[img2.pk])),
            response.content.decode())

        response = self.client.get(reverse('image_detail', args=[img2.pk]))
        self.assertInHTML(
            '<a href="{}" title="1.png"> &lt; Previous</a>'
            ' | <a href="{}" title="3.png"> Next &gt;</a>'.format(
                reverse('image_detail', args=[img1.pk]),
                reverse('image_detail', args=[img3.pk])),
            response.content.decode())

        response = self.client.get(reverse('image_detail', args=[img3.pk]))
        self.assertInHTML(
            '<a href="{}" title="2.png"> &lt; Previous</a>'.format(
                reverse('image_detail', args=[img2.pk])),
            response.content.decode())

    def test_point_gen_method_text(self):
        image = self.upload_image(self.user, self.source)

        def assert_pointgen_text(new_method, expected_text):
            image.point_generation_method = PointGen(**new_method).db_value
            image.save()

            response = self.client.get(reverse('image_detail', args=[image.pk]))
            self.assertInHTML(
                f"Point generation method: {expected_text}",
                response.content.decode())

        self.client.force_login(self.user)
        assert_pointgen_text(
            dict(type='simple', points=5),
            "Simple random, 5 points",
        )
        assert_pointgen_text(
            dict(type='stratified', cell_rows=3, cell_columns=4, per_cell=5),
            "Stratified random, 3 rows x 4 columns of cells,"
            " 5 points per cell (total of 60 points)",
        )
        assert_pointgen_text(
            dict(type='uniform', cell_rows=8, cell_columns=12),
            "Uniform grid, 8 rows x 12 columns"
            " (total of 96 points)",
        )
        assert_pointgen_text(
            dict(type='imported', points=10),
            "Imported, 10 points",
        )

    def test_annotation_area_text(self):
        image = self.upload_image(
            self.user, self.source,
            image_options=dict(width=200, height=200))

        def assert_area_text(new_area, expected_text):
            image.metadata.annotation_area = AnnotationArea(
                **new_area).db_value
            image.metadata.save()

            response = self.client.get(reverse('image_detail', args=[image.pk]))
            self.assertIn(
                f"Annotation area: {expected_text}",
                response.content.decode())

        self.client.force_login(self.user)
        assert_area_text(
            dict(
                type=AnnotationArea.TYPE_PERCENTAGES,
                min_x=0, max_x=100, min_y='15.47', max_y='84.53'),
            "X: 0 - 100% / Y: 15.47 - 84.53%",
        )
        assert_area_text(
            dict(
                type=AnnotationArea.TYPE_PIXELS,
                min_x=21, max_x=179, min_y=0, max_y=199),
            "X: 21 - 179 pixels / Y: 0 - 199 pixels",
        )
        assert_area_text(
            dict(type=AnnotationArea.TYPE_IMPORTED),
            "(Imported points; not specified)",
        )

    def test_annotation_status_text(self):
        """Test all the possible annotation-status displays on this page."""
        image = self.upload_image(self.user, self.source)

        def assert_status_text(expected_text):
            response = self.client.get(reverse('image_detail', args=[image.pk]))
            self.assertInHTML(
                f"Annotation status: <b>{expected_text}</b>",
                response.content.decode())

        self.client.force_login(self.user)
        assert_status_text("Not started")

        robot = self.create_robot(self.source)
        self.add_robot_annotations(robot, image)
        assert_status_text("Unconfirmed")

        self.add_annotations(self.user, image, {1: 'A'})
        assert_status_text("Partially confirmed")

        self.add_annotations(self.user, image, {2: 'B'})
        assert_status_text("Confirmed (completed)")


class ImageDetailEditTest(ClientTest):
    """
    Test the image view/detail page.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user,
            key1="Aux1", key2="Aux2", key3="Aux3", key4="Aux4", key5="Aux5",
        )
        cls.img = cls.upload_image(
            cls.user, cls.source, image_options=dict(filename='1.png'))
        cls.url = reverse('image_detail_edit', kwargs={'image_id': cls.img.id})

    def submit_edits(self, post_data: dict):
        self.client.force_login(self.user)
        return self.client.post(
            self.url,
            data=post_data,
            follow=True,
        )

    def test_load_page(self):
        # Set metadata
        self.img.metadata.photo_date = datetime.date(2020, 4, 3)
        self.img.metadata.aux1 = 'Site A'
        self.img.metadata.aux2 = 'Fringing Reef'
        self.img.metadata.aux3 = '2-4'
        self.img.metadata.aux4 = 'qu5'
        self.img.metadata.name = '13.png'
        self.img.metadata.height_in_cm = 50
        self.img.metadata.latitude = '12.3456'
        self.img.metadata.longitude = '65.4321'
        self.img.metadata.depth = '3m'
        self.img.metadata.camera = 'Nikon'
        self.img.metadata.photographer = 'John Doe'
        self.img.metadata.water_quality = 'Clear'
        self.img.metadata.strobes = 'White A'
        self.img.metadata.framing = 'Framing set C'
        self.img.metadata.balance = 'Card B'
        self.img.metadata.comments = "Here are\nsome comments."
        self.img.metadata.save()

        self.client.force_login(self.user)
        response = self.client.get(self.url)
        response_soup = BeautifulSoup(response.content, 'html.parser')

        # Check that the form loads the current values

        def check_input_value(field_name, expected_value):
            field_ = response_soup.find('input', attrs=dict(name=field_name))
            self.assertEqual(field_.attrs.get('value'), expected_value)

        check_input_value('photo_date', '2020-04-03')
        check_input_value('aux1', 'Site A')
        check_input_value('aux2', 'Fringing Reef')
        check_input_value('aux3', '2-4')
        check_input_value('aux4', 'qu5')
        check_input_value('aux5', None)
        check_input_value('name', '13.png')
        check_input_value('height_in_cm', '50')
        check_input_value('latitude', '12.3456')
        check_input_value('longitude', '65.4321')
        check_input_value('depth', '3m')
        check_input_value('camera', 'Nikon')
        check_input_value('photographer', 'John Doe')
        check_input_value('water_quality', 'Clear')
        check_input_value('strobes', 'White A')
        check_input_value('framing', 'Framing set C')
        check_input_value('balance', 'Card B')

        field = response_soup.find('textarea', attrs=dict(name='comments'))
        self.assertEqual(field.text.strip(), "Here are\nsome comments.")

    def test_submit_edits(self):
        response = self.submit_edits(dict(
            photo_date=datetime.date(2020, 4, 3),
            aux1='Site A',
            aux2='Fringing Reef',
            aux3='2-4',
            aux4='qu5',
            name='13.png',
            height_in_cm=50,
            latitude='12.3456',
            longitude='65.4321',
            depth='3m',
            camera='Nikon',
            photographer='John Doe',
            water_quality='Clear',
            strobes='White A',
            framing='Framing set C',
            balance='Card B',
            comments="Here are\nsome comments.",
        ))
        self.assertContains(response, "Image successfully edited.")

        # Check that the values have been updated in the DB
        self.img.metadata.refresh_from_db()
        self.assertEqual(
            self.img.metadata.photo_date, datetime.date(2020, 4, 3))
        self.assertEqual(self.img.metadata.aux1, 'Site A')
        self.assertEqual(self.img.metadata.aux2, 'Fringing Reef')
        self.assertEqual(self.img.metadata.aux3, '2-4')
        self.assertEqual(self.img.metadata.aux4, 'qu5')
        self.assertEqual(self.img.metadata.name, '13.png')
        self.assertEqual(self.img.metadata.height_in_cm, 50)
        self.assertEqual(self.img.metadata.latitude, '12.3456')
        self.assertEqual(self.img.metadata.longitude, '65.4321')
        self.assertEqual(self.img.metadata.depth, '3m')
        self.assertEqual(self.img.metadata.camera, 'Nikon')
        self.assertEqual(self.img.metadata.photographer, 'John Doe')
        self.assertEqual(self.img.metadata.water_quality, 'Clear')
        self.assertEqual(self.img.metadata.strobes, 'White A')
        self.assertEqual(self.img.metadata.framing, 'Framing set C')
        self.assertEqual(self.img.metadata.balance, 'Card B')
        self.assertEqual(
            self.img.metadata.comments, "Here are\nsome comments.")

    def test_invalid_date(self):
        self.img.metadata.refresh_from_db()
        old_name = self.img.metadata.name

        response = self.submit_edits(dict(
            photo_date='03/2020',
            name=old_name+'__a_suffix',
        ))
        self.assertNotContains(response, "Image successfully edited.")
        self.assertContains(response, "Enter a valid date.")

        # Check that no values have been updated in the DB
        self.img.metadata.refresh_from_db()
        self.assertEqual(self.img.metadata.name, old_name)

    def test_dupe_name(self):
        img_2 = self.upload_image(self.user, self.source)
        img_2.metadata.name = '2.png'
        img_2.metadata.save()

        # Try to edit self.img to have the same name (case insensitive)
        # as img_2.
        response = self.submit_edits(dict(name='2.PNG'))
        self.assertNotContains(response, "Image successfully edited.")
        self.assertContains(
            response, "This name already exists in the source.")

    def test_same_name(self):
        """
        Submitting with the same name should not fail some kind of
        duplicate check against itself.
        """
        response = self.submit_edits(dict(name='1.png', aux1='Site S'))
        self.assertContains(response, "Image successfully edited.")
        self.img.metadata.refresh_from_db()
        self.assertEqual(self.img.metadata.name, '1.png')
        # This other field's value proves that the edit went through.
        self.assertEqual(self.img.metadata.aux1, 'Site S')

    def test_same_name_in_other_source_ok(self):
        source_2 = self.create_source(self.user)
        source_2_img = self.upload_image(
            self.user, source_2, image_options=dict(filename='3.png'))
        self.assertEqual(
            source_2_img.metadata.name, '3.png',
            msg="Sanity check: source_2 upload should succeed")

        response = self.submit_edits(dict(name='3.png'))
        self.assertContains(response, "Image successfully edited.")
        self.img.metadata.refresh_from_db()
        self.assertEqual(self.img.metadata.name, '3.png')
