from bs4 import BeautifulSoup
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import timezone

from annotations.model_utils import AnnotationArea
from images.model_utils import PointGen
from jobs.models import Job
from jobs.tasks import run_scheduled_jobs_until_empty
from lib.tests.utils import BasePermissionTest, ClientTest
from vision_backend.common import Extractors
from vision_backend.models import Classifier
from vision_backend.tests.tasks.utils import BaseTaskTest
from ..models import Source


class PermissionTest(BasePermissionTest):

    def test_source_new(self):
        url = reverse('source_new')
        template = 'sources/source_new.html'

        self.assertPermissionLevel(
            url, self.SIGNED_IN, template=template,
            deny_type=self.REQUIRE_LOGIN)

    def test_source_edit(self):
        url = reverse('source_edit', args=[self.source.pk])
        template = 'sources/source_edit.html'

        self.source_to_private()
        self.assertPermissionLevel(url, self.SOURCE_ADMIN, template=template)
        self.source_to_public()
        self.assertPermissionLevel(url, self.SOURCE_ADMIN, template=template)

    def test_source_edit_cancel(self):
        url = reverse('source_edit_cancel', args=[self.source.pk])
        template = 'sources/source_main.html'

        self.source_to_private()
        self.assertPermissionLevel(url, self.SOURCE_ADMIN, template=template)
        self.source_to_public()
        self.assertPermissionLevel(url, self.SOURCE_ADMIN, template=template)


class BaseSourceTest(ClientTest):

    form_template: str

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()

        cls.labels = cls.create_labels(cls.user, ['A', 'B', 'C'], 'Group1')

        cls.create_source(name="Source AB")
        cls.source_ab = Source.objects.latest('create_date')
        cls.create_labelset(
            cls.user, cls.source_ab, cls.labels.filter(name__in=['A', 'B']))
        cls.source_ab_robot_1 = cls.create_robot(cls.source_ab)
        cls.source_ab_robot_2 = cls.create_robot(cls.source_ab)

        cls.create_source(name="Source ABC")
        cls.source_abc = Source.objects.latest('create_date')
        cls.create_labelset(cls.user, cls.source_abc, cls.labels)
        cls.source_abc_robot = cls.create_robot(cls.source_abc)

        user2 = cls.create_user()
        cls.create_source(
            user=user2, name="Source outside",
            visibility=Source.VisibilityTypes.PRIVATE)
        cls.source_outside = Source.objects.latest('create_date')
        cls.create_labelset(
            user2, cls.source_outside, cls.labels.filter(name__in=['A', 'B']))
        cls.source_outside_robot = cls.create_robot(cls.source_outside)

    @classmethod
    def create_source(cls, user=None, name="Test Source", **kwargs):
        user = user or cls.user
        cls.client.force_login(user)

        data = dict(
            name=name,
            visibility=Source.VisibilityTypes.PRIVATE,
            affiliation="Testing Society",
            description="Description\ngoes here.",
            key1="Aux1", key2="Aux2", key3="Aux3", key4="Aux4", key5="Aux5",
            # X 10-90%, Y 20-80%
            image_annotation_area_0=10,
            image_annotation_area_1=90,
            image_annotation_area_2=20,
            image_annotation_area_3=80,
            # Simple random, 16 points
            default_point_generation_method_0='m',
            default_point_generation_method_1=16,
            default_point_generation_method_2='',
            default_point_generation_method_3='',
            default_point_generation_method_4='',
            trains_own_classifiers=True,
            feature_extractor_setting=Extractors.EFFICIENTNET.value,
            latitude='-17.3776', longitude='25.1982')
        data.update(**kwargs)
        response = cls.client.post(
            reverse('source_new'), data, follow=True)
        return response

    def assert_field_error(self, response, field_html_name, error_message):
        self.assertTemplateUsed(response, self.form_template)

        response_soup = BeautifulSoup(
            response.content, 'html.parser')

        errors_container = response_soup.find(
            'div', id=f'{field_html_name}-field-errors')
        self.assertIsNotNone(
            errors_container,
            msg="Should find the expected errors container")
        self.assertInHTML(error_message, str(errors_container))


class SourceNewTest(BaseSourceTest):
    """
    Test the New Source page.
    """
    form_template = 'sources/source_new.html'

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.setup_source_count = Source.objects.count()

    def get_and_assert_new_source(self, response):
        new_source = Source.objects.latest('create_date')
        self.assertTemplateUsed('sources/source_main.html')
        self.assertEqual(response.context['source'], new_source)
        self.assertContains(response, "Source successfully created.")
        return new_source

    def assert_input_field_value(self, response, field_id, value):
        response_soup = BeautifulSoup(
            response.content, 'html.parser')

        field = response_soup.find('input', id=field_id)
        self.assertEqual(str(value), field.attrs.get('value', ''))

    def assert_select_field_value(self, response, field_id, value):
        response_soup = BeautifulSoup(
            response.content, 'html.parser')

        field = response_soup.find('select', id=field_id)
        selected_option = field.find('option', selected='')
        self.assertEqual(str(value), selected_option.attrs['value'])

    def assert_error_count(self, response, count):
        response_soup = BeautifulSoup(
            response.content, 'html.parser')

        errors = response_soup.select('ul.errorlist > li')
        self.assertEqual(len(errors), count)

    def test_access_page(self):
        """
        Access the page without errors.
        """
        self.client.force_login(self.user)
        response = self.client.get(reverse('source_new'))
        self.assertStatusOK(response)
        self.assertTemplateUsed(response, 'sources/source_new.html')

    def test_source_defaults(self):
        """
        Check for default values in the source form.
        """
        self.client.force_login(self.user)
        response = self.client.get(reverse('source_new'))

        self.assert_select_field_value(
            response, 'id_visibility', Source.VisibilityTypes.PUBLIC)
        self.assert_input_field_value(response, 'id_key1', 'Aux1')
        self.assert_input_field_value(response, 'id_key2', 'Aux2')
        self.assert_input_field_value(response, 'id_key3', 'Aux3')
        self.assert_input_field_value(response, 'id_key4', 'Aux4')
        self.assert_input_field_value(response, 'id_key5', 'Aux5')
        self.assert_select_field_value(
            response, 'id_default_point_generation_method_0', 'm')
        self.assert_input_field_value(
            response, 'id_default_point_generation_method_1', '30')
        self.assert_input_field_value(
            response, 'id_default_point_generation_method_2', '')
        self.assert_input_field_value(
            response, 'id_default_point_generation_method_3', '')
        self.assert_input_field_value(
            response, 'id_default_point_generation_method_4', '')
        self.assert_input_field_value(
            response, 'id_image_annotation_area_0', '0')
        self.assert_input_field_value(
            response, 'id_image_annotation_area_1', '100')
        self.assert_input_field_value(
            response, 'id_image_annotation_area_2', '0')
        self.assert_input_field_value(
            response, 'id_image_annotation_area_3', '100')
        self.assert_select_field_value(
            response, 'id_trains_own_classifiers', 'True')
        self.assert_select_field_value(
            response, 'id_feature_extractor_setting',
            Extractors.EFFICIENTNET.value)

    def test_source_create(self):
        """
        Successful creation of a new source.
        """
        datetime_before_creation = timezone.now()

        response = self.create_source()

        new_source = self.get_and_assert_new_source(response)

        self.assertEqual(new_source.name, "Test Source")
        self.assertEqual(new_source.visibility, Source.VisibilityTypes.PRIVATE)
        self.assertEqual(new_source.affiliation, "Testing Society")
        self.assertEqual(new_source.description, "Description\ngoes here.")
        self.assertEqual(new_source.key1, "Aux1")
        self.assertEqual(new_source.key2, "Aux2")
        self.assertEqual(new_source.key3, "Aux3")
        self.assertEqual(new_source.key4, "Aux4")
        self.assertEqual(new_source.key5, "Aux5")
        self.assertEqual(
            new_source.default_point_generation_method,
            PointGen(type='simple', points=16).db_value,
        )
        self.assertEqual(
            new_source.image_annotation_area,
            AnnotationArea(
                type=AnnotationArea.TYPE_PERCENTAGES,
                min_x=10, max_x=90, min_y=20, max_y=80).db_value,
        )
        self.assertEqual(new_source.latitude, '-17.3776')
        self.assertEqual(new_source.longitude, '25.1982')
        self.assertEqual(new_source.trains_own_classifiers, True)

        # Fields that aren't in the form.
        self.assertEqual(new_source.labelset, None)
        self.assertEqual(new_source.confidence_threshold, 100)

        # Check that the source creation date is reasonable:
        # - a timestamp taken before creation should be before the creation
        #   date.
        # - a timestamp taken after creation should be after the creation date.
        self.assertTrue(datetime_before_creation <= new_source.create_date)
        self.assertTrue(new_source.create_date <= timezone.now())

    def test_name_required(self):
        response = self.create_source(name="")
        self.assert_field_error(response, 'name', "This field is required.")

        # Should have no source created.
        self.assertEqual(Source.objects.count(), self.setup_source_count)

    def test_affiliation_required(self):
        response = self.create_source(affiliation="")
        self.assert_field_error(
            response, 'affiliation', "This field is required.")

        self.assertEqual(Source.objects.count(), self.setup_source_count)

    def test_description_required(self):
        response = self.create_source(description="")
        self.assert_field_error(
            response, 'description', "This field is required.")

        self.assertEqual(Source.objects.count(), self.setup_source_count)

    def test_aux_names_required(self):
        response = self.create_source(key1="")
        self.assert_field_error(
            response, 'key1', "This field is required.")

        response = self.create_source(key2="")
        self.assert_field_error(
            response, 'key2', "This field is required.")

        response = self.create_source(key3="")
        self.assert_field_error(
            response, 'key3', "This field is required.")

        response = self.create_source(key4="")
        self.assert_field_error(
            response, 'key4', "This field is required.")

        response = self.create_source(key5="")
        self.assert_field_error(
            response, 'key5', "This field is required.")

        # Should have no source created.
        self.assertEqual(Source.objects.count(), self.setup_source_count)

    def test_temporal_aux_name_not_accepted(self):
        """
        If an aux. meta field name looks like it's tracking date or time,
        don't accept it.
        """
        response = self.create_source(
            key1="date",
            key2="Year",
            key3="TIME",
            key4="month",
            key5="day",
        )

        # Should be back on the new source form with errors.
        error_dont_use_temporal = (
            "Date of image acquisition is already a default metadata field."
            " Do not use auxiliary metadata fields"
            " to encode temporal information."
        )
        self.assert_field_error(
            response, 'key1', error_dont_use_temporal)
        self.assert_field_error(
            response, 'key2', error_dont_use_temporal)
        self.assert_field_error(
            response, 'key3', error_dont_use_temporal)
        self.assert_field_error(
            response, 'key4', error_dont_use_temporal)
        self.assert_field_error(
            response, 'key5', error_dont_use_temporal)
        self.assert_error_count(response, 5)
        # Should have no source created.
        self.assertEqual(Source.objects.count(), self.setup_source_count)

    def test_aux_name_conflict_with_builtin_name(self):
        """
        If an aux. meta field name conflicts with a built-in metadata field,
        show an error.
        """
        response = self.create_source(
            key1="name",
            key2="Comments",
            key3="FRAMING GEAR used",
        )

        # Should be back on the new source form with errors.
        error_conflict = (
            "This conflicts with either a built-in metadata"
            " field or another auxiliary field."
        )
        self.assert_field_error(
            response, 'key1', error_conflict)
        self.assert_field_error(
            response, 'key2', error_conflict)
        self.assert_field_error(
            response, 'key3', error_conflict)
        self.assert_error_count(response, 3)
        # Should have no source created.
        self.assertEqual(Source.objects.count(), self.setup_source_count)

    def test_aux_name_conflict_with_other_aux_name(self):
        """
        If two aux. meta field names are the same, show an error.
        """
        response = self.create_source(
            key2="Site",
            key3="site",
        )

        # Should be back on the new source form with errors.
        error_conflict = (
            "This conflicts with either a built-in metadata"
            " field or another auxiliary field."
        )
        self.assert_field_error(
            response, 'key2', error_conflict)
        self.assert_field_error(
            response, 'key3', error_conflict)
        self.assert_error_count(response, 2)
        # Should have no source created.
        self.assertEqual(Source.objects.count(), self.setup_source_count)

    def test_annotation_area_required(self):
        response = self.create_source(image_annotation_area_0='')
        self.assert_field_error(
            response, 'image_annotation_area',
            "All of these fields are required.")

        response = self.create_source(image_annotation_area_1='')
        self.assert_field_error(
            response, 'image_annotation_area',
            "All of these fields are required.")

        response = self.create_source(image_annotation_area_2='')
        self.assert_field_error(
            response, 'image_annotation_area',
            "All of these fields are required.")

        response = self.create_source(image_annotation_area_3='')
        self.assert_field_error(
            response, 'image_annotation_area',
            "All of these fields are required.")

        self.assertEqual(Source.objects.count(), self.setup_source_count)

    def test_annotation_area_max_doesnt_exceed_min(self):
        response = self.create_source(
            image_annotation_area_0='50', image_annotation_area_1='49')
        self.assert_field_error(
            response, 'image_annotation_area',
            "The right boundary x must be greater than the left boundary x.")

        response = self.create_source(
            image_annotation_area_2='70', image_annotation_area_3='70')
        self.assert_field_error(
            response, 'image_annotation_area',
            "The bottom boundary y must be greater than the top boundary y.")

    def test_annotation_area_bounds(self):
        response = self.create_source(
            image_annotation_area_0='-1')
        self.assert_field_error(
            response, 'image_annotation_area',
            "Each value must be between 0 and 100.")

        response = self.create_source(
            image_annotation_area_1='101')
        self.assert_field_error(
            response, 'image_annotation_area',
            "Each value must be between 0 and 100.")

        response = self.create_source(
            image_annotation_area_2='-0.001')
        self.assert_field_error(
            response, 'image_annotation_area',
            "Each value must be between 0 and 100.")

        response = self.create_source(
            image_annotation_area_3='100.001')
        self.assert_field_error(
            response, 'image_annotation_area',
            "Each value must be between 0 and 100.")

    def test_annotation_area_decimals_ok(self):
        response = self.create_source(
            image_annotation_area_0='12.5',
            image_annotation_area_1='87.5',
            image_annotation_area_2='3.333',
            image_annotation_area_3='96.666',
        )

        new_source = self.get_and_assert_new_source(response)

        self.assertEqual(
            new_source.image_annotation_area,
            AnnotationArea(
                type=AnnotationArea.TYPE_PERCENTAGES,
                min_x='12.5', max_x='87.5',
                min_y='3.333', max_y='96.666').db_value)

    def test_annotation_area_decimal_too_long(self):
        response = self.create_source(
            image_annotation_area_0='1.2345')
        self.assert_field_error(
            response, 'image_annotation_area',
            "Up to 3 decimal places are allowed.")

        response = self.create_source(
            image_annotation_area_3='99.9999')
        self.assert_field_error(
            response, 'image_annotation_area',
            "Up to 3 decimal places are allowed.")

    def test_pointgen_type_required(self):
        response = self.create_source(default_point_generation_method_0='')
        self.assert_field_error(
            response, 'default_point_generation_method',
            "Missing type value.")

    def test_pointgen_type_invalid(self):
        response = self.create_source(
            default_point_generation_method_0='straight_line')
        self.assert_field_error(
            response, 'default_point_generation_method',
            "Select a valid choice. straight_line is not one of the available"
            " choices.")

    def test_pointgen_simple_success(self):
        response = self.create_source(
            default_point_generation_method_0=PointGen.Types.SIMPLE.value,
            default_point_generation_method_1=50,
            default_point_generation_method_2='',
            default_point_generation_method_3='',
            default_point_generation_method_4='')

        new_source = self.get_and_assert_new_source(response)

        self.assertEqual(
            new_source.default_point_generation_method,
            PointGen(type='simple', points=50).db_value)

    def test_pointgen_stratified_success(self):
        response = self.create_source(
            default_point_generation_method_0=PointGen.Types.STRATIFIED.value,
            default_point_generation_method_1='',
            default_point_generation_method_2=4,
            default_point_generation_method_3=5,
            default_point_generation_method_4=6)

        new_source = self.get_and_assert_new_source(response)

        self.assertEqual(
            new_source.default_point_generation_method,
            PointGen(
                type='stratified', cell_rows=4,
                cell_columns=5, per_cell=6).db_value)

    def test_pointgen_uniform_grid_success(self):
        response = self.create_source(
            default_point_generation_method_0=PointGen.Types.UNIFORM.value,
            default_point_generation_method_1='',
            default_point_generation_method_2=4,
            default_point_generation_method_3=7,
            default_point_generation_method_4='')

        new_source = self.get_and_assert_new_source(response)

        self.assertEqual(
            new_source.default_point_generation_method,
            PointGen(type='uniform', cell_rows=4, cell_columns=7).db_value)

    def test_pointgen_filling_extra_fields_ok(self):
        # Filling more fields than necessary here, with individually
        # valid values
        response = self.create_source(
            default_point_generation_method_0=PointGen.Types.UNIFORM.value,
            default_point_generation_method_1=2,
            default_point_generation_method_2=4,
            default_point_generation_method_3=7,
            default_point_generation_method_4=1000)

        new_source = self.get_and_assert_new_source(response)

        self.assertEqual(
            new_source.default_point_generation_method,
            PointGen(type='uniform', cell_rows=4, cell_columns=7).db_value)

    def test_pointgen_simple_missing_required_fields(self):
        response = self.create_source(
            default_point_generation_method_0=PointGen.Types.SIMPLE.value,
            default_point_generation_method_1='',
            default_point_generation_method_2='',
            default_point_generation_method_3='',
            default_point_generation_method_4='')

        self.assert_field_error(
            response, 'default_point_generation_method',
            "Missing value(s): Number of points")
        self.assert_error_count(response, 1)

    def test_pointgen_stratified_missing_required_fields(self):
        response = self.create_source(
            default_point_generation_method_0=PointGen.Types.STRATIFIED.value,
            default_point_generation_method_1='',
            default_point_generation_method_2='',
            default_point_generation_method_3='',
            default_point_generation_method_4='')

        self.assert_field_error(
            response, 'default_point_generation_method',
            "Missing value(s): Number of cell rows,"
            " Number of cell columns, Points per cell")

    def test_pointgen_uniform_missing_required_fields(self):
        response = self.create_source(
            default_point_generation_method_0=PointGen.Types.UNIFORM.value,
            default_point_generation_method_1='',
            default_point_generation_method_2='',
            default_point_generation_method_3='',
            default_point_generation_method_4='')

        self.assert_field_error(
            response, 'default_point_generation_method',
            "Missing value(s): Number of cell rows, Number of cell columns")

    def test_pointgen_too_few_simple_points(self):
        response = self.create_source(
            default_point_generation_method_0=PointGen.Types.SIMPLE.value,
            default_point_generation_method_1=0,
            default_point_generation_method_2='',
            default_point_generation_method_3='',
            default_point_generation_method_4='')
        self.assert_field_error(
            response, 'default_point_generation_method',
            "Please use positive integers only.")

    def test_pointgen_too_few_rows_columns_per_cell(self):
        response = self.create_source(
            default_point_generation_method_0=PointGen.Types.STRATIFIED.value,
            default_point_generation_method_1='',
            default_point_generation_method_2=0,
            default_point_generation_method_3=1,
            default_point_generation_method_4=1)
        self.assert_field_error(
            response, 'default_point_generation_method',
            "Please use positive integers only.")

        response = self.create_source(
            default_point_generation_method_0=PointGen.Types.STRATIFIED.value,
            default_point_generation_method_1='',
            default_point_generation_method_2=1,
            default_point_generation_method_3=0,
            default_point_generation_method_4=1)
        self.assert_field_error(
            response, 'default_point_generation_method',
            "Please use positive integers only.")

        response = self.create_source(
            default_point_generation_method_0=PointGen.Types.STRATIFIED.value,
            default_point_generation_method_1='',
            default_point_generation_method_2=1,
            default_point_generation_method_3=1,
            default_point_generation_method_4=0)
        self.assert_field_error(
            response, 'default_point_generation_method',
            "Please use positive integers only.")

    @override_settings(MAX_POINTS_PER_IMAGE=1000)
    def test_pointgen_max_points_ok(self):
        # Match the point limit exactly
        response = self.create_source(
            default_point_generation_method_0=PointGen.Types.STRATIFIED.value,
            default_point_generation_method_1='',
            default_point_generation_method_2=10,
            default_point_generation_method_3=10,
            default_point_generation_method_4=10)

        new_source = self.get_and_assert_new_source(response)

        self.assertEqual(
            new_source.default_point_generation_method,
            PointGen(
                type='stratified', cell_rows=10,
                cell_columns=10, per_cell=10).db_value)

    @override_settings(MAX_POINTS_PER_IMAGE=1000)
    def test_pointgen_above_max_points(self):
        response = self.create_source(
            default_point_generation_method_0=PointGen.Types.STRATIFIED.value,
            default_point_generation_method_1='',
            default_point_generation_method_2=7,
            default_point_generation_method_3=11,
            default_point_generation_method_4=13)
        self.assert_field_error(
            response, 'default_point_generation_method',
            "You specified 1001 points total."
            " Please make it no more than 1000.")

    def test_latitude_longitude_required(self):
        response = self.create_source(latitude="")
        self.assert_field_error(
            response, 'latitude', "This field is required.")

        response = self.create_source(longitude="")
        self.assert_field_error(
            response, 'longitude', "This field is required.")

        self.assertEqual(Source.objects.count(), self.setup_source_count)

    def test_latitude_longitude_not_numeric(self):
        response = self.create_source(latitude="abc")
        self.assert_field_error(
            response, 'latitude', "Latitude is not a number.")

        response = self.create_source(longitude="12abc")
        self.assert_field_error(
            response, 'longitude', "Longitude is not a number.")

        self.assertEqual(Source.objects.count(), self.setup_source_count)

    def test_latitude_longitude_out_of_range(self):
        response = self.create_source(latitude="-90.01")
        self.assert_field_error(
            response, 'latitude', "Latitude is out of range.")

        response = self.create_source(latitude="91")
        self.assert_field_error(
            response, 'latitude', "Latitude is out of range.")

        response = self.create_source(longitude="-181")
        self.assert_field_error(
            response, 'longitude', "Longitude is out of range.")

        response = self.create_source(longitude="180.0002")
        self.assert_field_error(
            response, 'longitude', "Longitude is out of range.")

        self.assertEqual(Source.objects.count(), self.setup_source_count)

    def test_deployed_classifier_valid(self):
        response = self.create_source(
            trains_own_classifiers=False,
            deployed_classifier=self.source_ab_robot_1.pk)

        new_source = self.get_and_assert_new_source(response)

        self.assertFalse(new_source.trains_own_classifiers)
        self.assertEqual(
            new_source.deployed_classifier_id, self.source_ab_robot_1.pk)
        self.assertEqual(
            new_source.deployed_source_id,
            self.source_ab.pk)

    def test_deployed_classifier_blank(self):
        response = self.create_source(
            trains_own_classifiers=False,
            deployed_classifier='')

        new_source = self.get_and_assert_new_source(response)

        self.assertFalse(new_source.trains_own_classifiers)
        self.assertEqual(new_source.deployed_classifier, None)
        self.assertEqual(new_source.deployed_source_id, None)

    def test_deployed_classifier_nonexistent(self):
        # IDs start from 1, so this shouldn't exist.
        response = self.create_source(
            trains_own_classifiers=False,
            deployed_classifier='0')
        self.assert_field_error(
            response, 'deployed_classifier',
            "This isn't a valid classifier ID.")

    def test_deployed_classifier_permission_denied(self):
        response = self.create_source(
            trains_own_classifiers=False,
            deployed_classifier=self.source_outside_robot.pk)
        self.assert_field_error(
            response, 'deployed_classifier',
            "You don't have access to this classifier's source.")

    def test_deployed_classifier_not_accepted(self):
        for status in [
            Classifier.LACKING_UNIQUE_LABELS,
            Classifier.TRAIN_PENDING,
            Classifier.TRAIN_ERROR,
            Classifier.REJECTED_ACCURACY,
        ]:
            classifier = self.create_robot(self.source_ab)
            classifier.status = status
            classifier.save()

            response = self.create_source(
                trains_own_classifiers=False,
                deployed_classifier=classifier.pk)
            self.assert_field_error(
                response, 'deployed_classifier',
                "This isn't a valid classifier ID.")


# Make these all different from what create_source() would use.
# Except trains_own_classifiers, which we'll test separately.
source_kwargs_2 = dict(
    name="Test Source 2",
    visibility=Source.VisibilityTypes.PUBLIC,
    affiliation="Testing Association",
    description="This is\na description.",
    key1="Island",
    key2="Site",
    key3="Habitat",
    key4="Section",
    key5="Transect",
    image_annotation_area_0=5,
    image_annotation_area_1=95,
    image_annotation_area_2=5,
    image_annotation_area_3=95,
    default_point_generation_method_0=PointGen.Types.STRATIFIED.value,
    default_point_generation_method_2=4,
    default_point_generation_method_3=6,
    default_point_generation_method_4=3,
    confidence_threshold=80,
    trains_own_classifiers=True,
    feature_extractor_setting=Extractors.VGG16.value,
    latitude='5.789',
    longitude='-50',
)


class SourceEditTest(BaseSourceTest):
    """
    Test the Edit Source page.
    """
    form_template = 'sources/source_edit.html'

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.create_source()
        cls.source = Source.objects.latest('create_date')
        cls.url = reverse('source_edit', args=[cls.source.pk])

    def edit_source(self, **kwargs):
        self.client.force_login(self.user)
        data = source_kwargs_2 | kwargs
        response = self.client.post(self.url, data, follow=True)
        return response

    def test_access_page(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertStatusOK(response)
        self.assertTemplateUsed(response, 'sources/source_edit.html')

    def test_source_edit(self):
        response = self.edit_source()

        self.assertRedirects(
            response,
            reverse('source_main', kwargs={'source_id': self.source.pk})
        )

        self.source.refresh_from_db()
        self.assertEqual(self.source.name, "Test Source 2")
        self.assertEqual(self.source.visibility, Source.VisibilityTypes.PUBLIC)
        self.assertEqual(self.source.affiliation, "Testing Association")
        self.assertEqual(self.source.description, "This is\na description.")
        self.assertEqual(self.source.key1, "Island")
        self.assertEqual(self.source.key2, "Site")
        self.assertEqual(self.source.key3, "Habitat")
        self.assertEqual(self.source.key4, "Section")
        self.assertEqual(self.source.key5, "Transect")
        self.assertEqual(
            self.source.image_annotation_area,
            AnnotationArea(
                type=AnnotationArea.TYPE_PERCENTAGES,
                min_x=5, max_x=95, min_y=5, max_y=95).db_value,
        )
        self.assertEqual(
            self.source.default_point_generation_method,
            PointGen(
                type='stratified', cell_rows=4,
                cell_columns=6, per_cell=3).db_value,
        )
        self.assertEqual(self.source.confidence_threshold, 80)
        self.assertEqual(
            self.source.feature_extractor_setting, Extractors.VGG16.value)
        self.assertEqual(self.source.latitude, '5.789')
        self.assertEqual(self.source.longitude, '-50')

    def test_cancel(self):
        """Test the view tied to the cancel button."""
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('source_edit_cancel', args=[self.source.pk]), follow=True)
        self.assertTemplateUsed(
            response, 'sources/source_main.html',
            "Should redirect to source main")
        self.assertContains(
            response, "Edit cancelled.",
            msg_prefix="Should show the appropriate message")

    def test_mode_to_deploy_with_matching_labelset(self):
        self.create_labelset(
            self.user, self.source, self.labels.filter(name__in=['A', 'B']))
        self.edit_source(
            trains_own_classifiers=False,
            deployed_classifier=self.source_ab_robot_1.pk)

        self.source.refresh_from_db()
        self.assertFalse(self.source.trains_own_classifiers)
        self.assertEqual(
            self.source.deployed_classifier_id, self.source_ab_robot_1.pk)
        self.assertEqual(
            self.source.deployed_source_id,
            self.source_ab.pk)

    def test_mode_to_deploy_with_no_labelset(self):
        self.assertIsNone(
            self.source.labelset, msg="Should start with no labelset")
        self.edit_source(
            trains_own_classifiers=False,
            deployed_classifier=self.source_ab_robot_1.pk)

        self.source.refresh_from_db()
        self.assertIsNotNone(
            self.source.labelset,
            msg="Source edit should result in labelset creation")
        self.assertSetEqual(
            {label.name for label in self.source.labelset.get_globals()},
            {'A', 'B'},
            msg="Should have the same labels as the deployed classifier",
        )

    def test_mode_to_deploy_with_blank_classifier(self):
        self.edit_source(
            trains_own_classifiers=False,
            deployed_classifier='')

        self.source.refresh_from_db()
        self.assertFalse(self.source.trains_own_classifiers)
        self.assertIsNone(self.source.deployed_classifier)
        self.assertIsNone(self.source.deployed_source_id)

    def test_mode_to_train_without_trained_classifier(self):
        # First be in deploy mode...
        self.edit_source(
            trains_own_classifiers=False,
            deployed_classifier=self.source_ab_robot_1.pk)
        self.source.refresh_from_db()
        self.assertFalse(self.source.trains_own_classifiers)

        # Then switch back to train mode
        self.edit_source(
            trains_own_classifiers=True,
            deployed_classifier='')
        self.source.refresh_from_db()
        self.assertTrue(self.source.trains_own_classifiers)
        self.assertIsNone(self.source.deployed_classifier)
        self.assertIsNone(self.source.deployed_source_id)

    def test_mode_to_train_with_trained_classifier(self):
        own_robot = self.create_robot(self.source)

        # First be in deploy mode...
        self.edit_source(
            trains_own_classifiers=False,
            deployed_classifier=self.source_ab_robot_1.pk)
        self.source.refresh_from_db()
        self.assertFalse(self.source.trains_own_classifiers)

        # Then switch back to train mode
        self.edit_source(
            trains_own_classifiers=True,
            deployed_classifier='')
        self.source.refresh_from_db()
        self.assertTrue(self.source.trains_own_classifiers)
        self.assertEqual(self.source.deployed_classifier.pk, own_robot.pk)
        self.assertEqual(self.source.deployed_source_id, self.source.pk)

    def test_deployed_classifier_different(self):
        self.edit_source(
            trains_own_classifiers=False,
            deployed_classifier=self.source_ab_robot_1.pk)
        self.source.refresh_from_db()
        self.assertEqual(
            self.source.deployed_classifier_id, self.source_ab_robot_1.pk)

        self.edit_source(
            trains_own_classifiers=False,
            deployed_classifier=self.source_ab_robot_2.pk)
        self.source.refresh_from_db()
        self.assertEqual(
            self.source.deployed_classifier_id, self.source_ab_robot_2.pk)

    def test_deployed_classifier_nonexistent(self):
        # IDs start from 1, so this shouldn't exist.
        response = self.edit_source(
            trains_own_classifiers=False,
            deployed_classifier='0')
        self.assert_field_error(
            response, 'deployed_classifier',
            "This isn't a valid classifier ID.")

    def test_deployed_classifier_permission_denied(self):
        response = self.edit_source(
            trains_own_classifiers=False,
            deployed_classifier=self.source_outside_robot.pk)
        self.assert_field_error(
            response, 'deployed_classifier',
            "You don't have access to this classifier's source.")

    def do_test_deployed_classifier_labelset_mismatch(
        self, label_names, deployed_classifier
    ):
        self.create_labelset(
            self.user, self.source, self.labels.filter(name__in=label_names))
        response = self.edit_source(
            trains_own_classifiers=False,
            deployed_classifier=deployed_classifier.pk)
        self.assert_field_error(
            response, 'deployed_classifier',
            "This source's labelset must match the"
            " classifier's source's labelset.")

    def test_labelset_mismatch_1(self):
        # Subset
        self.do_test_deployed_classifier_labelset_mismatch(
            ['A', 'B'], self.source_abc_robot)

    def test_labelset_mismatch_2(self):
        # Superset
        self.do_test_deployed_classifier_labelset_mismatch(
            ['A', 'B', 'C'], self.source_ab_robot_1)

    def test_labelset_mismatch_3(self):
        # Same size, one label different
        self.do_test_deployed_classifier_labelset_mismatch(
            ['A', 'C'], self.source_ab_robot_1)

    def test_classifiers_help_text_this_source(self):
        self.create_labelset(self.user, self.source, self.labels)
        own_robot = self.create_robot(self.source)
        self.edit_source(trains_own_classifiers=True)

        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertContains(
            response,
            f"Currently selected: {own_robot.pk},"
            f" from this source")

    def test_classifiers_help_text_other_source(self):
        self.edit_source(
            trains_own_classifiers=False,
            deployed_classifier=self.source_ab_robot_1.pk)
        self.source.refresh_from_db()

        self.client.force_login(self.user)
        response = self.client.get(self.url)

        classifier_source_link = reverse(
            'source_main', args=[self.source_ab.pk])
        self.assertContains(
            response,
            f'Currently selected: {self.source_ab_robot_1.pk}, from'
            f' <a href="{classifier_source_link}" target="_blank">'
            f'{self.source_ab.name}</a>')

    def test_classifiers_help_text_none_selected(self):
        self.edit_source(
            trains_own_classifiers=False,
            deployed_classifier='')
        self.source.refresh_from_db()

        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertNotContains(response, "Currently selected:")


class SourceFormFieldAvailability(ClientTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.new_url = reverse('source_new')

        cls.source_with_training = cls.create_source(cls.user)
        cls.with_training_url = reverse(
            'source_edit', args=[cls.source_with_training.pk])

        cls.source_without_training = cls.create_source(cls.user)
        cls.source_without_training.trains_own_classifiers = False
        cls.source_without_training.save()
        cls.without_training_url = reverse(
            'source_edit', args=[cls.source_without_training.pk])

    def field_is_in_form(self, source_form_url, field_id):
        self.client.force_login(self.user)
        response = self.client.get(source_form_url)
        response_soup = BeautifulSoup(
            response.content, 'html.parser')
        field = response_soup.find(id=field_id)
        return field is not None

    def test_confidence_threshold(self):
        self.assertFalse(self.field_is_in_form(
            self.new_url, 'id_confidence_threshold'))
        self.assertTrue(self.field_is_in_form(
            self.with_training_url, 'id_confidence_threshold'))
        self.assertTrue(self.field_is_in_form(
            self.without_training_url, 'id_confidence_threshold'))


@override_settings(FORCE_DUMMY_EXTRACTOR=False)
class SourceEditBackendStatusTest(BaseTaskTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.url = reverse('source_edit', args=[cls.source.pk])

        cls.own_robot = cls.create_robot(cls.source)

        source_effnet = cls.create_source(
            cls.user,
            trains_own_classifier=True,
            feature_extractor_setting=Extractors.EFFICIENTNET.value)
        cls.create_labelset(cls.user, source_effnet, cls.labels)
        cls.effnet_robot = cls.create_robot(source_effnet)
        cls.effnet_robot_2 = cls.create_robot(source_effnet)

        source_vgg = cls.create_source(
            cls.user,
            trains_own_classifier=True,
            feature_extractor_setting=Extractors.VGG16.value)
        cls.create_labelset(cls.user, source_vgg, cls.labels)
        cls.vgg_robot = cls.create_robot(source_vgg)

    def edit_source(self, **kwargs):
        self.client.force_login(self.user)
        data = source_kwargs_2 | kwargs
        response = self.client.post(self.url, data, follow=True)
        return response

    def do_test(
        self,
        trains_own_classifiers=(True, True),
        feature_extractor_setting=(
            Extractors.EFFICIENTNET.value, Extractors.EFFICIENTNET.value),
        deployed_classifier=(None, None),
    ):
        # Fake-extract EfficientNet features for one image. (Just mark as
        # extracted.)
        image = self.upload_image(self.user, self.source)
        image.features.extracted = True
        image.features.extractor = Extractors.EFFICIENTNET.value
        image.features.save()
        # Process any source checks, so that later we know any scheduled source
        # checks were scheduled by edit-source.
        run_scheduled_jobs_until_empty()

        # Directly set initial state of fields.
        self.source.trains_own_classifiers = trains_own_classifiers[0]
        self.source.feature_extractor_setting = feature_extractor_setting[0]
        self.source.deployed_classifier = deployed_classifier[0]
        self.source.save()

        # Set final state of fields through the edit-source view, and return
        # response.
        if deployed_classifier[1] is None:
            deployed_classifier_form_value = ''
        else:
            deployed_classifier_form_value = deployed_classifier[1].pk
        with self.captureOnCommitCallbacks(execute=True):
            response = self.edit_source(
                trains_own_classifiers=trains_own_classifiers[1],
                feature_extractor_setting=feature_extractor_setting[1],
                deployed_classifier=deployed_classifier_form_value,
            )
        return response

    def assert_classifier_reset(self, response):
        self.assertTrue(
            Job.objects.filter(
                job_name='reset_classifiers_for_source').exists(),
            msg="Should schedule classifier reset")

        self.assertContains(
            response,
            "Source successfully edited. Classifier history will be cleared.",
            msg_prefix="Page should show the appropriate message")

    def assert_no_classifier_reset(self, response):
        self.assertFalse(
            Job.objects.filter(
                job_name='reset_classifiers_for_source').exists(),
            msg="Should not schedule classifier reset")

        self.assertContains(
            response, "Source successfully edited.",
            msg_prefix="Page should show the appropriate message")
        self.assertNotContains(
            response, "Classifier history will be cleared.",
            msg_prefix="Page should show the appropriate message")

    def assert_feature_reset(self):
        self.assertTrue(
            Job.objects.filter(
                job_name='reset_features_for_source').exists(),
            msg="Should schedule feature reset")

    def assert_no_feature_reset(self):
        self.assertFalse(
            Job.objects.filter(
                job_name='reset_features_for_source').exists(),
            msg="Should not schedule feature reset")

    def assert_source_check(self):
        self.assertTrue(
            Job.objects.incomplete().filter(
                job_name='check_source').exists(),
            msg="Should schedule source check")

    def assert_no_source_check(self):
        self.assertFalse(
            Job.objects.incomplete().filter(
                job_name='check_source').exists(),
            msg="Should not schedule source check")

    def test_extractor_changed_in_train_mode(self):
        response = self.do_test(
            feature_extractor_setting=(
                Extractors.EFFICIENTNET.value, Extractors.VGG16.value),
        )
        self.assert_classifier_reset(response)
        self.assert_feature_reset()
        self.assert_no_source_check()

    def test_extractor_same_in_train_mode(self):
        response = self.do_test(
            feature_extractor_setting=(
                Extractors.EFFICIENTNET.value, Extractors.EFFICIENTNET.value),
        )
        self.assert_no_classifier_reset(response)
        self.assert_no_feature_reset()
        self.assert_no_source_check()

    def test_train_mode_to_deploying_classifier_of_other_extractor(self):
        response = self.do_test(
            trains_own_classifiers=(True, False),
            deployed_classifier=(self.own_robot, self.vgg_robot),
        )
        self.assert_no_classifier_reset(response)
        self.assert_feature_reset()
        self.assert_no_source_check()

    def test_train_mode_to_deploying_classifier_of_same_extractor(self):
        response = self.do_test(
            trains_own_classifiers=(True, False),
            deployed_classifier=(self.own_robot, self.effnet_robot),
        )
        self.assert_no_classifier_reset(response)
        self.assert_no_feature_reset()
        self.assert_source_check()

    def test_train_mode_to_deploying_no_classifier(self):
        response = self.do_test(
            trains_own_classifiers=(True, False),
            deployed_classifier=(self.own_robot, None),
        )
        self.assert_no_classifier_reset(response)
        self.assert_no_feature_reset()
        self.assert_source_check()

    def test_change_to_classifier_of_same_extractor_in_deploy_mode(self):
        response = self.do_test(
            trains_own_classifiers=(False, False),
            deployed_classifier=(self.effnet_robot, self.effnet_robot_2),
        )
        self.assert_no_classifier_reset(response)
        self.assert_no_feature_reset()
        self.assert_source_check()

    def test_change_to_classifier_of_other_extractor_in_deploy_mode(self):
        response = self.do_test(
            trains_own_classifiers=(False, False),
            deployed_classifier=(self.effnet_robot, self.vgg_robot),
        )
        self.assert_no_classifier_reset(response)
        self.assert_feature_reset()
        self.assert_no_source_check()

    def test_null_out_classifier_in_deploy_mode(self):
        response = self.do_test(
            trains_own_classifiers=(False, False),
            deployed_classifier=(self.effnet_robot, None),
        )
        self.assert_no_classifier_reset(response)
        self.assert_no_feature_reset()
        self.assert_source_check()

    def test_null_to_classifier_matching_previous_features(self):
        response = self.do_test(
            trains_own_classifiers=(False, False),
            deployed_classifier=(None, self.effnet_robot),
        )
        self.assert_no_classifier_reset(response)
        self.assert_no_feature_reset()
        self.assert_source_check()

    def test_null_to_classifier_not_matching_previous_features(self):
        response = self.do_test(
            trains_own_classifiers=(False, False),
            deployed_classifier=(None, self.vgg_robot),
        )
        self.assert_no_classifier_reset(response)
        self.assert_feature_reset()
        self.assert_no_source_check()

    def test_deploy_mode_to_training_with_same_extractor(self):
        self.do_test(
            trains_own_classifiers=(False, True),
            feature_extractor_setting=(
                Extractors.EFFICIENTNET.value, Extractors.EFFICIENTNET.value),
            deployed_classifier=(self.effnet_robot, None),
        )
        self.assert_no_feature_reset()
        self.assert_source_check()

    def test_deploy_mode_to_training_with_other_extractor(self):
        self.do_test(
            trains_own_classifiers=(False, True),
            feature_extractor_setting=(
                Extractors.EFFICIENTNET.value, Extractors.VGG16.value),
            deployed_classifier=(self.effnet_robot, None),
        )
        self.assert_feature_reset()
        self.assert_no_source_check()

    def test_null_to_training_matching_previous_features(self):
        self.do_test(
            trains_own_classifiers=(False, True),
            feature_extractor_setting=(
                Extractors.EFFICIENTNET.value, Extractors.EFFICIENTNET.value),
            deployed_classifier=(None, None),
        )
        self.assert_no_feature_reset()
        self.assert_source_check()

    def test_null_to_training_not_matching_previous_features(self):
        self.do_test(
            trains_own_classifiers=(False, True),
            feature_extractor_setting=(
                Extractors.EFFICIENTNET.value, Extractors.VGG16.value),
            deployed_classifier=(None, None),
        )
        self.assert_feature_reset()
        self.assert_no_source_check()
