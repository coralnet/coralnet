from django.test.utils import override_settings
from django.urls import reverse
from django.utils import timezone

from annotations.model_utils import AnnotationAreaUtils
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
            min_x=10, max_x=90, min_y=10, max_y=90,
            point_generation_type=PointGen.Types.SIMPLE,
            simple_number_of_points=16, number_of_cell_rows='',
            number_of_cell_columns='', stratified_points_per_cell='',
            feature_extractor_setting='efficientnet_b0_ver1',
            latitude='-17.3776', longitude='25.1982')
        data.update(**kwargs)
        response = self.client.post(
            reverse('source_new'), data, follow=True)
        return response

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

        form = response.context['sourceForm']
        self.assertEqual(
            form['visibility'].value(), Source.VisibilityTypes.PUBLIC)
        self.assertEqual(form['key1'].value(), 'Aux1')
        self.assertEqual(form['key2'].value(), 'Aux2')
        self.assertEqual(form['key3'].value(), 'Aux3')
        self.assertEqual(form['key4'].value(), 'Aux4')
        self.assertEqual(form['key5'].value(), 'Aux5')
        self.assertEqual(
            form['feature_extractor_setting'].value(), 'efficientnet_b0_ver1')

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
            PointGen.args_to_db_format(
                point_generation_type=PointGen.Types.SIMPLE,
                simple_number_of_points=16,
            ),
        )
        self.assertEqual(
            new_source.image_annotation_area,
            AnnotationAreaUtils.percentages_to_db_format(
                min_x=10, max_x=90,
                min_y=10, max_y=90,
            ),
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
        self.assertContains(response, "This field is required.")

        # Should have no source created.
        self.assertEqual(Source.objects.all().count(), 0)

    def test_affiliation_required(self):
        self.client.force_login(self.user)

        response = self.create_source(affiliation="")
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assertContains(response, "This field is required.")

        self.assertEqual(Source.objects.all().count(), 0)

    def test_description_required(self):
        self.client.force_login(self.user)

        response = self.create_source(description="")
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assertContains(response, "This field is required.")

        self.assertEqual(Source.objects.all().count(), 0)

    def test_aux_names_required(self):
        self.client.force_login(self.user)

        response = self.create_source(key1="")
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assertContains(response, "This field is required.")

        response = self.create_source(key2="")
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assertContains(response, "This field is required.")

        response = self.create_source(key3="")
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assertContains(response, "This field is required.")

        response = self.create_source(key4="")
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assertContains(response, "This field is required.")

        response = self.create_source(key5="")
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assertContains(response, "This field is required.")

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
        self.assertDictEqual(
            response.context['sourceForm'].errors,
            dict(
                key1=[error_dont_use_temporal],
                key2=[error_dont_use_temporal],
                key3=[error_dont_use_temporal],
                key4=[error_dont_use_temporal],
                key5=[error_dont_use_temporal],
            )
        )
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
        self.assertDictEqual(
            response.context['sourceForm'].errors,
            dict(
                key1=[error_conflict],
                key2=[error_conflict],
                key3=[error_conflict],
            )
        )
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
        self.assertDictEqual(
            response.context['sourceForm'].errors,
            dict(
                key2=[error_conflict],
                key3=[error_conflict],
            )
        )
        # Should have no source created.
        self.assertEqual(Source.objects.all().count(), 0)

    def test_annotation_area_required(self):
        self.client.force_login(self.user)

        response = self.create_source(min_x="")
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assertContains(response, "This field is required.")

        response = self.create_source(max_x="")
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assertContains(response, "This field is required.")

        response = self.create_source(min_y="")
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assertContains(response, "This field is required.")

        response = self.create_source(max_y="")
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assertContains(response, "This field is required.")

        self.assertEqual(Source.objects.all().count(), 0)

    def test_annotation_area_min_exceeds_max(self):
        self.client.force_login(self.user)

        response = self.create_source(min_x="50", max_x="49")
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assertContains(
            response,
            "The right boundary x must be greater than the left boundary x.")

        response = self.create_source(min_y="100", max_y="0")
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assertContains(
            response,
            "The bottom boundary y must be greater than the top boundary y.")

    def test_pointgen_type_required(self):
        self.client.force_login(self.user)

        response = self.create_source(point_generation_type="")
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assertContains(response, "This field is required.")

    def test_pointgen_type_invalid(self):
        self.client.force_login(self.user)

        response = self.create_source(point_generation_type="straight line")
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assertContains(
            response,
            "Select a valid choice. straight line is not one of the available"
            " choices.")

    def test_pointgen_simple_success(self):
        self.client.force_login(self.user)

        response = self.create_source(
            point_generation_type=PointGen.Types.SIMPLE,
            simple_number_of_points=50, number_of_cell_rows='',
            number_of_cell_columns='', stratified_points_per_cell='')

        new_source = Source.objects.latest('create_date')
        self.assertTemplateUsed('sources/source_main.html')
        self.assertEqual(response.context['source'], new_source)

        self.assertEqual(
            new_source.default_point_generation_method,
            PointGen.args_to_db_format(
                point_generation_type=PointGen.Types.SIMPLE,
                simple_number_of_points=50))

    def test_pointgen_stratified_success(self):
        self.client.force_login(self.user)

        response = self.create_source(
            point_generation_type=PointGen.Types.STRATIFIED,
            simple_number_of_points='', number_of_cell_rows=4,
            number_of_cell_columns=5, stratified_points_per_cell=6)

        new_source = Source.objects.latest('create_date')
        self.assertTemplateUsed('sources/source_main.html')
        self.assertEqual(response.context['source'], new_source)

        self.assertEqual(
            new_source.default_point_generation_method,
            PointGen.args_to_db_format(
                point_generation_type=PointGen.Types.STRATIFIED,
                number_of_cell_rows=4, number_of_cell_columns=5,
                stratified_points_per_cell=6))

    def test_pointgen_uniform_grid_success(self):
        self.client.force_login(self.user)

        response = self.create_source(
            point_generation_type=PointGen.Types.UNIFORM,
            simple_number_of_points='', number_of_cell_rows=4,
            number_of_cell_columns=7, stratified_points_per_cell='')

        new_source = Source.objects.latest('create_date')
        self.assertTemplateUsed('sources/source_main.html')
        self.assertEqual(response.context['source'], new_source)

        self.assertEqual(
            new_source.default_point_generation_method,
            PointGen.args_to_db_format(
                point_generation_type=PointGen.Types.UNIFORM,
                number_of_cell_rows=4, number_of_cell_columns=7))

    def test_pointgen_filling_extra_fields_ok(self):
        self.client.force_login(self.user)

        # Filling more fields than necessary here, even with values that
        # would be invalid
        response = self.create_source(
            point_generation_type=PointGen.Types.UNIFORM,
            simple_number_of_points=-2, number_of_cell_rows=4,
            number_of_cell_columns=7, stratified_points_per_cell=10000)

        new_source = Source.objects.latest('create_date')
        self.assertTemplateUsed('sources/source_main.html')
        self.assertEqual(response.context['source'], new_source)

        self.assertEqual(
            new_source.default_point_generation_method,
            PointGen.args_to_db_format(
                point_generation_type=PointGen.Types.UNIFORM,
                number_of_cell_rows=4, number_of_cell_columns=7))

    def test_pointgen_simple_missing_required_fields(self):
        self.client.force_login(self.user)

        response = self.create_source(
            point_generation_type=PointGen.Types.SIMPLE,
            simple_number_of_points='', number_of_cell_rows='',
            number_of_cell_columns='', stratified_points_per_cell='')

        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assertDictEqual(
            response.context['pointGenForm'].errors,
            dict(
                simple_number_of_points=["This field is required."],
            )
        )

    def test_pointgen_stratified_missing_required_fields(self):
        self.client.force_login(self.user)

        response = self.create_source(
            point_generation_type=PointGen.Types.STRATIFIED,
            simple_number_of_points='', number_of_cell_rows='',
            number_of_cell_columns='', stratified_points_per_cell='')

        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assertDictEqual(
            response.context['pointGenForm'].errors,
            dict(
                number_of_cell_rows=["This field is required."],
                number_of_cell_columns=["This field is required."],
                stratified_points_per_cell=["This field is required."],
            )
        )

    def test_pointgen_uniform_missing_required_fields(self):
        self.client.force_login(self.user)

        response = self.create_source(
            point_generation_type=PointGen.Types.UNIFORM,
            simple_number_of_points='', number_of_cell_rows='',
            number_of_cell_columns='', stratified_points_per_cell='')

        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assertDictEqual(
            response.context['pointGenForm'].errors,
            dict(
                number_of_cell_rows=["This field is required."],
                number_of_cell_columns=["This field is required."],
            )
        )

    def test_pointgen_too_few_simple_points(self):
        self.client.force_login(self.user)

        response = self.create_source(
            point_generation_type=PointGen.Types.SIMPLE,
            simple_number_of_points=0, number_of_cell_rows='',
            number_of_cell_columns='', stratified_points_per_cell='')
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assertDictEqual(
            response.context['pointGenForm'].errors,
            dict(
                simple_number_of_points=[
                    "Ensure this value is greater than or equal to 1."],
            )
        )

    def test_pointgen_too_few_rows_columns_per_cell(self):
        self.client.force_login(self.user)

        response = self.create_source(
            point_generation_type=PointGen.Types.STRATIFIED,
            simple_number_of_points='', number_of_cell_rows=0,
            number_of_cell_columns=0, stratified_points_per_cell=0)
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assertDictEqual(
            response.context['pointGenForm'].errors,
            dict(
                number_of_cell_rows=[
                    "Ensure this value is greater than or equal to 1."],
                number_of_cell_columns=[
                    "Ensure this value is greater than or equal to 1."],
                stratified_points_per_cell=[
                    "Ensure this value is greater than or equal to 1."],
            )
        )

    @override_settings(MAX_POINTS_PER_IMAGE=1000)
    def test_pointgen_max_points_ok(self):
        self.client.force_login(self.user)

        # Match the point limit exactly
        response = self.create_source(
            point_generation_type=PointGen.Types.STRATIFIED,
            simple_number_of_points='', number_of_cell_rows=10,
            number_of_cell_columns=10, stratified_points_per_cell=10)

        new_source = Source.objects.latest('create_date')
        self.assertTemplateUsed('sources/source_main.html')
        self.assertEqual(response.context['source'], new_source)

        self.assertEqual(
            new_source.default_point_generation_method,
            PointGen.args_to_db_format(
                point_generation_type=PointGen.Types.STRATIFIED,
                number_of_cell_rows=10, number_of_cell_columns=10,
                stratified_points_per_cell=10))

    @override_settings(MAX_POINTS_PER_IMAGE=1000)
    def test_pointgen_above_max_points(self):
        self.client.force_login(self.user)

        response = self.create_source(
            point_generation_type=PointGen.Types.STRATIFIED,
            simple_number_of_points='', number_of_cell_rows=7,
            number_of_cell_columns=11, stratified_points_per_cell=13)
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assertDictEqual(
            response.context['pointGenForm'].errors,
            dict(
                __all__=[
                    "You specified 1001 points total."
                    " Please make it no more than 1000."],
            )
        )

    def test_latitude_longitude_required(self):
        self.client.force_login(self.user)

        response = self.create_source(latitude="")
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assertContains(response, "This field is required.")

        response = self.create_source(longitude="")
        self.assertTemplateUsed(response, 'sources/source_new.html')
        self.assertContains(response, "This field is required.")

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
    min_x=5,
    max_x=95,
    min_y=5,
    max_y=95,
    point_generation_type=PointGen.Types.STRATIFIED,
    number_of_cell_rows=4,
    number_of_cell_columns=6,
    stratified_points_per_cell=3,
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
            AnnotationAreaUtils.percentages_to_db_format(
                min_x=5, max_x=95, min_y=5, max_y=95,
            )
        )
        self.assertEqual(
            self.source.default_point_generation_method,
            PointGen.args_to_db_format(
                point_generation_type=PointGen.Types.STRATIFIED,
                number_of_cell_rows=4,
                number_of_cell_columns=6,
                stratified_points_per_cell=3,
            )
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
