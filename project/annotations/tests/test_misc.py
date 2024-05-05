import math
from unittest import skip

from bs4 import BeautifulSoup
from django.urls import reverse

from jobs.tests.utils import do_job
from lib.tests.utils import BasePermissionTest, ClientTest
from ..model_utils import AnnotationArea
from ..utils import cacheable_annotation_count


class PermissionTest(BasePermissionTest):
    """
    Test page and Ajax-submit permissions for misc. views.
    """
    def test_annotation_area_edit(self):
        img = self.upload_image(self.user, self.source)
        url = reverse('annotation_area_edit', args=[img.pk])
        template = 'annotations/annotation_area_edit.html'

        self.source_to_private()
        self.assertPermissionLevel(
            url, self.SOURCE_EDIT, template=template)
        self.source_to_public()
        self.assertPermissionLevel(
            url, self.SOURCE_EDIT, template=template)


class SitewideAnnotationCountTest(ClientTest):
    """
    Test the task which computes the site-wide annotation count.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)
        labels = cls.create_labels(cls.user, ['A', 'B'], "Group1")
        cls.create_labelset(cls.user, cls.source, labels)
        cls.img = cls.upload_image(cls.user, cls.source)
        cls.add_annotations(cls.user, cls.img, {1: 'A', 2: 'B', 3: 'A'})

    @staticmethod
    def run_and_get_result():
        job = do_job('update_sitewide_annotation_count')
        return job.result_message

    def test_set_on_demand(self):
        self.assertEqual(cacheable_annotation_count.get(), 3)

    def test_set_in_advance(self):
        self.assertEqual(self.run_and_get_result(), "Updated count to 3")
        self.assertEqual(cacheable_annotation_count.get(), 3)

    def test_set_then_update(self):
        self.assertEqual(self.run_and_get_result(), "Updated count to 3")
        self.assertEqual(cacheable_annotation_count.get(), 3)
        self.add_annotations(self.user, self.img, {4: 'B'})
        self.assertEqual(self.run_and_get_result(), "Updated count to 4")
        self.assertEqual(cacheable_annotation_count.get(), 4)

    def test_caching(self):
        self.run_and_get_result()
        self.assertEqual(cacheable_annotation_count.get(), 3)
        self.add_annotations(self.user, self.img, {4: 'B'})
        self.assertEqual(cacheable_annotation_count.get(), 3)


class AnnotationAreaEditTest(ClientTest):
    """
    Test the annotation area edit page.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        # Passing decimals as strings prevents the decimal places from
        # getting expanded due to floating-point imprecision, which would
        # cause issues with the area field's decimal-place limit.
        cls.source = cls.create_source(
            cls.user, image_annotation_area=dict(
                min_x=19, max_x=62, min_y=7, max_y='90.2'))

        cls.img = cls.upload_image(
            cls.user, cls.source, image_options=dict(width=40, height=50))
        cls.url = reverse('annotation_area_edit', args=[cls.img.pk])

    def test_load_page_with_source_annotation_area(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)

        response_soup = BeautifulSoup(response.content, 'html.parser')
        self.assertEqual(
            '7',
            response_soup.find('input', dict(name='min_x')).attrs.get('value'))
        self.assertEqual(
            '24',
            response_soup.find('input', dict(name='max_x')).attrs.get('value'))
        self.assertEqual(
            '3',
            response_soup.find('input', dict(name='min_y')).attrs.get('value'))
        self.assertEqual(
            '45',
            response_soup.find('input', dict(name='max_y')).attrs.get('value'))

    def test_load_page_with_image_specific_annotation_area(self):
        # Set an image specific annotation area
        self.client.force_login(self.user)
        self.client.post(
            self.url, data=dict(min_x=8, max_x=36, min_y=0, max_y=18))

        # Ensure it's loaded on the next visit
        response = self.client.get(self.url)

        response_soup = BeautifulSoup(response.content, 'html.parser')
        self.assertEqual(
            '8',
            response_soup.find('input', dict(name='min_x')).attrs.get('value'))
        self.assertEqual(
            '36',
            response_soup.find('input', dict(name='max_x')).attrs.get('value'))
        self.assertEqual(
            '0',
            response_soup.find('input', dict(name='min_y')).attrs.get('value'))
        self.assertEqual(
            '18',
            response_soup.find('input', dict(name='max_y')).attrs.get('value'))

    def test_change_annotation_area(self):
        self.client.force_login(self.user)
        area_dict = dict(min_x=8, max_x=36, min_y=0, max_y=18)
        response = self.client.post(
            self.url, data=area_dict,
            follow=True)
        self.assertContains(response, "Annotation area successfully edited.")

        self.img.metadata.refresh_from_db()
        self.assertEqual(
            self.img.metadata.annotation_area,
            AnnotationArea(
                type=AnnotationArea.TYPE_PIXELS, **area_dict).db_value,
            msg="Annotation area should be successfully changed")

    def test_min_or_max_past_limits(self):
        self.client.force_login(self.user)

        response = self.client.post(
            self.url, data=dict(min_x=-1, max_x=39, min_y=0, max_y=49))
        self.assertContains(response, "Please correct the errors below.")
        self.assertContains(
            response, "Ensure this value is greater than or equal to 0.")

        response = self.client.post(
            self.url, data=dict(min_x=0, max_x=40, min_y=0, max_y=49))
        self.assertContains(
            response, "Ensure this value is less than or equal to 39.")

        response = self.client.post(
            self.url, data=dict(min_x=0, max_x=39, min_y=-1, max_y=49))
        self.assertContains(response, "Please correct the errors below.")
        self.assertContains(
            response, "Ensure this value is greater than or equal to 0.")

        response = self.client.post(
            self.url, data=dict(min_x=0, max_x=39, min_y=0, max_y=50))
        self.assertContains(
            response, "Ensure this value is less than or equal to 49.")

        response = self.client.post(
            self.url, data=dict(min_x=0, max_x=39, min_y=0, max_y=49),
            follow=True)
        self.assertContains(
            response, "Annotation area successfully edited.")

    @skip(
        "There's a bug in the behavior here."
        " Need to fix that in the annotation area edit form.")
    def test_min_exceeds_max(self):
        self.client.force_login(self.user)

        response = self.client.post(
            self.url, data=dict(min_x=30, max_x=29, min_y=29, max_y=30))
        self.assertContains(response, "Please correct the errors below.")
        self.assertContains(
            response,
            "The right boundary x must be greater than or equal to"
            " the left boundary x.")

        response = self.client.post(
            self.url, data=dict(min_x=0, max_x=1, min_y=1, max_y=0))
        self.assertContains(
            response,
            "The bottom boundary y must be greater than or equal to"
            " the top boundary y.")

    def test_non_integers(self):
        self.client.force_login(self.user)

        response = self.client.post(
            self.url, data=dict(min_x=8, max_x=36, min_y=0, max_y='a'))
        self.assertContains(response, "Please correct the errors below.")
        self.assertContains(response, "Enter a whole number.")

        response = self.client.post(
            self.url, data=dict(min_x=8.28, max_x=36, min_y=0, max_y=18))
        self.assertContains(response, "Please correct the errors below.")
        self.assertContains(response, "Enter a whole number.")

    # TODO: Test blank fields


class PointGenTest(ClientTest):
    """
    Test generation of annotation points.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()

    def assertPointsAreInBounds(self, points, bounds):
        """
        Check that every Point in the given points array is within the
        bounds specified.
        bounds is a dict of pixel-position boundaries. For example,
        dict(min_x=0, max_x=19, min_y=0, max_y=29)
        """
        for pt in points:
            self.assertTrue(bounds['min_x'] <= pt.column)
            self.assertTrue(pt.column <= bounds['max_x'])
            self.assertTrue(bounds['min_y'] <= pt.row)
            self.assertTrue(pt.row <= bounds['max_y'])

    def test_simple_random_whole_image(self):
        source = self.create_source(
            self.user,
            image_annotation_area=dict(min_x=0, max_x=100, min_y=0, max_y=100),
            default_point_generation_method=dict(type='simple', points=100))
        # Make the resolution small so that we have a good chance of
        # testing the annotation area boundaries.
        img = self.upload_image(
            self.user, source, image_options=dict(width=20, height=30))

        points = img.point_set.all()
        self.assertEqual(
            points.count(), 100,
            "Should generate the correct number of points")

        self.assertPointsAreInBounds(
            points, dict(min_x=0, max_x=19, min_y=0, max_y=29))

    def test_simple_random_source_annotation_area(self):
        source = self.create_source(
            self.user,
            default_point_generation_method=dict(type='simple', points=100),
            image_annotation_area=dict(
                min_x=19, max_x=62, min_y=7, max_y='90.2'))
        img = self.upload_image(
            self.user, source, image_options=dict(width=40, height=50))

        points = img.point_set.all()
        self.assertEqual(
            points.count(), 100,
            "Should generate the correct number of points")

        self.assertPointsAreInBounds(
            points, dict(
                min_x=math.floor((19/100)*40),
                max_x=math.floor((62/100)*40),
                min_y=math.floor((7/100)*50),
                max_y=math.floor((90.2/100)*50)))

    def test_simple_random_image_specific_annotation_area(self):
        source = self.create_source(
            self.user,
            default_point_generation_method=dict(type='simple', points=100))
        img = self.upload_image(
            self.user, source, image_options=dict(width=40, height=50))

        self.client.force_login(self.user)
        self.client.post(
            reverse('annotation_area_edit', args=[img.pk]),
            data=dict(min_x=8, max_x=36, min_y=0, max_y=18))

        points = img.point_set.all()
        self.assertEqual(
            points.count(), 100,
            "Should generate the correct number of points")

        self.assertPointsAreInBounds(
            points, dict(min_x=8, max_x=36, min_y=0, max_y=18))

    def test_stratified_random_whole_image(self):
        source = self.create_source(
            self.user,
            default_point_generation_method=dict(
                type='stratified', cell_rows=4, cell_columns=5, per_cell=6),
            image_annotation_area=dict(min_x=0, max_x=100, min_y=0, max_y=100),
        )
        img = self.upload_image(
            self.user, source, image_options=dict(width=20, height=30))

        points = img.point_set.all().order_by('point_number')
        self.assertEqual(
            points.count(), 5*4*6,
            "Should generate the correct number of points")

        # Check the strata in order by point number. That's row by row,
        # top to bottom, left to right.
        point_index = 0
        for min_y, max_y in [(0,6), (7,14), (15,21), (22,29)]:
            for min_x, max_x in [(0,3), (4,7), (8,11), (12,15), (16,19)]:
                self.assertPointsAreInBounds(
                    points[point_index:point_index+6],
                    dict(min_x=min_x, max_x=max_x, min_y=min_y, max_y=max_y))
                point_index += 6

    def test_stratified_random_source_annotation_area(self):
        source = self.create_source(
            self.user,
            default_point_generation_method=dict(
                type='stratified', cell_rows=4, cell_columns=5, per_cell=6),
            image_annotation_area=dict(
                min_x=19, max_x=62, min_y=7, max_y='90.2'))
        img = self.upload_image(
            self.user, source, image_options=dict(width=20, height=30))

        points = img.point_set.all().order_by('point_number')
        self.assertEqual(
            points.count(), 5*4*6,
            "Should generate the correct number of points")

        # Check the strata in order by point number. That's row by row,
        # top to bottom, left to right.
        point_index = 0
        for min_y, max_y in [(2,7), (8,14), (15,20), (21,27)]:
            for min_x, max_x in [(3,4), (5,6), (7,8), (9,10), (11,12)]:
                self.assertPointsAreInBounds(
                    points[point_index:point_index+6],
                    dict(min_x=min_x, max_x=max_x, min_y=min_y, max_y=max_y))
                point_index += 6

    def test_stratified_random_image_specific_annotation_area(self):
        source = self.create_source(
            self.user,
            default_point_generation_method=dict(
                type='stratified', cell_rows=4, cell_columns=5, per_cell=6))
        img = self.upload_image(
            self.user, source, image_options=dict(width=40, height=50))

        self.client.force_login(self.user)
        self.client.post(
            reverse('annotation_area_edit', args=[img.pk]),
            data=dict(min_x=8, max_x=36, min_y=0, max_y=18))

        points = img.point_set.order_by('point_number')
        self.assertEqual(
            points.count(), 5*4*6,
            "Should generate the correct number of points")

        # Check the strata in order by point number. That's row by row,
        # top to bottom, left to right.
        point_index = 0
        for min_y, max_y in [(0,3), (4,8), (9,13), (14,18)]:
            for min_x, max_x in [(8,12), (13,18), (19,24), (25,30), (31,36)]:
                self.assertPointsAreInBounds(
                    points[point_index:point_index+6],
                    dict(min_x=min_x, max_x=max_x, min_y=min_y, max_y=max_y))
                point_index += 6

    def test_uniform_grid_whole_image(self):
        source = self.create_source(
            self.user,
            default_point_generation_method=dict(
                type='uniform', cell_rows=4, cell_columns=5),
            image_annotation_area=dict(min_x=0, max_x=100, min_y=0, max_y=100))
        img = self.upload_image(
            self.user, source, image_options=dict(width=20, height=30))

        points = img.point_set.all().order_by('point_number')
        self.assertEqual(
            points.count(), 5*4,
            "Should generate the correct number of points")

        # Check the points in order by point number. That's row by row,
        # top to bottom, left to right.
        point_index = 0
        for y in [3, 10, 18, 25]:
            for x in [1, 5, 9, 13, 17]:
                self.assertEqual(x, points[point_index].column)
                self.assertEqual(y, points[point_index].row)
                point_index += 1

    def test_uniform_grid_source_annotation_area(self):
        source = self.create_source(
            self.user,
            default_point_generation_method=dict(
                type='uniform', cell_rows=4, cell_columns=5),
            image_annotation_area=dict(
                min_x=19, max_x=62, min_y=7, max_y='90.2'))
        img = self.upload_image(
            self.user, source, image_options=dict(width=20, height=30))

        points = img.point_set.all().order_by('point_number')
        self.assertEqual(
            points.count(), 5*4,
            "Should generate the correct number of points")

        # Check the points in order by point number. That's row by row,
        # top to bottom, left to right.
        point_index = 0
        for y in [4, 11, 17, 24]:
            for x in [3, 5, 7, 9, 11]:
                self.assertEqual(x, points[point_index].column)
                self.assertEqual(y, points[point_index].row)
                point_index += 1

    def test_uniform_grid_image_specific_annotation_area(self):
        source = self.create_source(
            self.user,
            default_point_generation_method=dict(
                type='uniform', cell_rows=4, cell_columns=5))
        img = self.upload_image(
            self.user, source, image_options=dict(width=40, height=50))

        self.client.force_login(self.user)
        self.client.post(
            reverse('annotation_area_edit', args=[img.pk]),
            data=dict(min_x=8, max_x=36, min_y=0, max_y=18))

        points = img.point_set.order_by('point_number')
        self.assertEqual(
            points.count(), 5*4,
            "Should generate the correct number of points")

        # Check the points in order by point number. That's row by row,
        # top to bottom, left to right.
        point_index = 0
        for y in [1, 6, 11, 16]:
            for x in [10, 15, 21, 27, 33]:
                self.assertEqual(x, points[point_index].column)
                self.assertEqual(y, points[point_index].row)
                point_index += 1
