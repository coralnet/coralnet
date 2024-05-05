from bs4 import BeautifulSoup
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import timezone

from annotations.model_utils import AnnotationArea
from images.model_utils import PointGen
from jobs.models import Job
from lib.tests.utils import BasePermissionTest, ClientTest
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


class SourceNewTest(ClientTest):
    """
    Test the New Source page.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()

    def create_source(self, **kwargs):
        data = dict(
            name="Test Source",
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
            feature_extractor_setting='efficientnet_b0_ver1',
            latitude='-17.3776', longitude='25.1982')
        data.update(**kwargs)
        response = self.client.post(
            reverse('source_new'), data, follow=True)
        return response

    def assert_input_field_value(self, response, field_id, value):
        response_soup = BeautifulSoup(
            response.content, 'html.parser')

        field = response_soup.find('input', id=field_id)
        self.assertEqual(str(value), field.attrs['value'])

    def assert_select_field_value(self, response, field_id, value):
        response_soup = BeautifulSoup(
            response.content, 'html.parser')

        field = response_soup.find('select', id=field_id)
        selected_option = field.find('option', selected='')
        self.assertEqual(str(value), selected_option.attrs['value'])

    def assert_field_error(self, response, field_html_name, error_message):
        response_soup = BeautifulSoup(
            response.content, 'html.parser')

        errors_container = response_soup.find(
            'div', id=f'{field_html_name}-field-errors')
        self.assertIsNotNone(
            errors_container,
            msg="Should find the expected errors container")
        self.assertInHTML(error_message, str(errors_container))

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
            response, 'id_feature_extractor_setting', 'efficientnet_b0_ver1')

    def test_source_create(self):
        """
        Successful creation of a new source.
        """
        datetime_before_creation = timezone.now()

        self.client.force_login(self.user)
        response = self.create_source()

        new_source = Source.objects.latest('create_date')
        self.assertTemplateUsed('sources/source_main.html')
        self.assertEqual(response.context['source'], new_source)
        self.assertContains(response, "Source successfully created.")

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

        # Fields that aren't in the form.
        self.assertEqual(new_source.labelset, None)
        self.assertEqual(new_source.confidence_threshold, 100)
        self.assertEqual(new_source.enable_robot_classifier, True)

        # Check that the source creation date is reasonable:
        # - a timestamp taken before creation should be before the creation
        #   date.
        # - a timestamp taken after creation should be after the creation date.
        self.assertTrue(datetime_before_creation <= new_source.create_date)
        self.assertTrue(new_source.create_date <= timezone.now())

    def test_name_required(self):
        self.client.force_login(self.user)

        response = self.create_source(name="")
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assert_field_error(response, 'name', "This field is required.")

        # Should have no source created.
        self.assertEqual(Source.objects.all().count(), 0)

    def test_affiliation_required(self):
        self.client.force_login(self.user)

        response = self.create_source(affiliation="")
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assert_field_error(
            response, 'affiliation', "This field is required.")

        self.assertEqual(Source.objects.all().count(), 0)

    def test_description_required(self):
        self.client.force_login(self.user)

        response = self.create_source(description="")
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assert_field_error(
            response, 'description', "This field is required.")

        self.assertEqual(Source.objects.all().count(), 0)

    def test_aux_names_required(self):
        self.client.force_login(self.user)

        response = self.create_source(key1="")
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assert_field_error(
            response, 'key1', "This field is required.")

        response = self.create_source(key2="")
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assert_field_error(
            response, 'key2', "This field is required.")

        response = self.create_source(key3="")
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assert_field_error(
            response, 'key3', "This field is required.")

        response = self.create_source(key4="")
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assert_field_error(
            response, 'key4', "This field is required.")

        response = self.create_source(key5="")
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assert_field_error(
            response, 'key5', "This field is required.")

        # Should have no source created.
        self.assertEqual(Source.objects.all().count(), 0)

    def test_temporal_aux_name_not_accepted(self):
        """
        If an aux. meta field name looks like it's tracking date or time,
        don't accept it.
        """
        self.client.force_login(self.user)
        response = self.create_source(
            key1="date",
            key2="Year",
            key3="TIME",
            key4="month",
            key5="day",
        )

        # Should be back on the new source form with errors.
        self.assertTemplateUsed(response, 'sources/source_new.html')
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
        self.assertEqual(Source.objects.all().count(), 0)

    def test_aux_name_conflict_with_builtin_name(self):
        """
        If an aux. meta field name conflicts with a built-in metadata field,
        show an error.
        """
        self.client.force_login(self.user)
        response = self.create_source(
            key1="name",
            key2="Comments",
            key3="FRAMING GEAR used",
        )

        # Should be back on the new source form with errors.
        self.assertTemplateUsed(response, 'sources/source_new.html')
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
        self.assertEqual(Source.objects.all().count(), 0)

    def test_aux_name_conflict_with_other_aux_name(self):
        """
        If two aux. meta field names are the same, show an error.
        """
        self.client.force_login(self.user)
        response = self.create_source(
            key2="Site",
            key3="site",
        )

        # Should be back on the new source form with errors.
        self.assertTemplateUsed(response, 'sources/source_new.html')
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
        self.assertEqual(Source.objects.all().count(), 0)

    def test_annotation_area_required(self):
        self.client.force_login(self.user)

        response = self.create_source(image_annotation_area_0='')
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assert_field_error(
            response, 'image_annotation_area',
            "All of these fields are required.")

        response = self.create_source(image_annotation_area_1='')
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assert_field_error(
            response, 'image_annotation_area',
            "All of these fields are required.")

        response = self.create_source(image_annotation_area_2='')
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assert_field_error(
            response, 'image_annotation_area',
            "All of these fields are required.")

        response = self.create_source(image_annotation_area_3='')
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assert_field_error(
            response, 'image_annotation_area',
            "All of these fields are required.")

        self.assertEqual(Source.objects.all().count(), 0)

    def test_annotation_area_max_doesnt_exceed_min(self):
        self.client.force_login(self.user)

        response = self.create_source(
            image_annotation_area_0='50', image_annotation_area_1='49')
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assert_field_error(
            response, 'image_annotation_area',
            "The right boundary x must be greater than the left boundary x.")

        response = self.create_source(
            image_annotation_area_2='70', image_annotation_area_3='70')
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assert_field_error(
            response, 'image_annotation_area',
            "The bottom boundary y must be greater than the top boundary y.")

    def test_annotation_area_bounds(self):
        self.client.force_login(self.user)

        response = self.create_source(
            image_annotation_area_0='-1')
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assert_field_error(
            response, 'image_annotation_area',
            "Each value must be between 0 and 100.")

        response = self.create_source(
            image_annotation_area_1='101')
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assert_field_error(
            response, 'image_annotation_area',
            "Each value must be between 0 and 100.")

        response = self.create_source(
            image_annotation_area_2='-0.001')
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assert_field_error(
            response, 'image_annotation_area',
            "Each value must be between 0 and 100.")

        response = self.create_source(
            image_annotation_area_3='100.001')
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assert_field_error(
            response, 'image_annotation_area',
            "Each value must be between 0 and 100.")

    def test_annotation_area_decimals_ok(self):
        self.client.force_login(self.user)

        response = self.create_source(
            image_annotation_area_0='12.5',
            image_annotation_area_1='87.5',
            image_annotation_area_2='3.333',
            image_annotation_area_3='96.666',
        )

        new_source = Source.objects.latest('create_date')
        self.assertTemplateUsed('sources/source_main.html')
        self.assertEqual(response.context['source'], new_source)

        self.assertEqual(
            new_source.image_annotation_area,
            AnnotationArea(
                type=AnnotationArea.TYPE_PERCENTAGES,
                min_x='12.5', max_x='87.5',
                min_y='3.333', max_y='96.666').db_value)

    def test_annotation_area_decimal_too_long(self):
        self.client.force_login(self.user)

        response = self.create_source(
            image_annotation_area_0='1.2345')
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assert_field_error(
            response, 'image_annotation_area',
            "Up to 3 decimal places are allowed.")

        response = self.create_source(
            image_annotation_area_3='99.9999')
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assert_field_error(
            response, 'image_annotation_area',
            "Up to 3 decimal places are allowed.")

    def test_pointgen_type_required(self):
        self.client.force_login(self.user)

        response = self.create_source(default_point_generation_method_0='')
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assert_field_error(
            response, 'default_point_generation_method',
            "Missing type value.")

    def test_pointgen_type_invalid(self):
        self.client.force_login(self.user)

        response = self.create_source(
            default_point_generation_method_0='straight_line')
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assert_field_error(
            response, 'default_point_generation_method',
            "Select a valid choice. straight_line is not one of the available"
            " choices.")

    def test_pointgen_simple_success(self):
        self.client.force_login(self.user)

        response = self.create_source(
            default_point_generation_method_0=PointGen.Types.SIMPLE.value,
            default_point_generation_method_1=50,
            default_point_generation_method_2='',
            default_point_generation_method_3='',
            default_point_generation_method_4='')

        new_source = Source.objects.latest('create_date')
        self.assertTemplateUsed('sources/source_main.html')
        self.assertEqual(response.context['source'], new_source)

        self.assertEqual(
            new_source.default_point_generation_method,
            PointGen(type='simple', points=50).db_value)

    def test_pointgen_stratified_success(self):
        self.client.force_login(self.user)

        response = self.create_source(
            default_point_generation_method_0=PointGen.Types.STRATIFIED.value,
            default_point_generation_method_1='',
            default_point_generation_method_2=4,
            default_point_generation_method_3=5,
            default_point_generation_method_4=6)

        new_source = Source.objects.latest('create_date')
        self.assertTemplateUsed('sources/source_main.html')
        self.assertEqual(response.context['source'], new_source)

        self.assertEqual(
            new_source.default_point_generation_method,
            PointGen(
                type='stratified', cell_rows=4,
                cell_columns=5, per_cell=6).db_value)

    def test_pointgen_uniform_grid_success(self):
        self.client.force_login(self.user)

        response = self.create_source(
            default_point_generation_method_0=PointGen.Types.UNIFORM.value,
            default_point_generation_method_1='',
            default_point_generation_method_2=4,
            default_point_generation_method_3=7,
            default_point_generation_method_4='')

        new_source = Source.objects.latest('create_date')
        self.assertTemplateUsed('sources/source_main.html')
        self.assertEqual(response.context['source'], new_source)

        self.assertEqual(
            new_source.default_point_generation_method,
            PointGen(type='uniform', cell_rows=4, cell_columns=7).db_value)

    def test_pointgen_filling_extra_fields_ok(self):
        self.client.force_login(self.user)

        # Filling more fields than necessary here, with individually
        # valid values
        response = self.create_source(
            default_point_generation_method_0=PointGen.Types.UNIFORM.value,
            default_point_generation_method_1=2,
            default_point_generation_method_2=4,
            default_point_generation_method_3=7,
            default_point_generation_method_4=1000)

        new_source = Source.objects.latest('create_date')
        self.assertTemplateUsed('sources/source_main.html')
        self.assertEqual(response.context['source'], new_source)

        self.assertEqual(
            new_source.default_point_generation_method,
            PointGen(type='uniform', cell_rows=4, cell_columns=7).db_value)

    def test_pointgen_simple_missing_required_fields(self):
        self.client.force_login(self.user)

        response = self.create_source(
            default_point_generation_method_0=PointGen.Types.SIMPLE.value,
            default_point_generation_method_1='',
            default_point_generation_method_2='',
            default_point_generation_method_3='',
            default_point_generation_method_4='')

        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assert_field_error(
            response, 'default_point_generation_method',
            "Missing value(s): Number of points")
        self.assert_error_count(response, 1)

    def test_pointgen_stratified_missing_required_fields(self):
        self.client.force_login(self.user)

        response = self.create_source(
            default_point_generation_method_0=PointGen.Types.STRATIFIED.value,
            default_point_generation_method_1='',
            default_point_generation_method_2='',
            default_point_generation_method_3='',
            default_point_generation_method_4='')

        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assert_field_error(
            response, 'default_point_generation_method',
            "Missing value(s): Number of cell rows,"
            " Number of cell columns, Points per cell")

    def test_pointgen_uniform_missing_required_fields(self):
        self.client.force_login(self.user)

        response = self.create_source(
            default_point_generation_method_0=PointGen.Types.UNIFORM.value,
            default_point_generation_method_1='',
            default_point_generation_method_2='',
            default_point_generation_method_3='',
            default_point_generation_method_4='')

        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assert_field_error(
            response, 'default_point_generation_method',
            "Missing value(s): Number of cell rows, Number of cell columns")

    def test_pointgen_too_few_simple_points(self):
        self.client.force_login(self.user)

        response = self.create_source(
            default_point_generation_method_0=PointGen.Types.SIMPLE.value,
            default_point_generation_method_1=0,
            default_point_generation_method_2='',
            default_point_generation_method_3='',
            default_point_generation_method_4='')
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assert_field_error(
            response, 'default_point_generation_method',
            "Please use positive integers only.")

    def test_pointgen_too_few_rows_columns_per_cell(self):
        self.client.force_login(self.user)

        response = self.create_source(
            default_point_generation_method_0=PointGen.Types.STRATIFIED.value,
            default_point_generation_method_1='',
            default_point_generation_method_2=0,
            default_point_generation_method_3=1,
            default_point_generation_method_4=1)
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assert_field_error(
            response, 'default_point_generation_method',
            "Please use positive integers only.")

        response = self.create_source(
            default_point_generation_method_0=PointGen.Types.STRATIFIED.value,
            default_point_generation_method_1='',
            default_point_generation_method_2=1,
            default_point_generation_method_3=0,
            default_point_generation_method_4=1)
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assert_field_error(
            response, 'default_point_generation_method',
            "Please use positive integers only.")

        response = self.create_source(
            default_point_generation_method_0=PointGen.Types.STRATIFIED.value,
            default_point_generation_method_1='',
            default_point_generation_method_2=1,
            default_point_generation_method_3=1,
            default_point_generation_method_4=0)
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assert_field_error(
            response, 'default_point_generation_method',
            "Please use positive integers only.")

    @override_settings(MAX_POINTS_PER_IMAGE=1000)
    def test_pointgen_max_points_ok(self):
        self.client.force_login(self.user)

        # Match the point limit exactly
        response = self.create_source(
            default_point_generation_method_0=PointGen.Types.STRATIFIED.value,
            default_point_generation_method_1='',
            default_point_generation_method_2=10,
            default_point_generation_method_3=10,
            default_point_generation_method_4=10)

        new_source = Source.objects.latest('create_date')
        self.assertTemplateUsed('sources/source_main.html')
        self.assertEqual(response.context['source'], new_source)

        self.assertEqual(
            new_source.default_point_generation_method,
            PointGen(
                type='stratified', cell_rows=10,
                cell_columns=10, per_cell=10).db_value)

    @override_settings(MAX_POINTS_PER_IMAGE=1000)
    def test_pointgen_above_max_points(self):
        self.client.force_login(self.user)

        response = self.create_source(
            default_point_generation_method_0=PointGen.Types.STRATIFIED.value,
            default_point_generation_method_1='',
            default_point_generation_method_2=7,
            default_point_generation_method_3=11,
            default_point_generation_method_4=13)
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assert_field_error(
            response, 'default_point_generation_method',
            "You specified 1001 points total."
            " Please make it no more than 1000.")

    def test_latitude_longitude_required(self):
        self.client.force_login(self.user)

        response = self.create_source(latitude="")
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assert_field_error(
            response, 'latitude', "This field is required.")

        response = self.create_source(longitude="")
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assert_field_error(
            response, 'longitude', "This field is required.")

        self.assertEqual(Source.objects.all().count(), 0)


# Make these all different from what create_source() would use.
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
    feature_extractor_setting='vgg16_coralnet_ver1',
    latitude='5.789',
    longitude='-50',
)


class SourceEditTest(ClientTest):
    """
    Test the Edit Source page.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()

        # Create a source
        cls.source = cls.create_source(cls.user)
        cls.url = reverse('source_edit', args=[cls.source.pk])

    def test_access_page(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertStatusOK(response)
        self.assertTemplateUsed(response, 'sources/source_edit.html')

    def test_source_edit(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url, source_kwargs_2)

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
            self.source.feature_extractor_setting, 'vgg16_coralnet_ver1')
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


class SourceFormFieldAvailability(ClientTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.new_url = reverse('source_new')

        cls.source_with_backend = cls.create_source(cls.user)
        cls.with_backend_url = reverse(
            'source_edit', args=[cls.source_with_backend.pk])

        cls.source_without_backend = cls.create_source(cls.user)
        cls.source_without_backend.enable_robot_classifier = False
        cls.source_without_backend.save()
        cls.without_backend_url = reverse(
            'source_edit', args=[cls.source_without_backend.pk])

    def field_is_in_form(self, source_form_url, field_id):
        self.client.force_login(self.user)
        response = self.client.get(source_form_url)
        response_soup = BeautifulSoup(
            response.content, 'html.parser')
        field = response_soup.find(id=field_id)
        return field is not None

    def test_extractor_setting(self):
        self.assertTrue(self.field_is_in_form(
            self.new_url, 'id_feature_extractor_setting'))
        self.assertTrue(self.field_is_in_form(
            self.with_backend_url, 'id_feature_extractor_setting'))
        self.assertFalse(self.field_is_in_form(
            self.without_backend_url, 'id_feature_extractor_setting'))

    def test_confidence_threshold(self):
        self.assertFalse(self.field_is_in_form(
            self.new_url, 'id_confidence_threshold'))
        self.assertTrue(self.field_is_in_form(
            self.with_backend_url, 'id_confidence_threshold'))
        self.assertFalse(self.field_is_in_form(
            self.without_backend_url, 'id_confidence_threshold'))


class SourceEditBackendStatusTest(BaseTaskTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.url = reverse('source_edit', args=[cls.source.pk])

    def test_backend_reset_if_extractor_changed(self):
        edit_kwargs = source_kwargs_2.copy()
        edit_kwargs['feature_extractor_setting'] = 'vgg16_coralnet_ver1'
        self.client.force_login(self.user)

        # Edit source with changed extractor setting
        response = self.client.post(self.url, edit_kwargs, follow=True)
        self.assertTrue(
            Job.objects.filter(
                job_name='reset_backend_for_source').exists(),
            msg="Reset job should be scheduled")

        self.assertContains(
            response,
            "Source successfully edited. Classifier history will be cleared.",
            msg_prefix="Page should show the appropriate message")

    def test_backend_not_reset_if_extractor_same(self):
        edit_kwargs = source_kwargs_2.copy()
        edit_kwargs['feature_extractor_setting'] = 'efficientnet_b0_ver1'
        self.client.force_login(self.user)

        # Edit source with same extractor setting
        response = self.client.post(self.url, edit_kwargs, follow=True)
        self.assertFalse(
            Job.objects.filter(
                job_name='reset_backend_for_source').exists(),
            msg="Reset job should not be scheduled")

        self.assertContains(
            response, "Source successfully edited.",
            msg_prefix="Page should show the appropriate message")
        self.assertNotContains(
            response, "Classifier history will be cleared.",
            msg_prefix="Page should show the appropriate message")
