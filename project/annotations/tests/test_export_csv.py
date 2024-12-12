import datetime

from django.core.files.base import ContentFile
from django.test import override_settings
from django.urls import reverse

from annotations.models import Annotation
from export.tests.utils import BaseExportTest
from lib.tests.utils import BasePermissionTest
from upload.tests.utils import UploadAnnotationsCsvTestMixin


class PermissionTest(BasePermissionTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, cls.labels)

    def test_annotations(self):
        url = reverse('export_annotations', args=[self.source.pk])

        self.source_to_private()
        self.assertPermissionLevel(
            url, self.SOURCE_VIEW, post_data={}, content_type='text/csv')
        self.source_to_public()
        self.assertPermissionLevel(
            url, self.SIGNED_IN, post_data={}, content_type='text/csv',
            deny_type=self.REQUIRE_LOGIN)


class ImageSetTest(BaseExportTest):
    """Test annotations export to CSV for different kinds of image subsets."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user,
            # Uniform grid gives us consistent point locations.
            default_point_generation_method=dict(
                type='uniform', cell_rows=1, cell_columns=2),
        )
        cls.labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, cls.labels)

    def test_all_images_single(self):
        """Export for 1 out of 1 images."""
        self.img1 = self.upload_image(
            self.user, self.source,
            dict(filename='1.jpg', width=400, height=300))
        self.add_annotations(self.user, self.img1, {1: 'A', 2: 'B'})

        post_data = self.default_search_params.copy()
        response = self.export_annotations(post_data)

        expected_lines = [
            'Name,Row,Column,Label',
            '1.jpg,149,99,A',
            '1.jpg,149,299,B',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_all_images_multiple(self):
        """Export for 3 out of 3 images."""
        self.img1 = self.upload_image(
            self.user, self.source,
            dict(filename='1.jpg', width=400, height=300))
        self.img2 = self.upload_image(
            self.user, self.source,
            dict(filename='2.jpg', width=400, height=400))
        self.img3 = self.upload_image(
            self.user, self.source,
            dict(filename='3.jpg', width=400, height=200))
        self.add_annotations(self.user, self.img1, {1: 'A', 2: 'B'})
        self.add_annotations(self.user, self.img2, {1: 'B', 2: 'A'})
        self.add_annotations(self.user, self.img3, {1: 'B', 2: 'B'})

        post_data = self.default_search_params.copy()
        response = self.export_annotations(post_data)

        expected_lines = [
            'Name,Row,Column,Label',
            '1.jpg,149,99,A',
            '1.jpg,149,299,B',
            '2.jpg,199,99,B',
            '2.jpg,199,299,A',
            '3.jpg,99,99,B',
            '3.jpg,99,299,B',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_image_subset_by_metadata(self):
        """Export for some, but not all, images."""
        self.img1 = self.upload_image(
            self.user, self.source,
            dict(filename='1.jpg', width=400, height=300))
        self.img2 = self.upload_image(
            self.user, self.source,
            dict(filename='2.jpg', width=400, height=400))
        self.img3 = self.upload_image(
            self.user, self.source,
            dict(filename='3.jpg', width=400, height=200))
        self.add_annotations(self.user, self.img1, {1: 'A', 2: 'B'})
        self.add_annotations(self.user, self.img2, {1: 'B', 2: 'A'})
        self.add_annotations(self.user, self.img3, {1: 'B', 2: 'B'})
        self.img1.metadata.aux1 = 'X'
        self.img1.metadata.save()
        self.img2.metadata.aux1 = 'Y'
        self.img2.metadata.save()
        self.img3.metadata.aux1 = 'X'
        self.img3.metadata.save()

        post_data = self.default_search_params.copy()
        post_data['aux1'] = 'X'
        response = self.export_annotations(post_data)

        expected_lines = [
            'Name,Row,Column,Label',
            '1.jpg,149,99,A',
            '1.jpg,149,299,B',
            '3.jpg,99,99,B',
            '3.jpg,99,299,B',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_image_subset_by_annotation_status(self):
        """Export for some, but not all, images. Different search criteria.
        Just a sanity check to ensure the image filtering is as complete
        as it should be."""
        self.img1 = self.upload_image(
            self.user, self.source,
            dict(filename='1.jpg', width=400, height=300))
        self.img2 = self.upload_image(
            self.user, self.source,
            dict(filename='2.jpg', width=400, height=400))
        self.img3 = self.upload_image(
            self.user, self.source,
            dict(filename='3.jpg', width=400, height=200))
        robot = self.create_robot(self.source)
        self.add_robot_annotations(robot, self.img1, {1: 'A', 2: 'A'})
        self.add_robot_annotations(robot, self.img2, {1: 'A', 2: 'A'})
        self.add_robot_annotations(robot, self.img3, {1: 'A', 2: 'A'})
        # Only images 2 and 3 become confirmed
        self.add_annotations(self.user, self.img2, {1: 'B', 2: 'A'})
        self.add_annotations(self.user, self.img3, {1: 'B', 2: 'B'})

        post_data = self.default_search_params.copy()
        post_data['annotation_status'] = 'confirmed'
        response = self.export_annotations(post_data)

        expected_lines = [
            'Name,Row,Column,Label',
            '2.jpg,199,99,B',
            '2.jpg,199,299,A',
            '3.jpg,99,99,B',
            '3.jpg,99,299,B',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_image_empty_set(self):
        """Export for 0 images."""
        self.img1 = self.upload_image(
            self.user, self.source,
            dict(filename='1.jpg', width=400, height=300))
        self.add_annotations(self.user, self.img1, {1: 'A', 2: 'B'})

        post_data = self.default_search_params.copy()
        post_data['image_name'] = '5.jpg'
        response = self.export_annotations(post_data)

        expected_lines = [
            'Name,Row,Column,Label',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_invalid_image_set_params(self):
        self.upload_image(self.user, self.source)

        post_data = self.default_search_params.copy()
        post_data['photo_date_0'] = 'abc'
        response = self.export_annotations(post_data)

        # Display an error in HTML instead of serving CSV.
        self.assertTrue(response['content-type'].startswith('text/html'))
        self.assertContains(response, "Image-search parameters were invalid.")

    def test_dont_get_other_sources_images(self):
        """Don't export for other sources' images."""
        self.img1 = self.upload_image(
            self.user, self.source,
            dict(filename='1.jpg', width=400, height=300))
        self.add_annotations(self.user, self.img1, {1: 'A', 2: 'B'})

        source2 = self.create_source(
            self.user,
            default_point_generation_method=dict(
                type='uniform', cell_rows=1, cell_columns=2))
        self.create_labelset(self.user, source2, self.labels)
        img2 = self.upload_image(self.user, source2, dict(filename='2.jpg'))
        self.add_annotations(self.user, img2, {1: 'A', 2: 'B'})

        post_data = self.default_search_params.copy()
        response = self.export_annotations(post_data)

        # Should have image 1, but not 2
        expected_lines = [
            'Name,Row,Column,Label',
            '1.jpg,149,99,A',
            '1.jpg,149,299,B',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)


class AnnotationStatusTest(BaseExportTest):
    """Test annotations export to CSV for images of various annotation
    statuses."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user,
            default_point_generation_method=dict(
                type='uniform', cell_rows=1, cell_columns=2),
        )
        labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, labels)

        cls.img1 = cls.upload_image(
            cls.user, cls.source,
            dict(filename='1.jpg', width=400, height=300))

    def test_not_annotated(self):
        response = self.export_annotations(self.default_search_params)

        expected_lines = [
            'Name,Row,Column,Label',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_partially_annotated(self):
        self.add_annotations(self.user, self.img1, {1: 'B'})
        response = self.export_annotations(self.default_search_params)

        expected_lines = [
            'Name,Row,Column,Label',
            '1.jpg,149,99,B',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_fully_annotated(self):
        self.add_annotations(self.user, self.img1, {1: 'B', 2: 'A'})
        response = self.export_annotations(self.default_search_params)

        expected_lines = [
            'Name,Row,Column,Label',
            '1.jpg,149,99,B',
            '1.jpg,149,299,A',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_machine_annotated(self):
        robot = self.create_robot(self.source)
        self.add_robot_annotations(robot, self.img1, {1: 'B', 2: 'A'})
        response = self.export_annotations(self.default_search_params)

        expected_lines = [
            'Name,Row,Column,Label',
            '1.jpg,149,99,B',
            '1.jpg,149,299,A',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_part_machine_part_manual(self):
        robot = self.create_robot(self.source)
        self.add_robot_annotations(robot, self.img1, {1: 'B', 2: 'A'})
        self.add_annotations(self.user, self.img1, {2: 'A'})
        response = self.export_annotations(self.default_search_params)

        expected_lines = [
            'Name,Row,Column,Label',
            '1.jpg,149,99,B',
            '1.jpg,149,299,A',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)


class AnnotatorInfoColumnsTest(BaseExportTest, UploadAnnotationsCsvTestMixin):
    """Test the optional annotation info columns."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user,
            default_point_generation_method=dict(
                type='uniform', cell_rows=1, cell_columns=1),
        )
        labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, labels)

        cls.img1 = cls.upload_image(
            cls.user, cls.source,
            dict(filename='1.jpg', width=400, height=300))

    def test_user_annotation(self):
        self.add_annotations(self.user, self.img1, {1: 'B'})
        post_data = self.default_search_params.copy()
        post_data['optional_columns'] = ['annotator_info']
        response = self.export_annotations(post_data)

        annotation_date = \
            Annotation.objects.get(image=self.img1).annotation_date
        date_str = annotation_date.strftime('%Y-%m-%d %H:%M:%S+00:00')

        expected_lines = [
            'Name,Row,Column,Label,Annotator,Date annotated',
            '1.jpg,149,199,B,{username},{date}'.format(
                username=self.user.username, date=date_str),
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_imported_annotation(self):
        # Import an annotation
        rows = [
            ['Name', 'Row', 'Column', 'Label'],
            ['1.jpg', 50, 70, 'B'],
        ]
        csv_file = self.make_annotations_file('A.csv', rows)
        self.preview_annotations(
            self.user, self.source, csv_file)
        self.upload_annotations(self.user, self.source)

        post_data = self.default_search_params.copy()
        post_data['optional_columns'] = ['annotator_info']
        response = self.export_annotations(post_data)

        annotation_date = \
            Annotation.objects.get(image=self.img1).annotation_date
        date_str = annotation_date.strftime('%Y-%m-%d %H:%M:%S+00:00')

        expected_lines = [
            'Name,Row,Column,Label,Annotator,Date annotated',
            '1.jpg,50,70,B,Imported,{date}'.format(date=date_str),
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_machine_annotation(self):
        robot = self.create_robot(self.source)
        self.add_robot_annotations(robot, self.img1, {1: 'B'})
        post_data = self.default_search_params.copy()
        post_data['optional_columns'] = ['annotator_info']
        response = self.export_annotations(post_data)

        annotation_date = \
            Annotation.objects.get(image=self.img1).annotation_date
        date_str = annotation_date.strftime('%Y-%m-%d %H:%M:%S+00:00')

        expected_lines = [
            'Name,Row,Column,Label,Annotator,Date annotated',
            '1.jpg,149,199,B,robot,{date}'.format(date=date_str),
        ]
        self.assert_csv_content_equal(response.content, expected_lines)


class MachineSuggestionColumnsTest(BaseExportTest):
    """Test the optional machine suggestion columns."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user,
            default_point_generation_method=dict(
                type='uniform', cell_rows=1, cell_columns=1),
        )
        labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, labels)

        cls.img1 = cls.upload_image(
            cls.user, cls.source,
            dict(filename='1.jpg', width=400, height=300))

    @override_settings(NBR_SCORES_PER_ANNOTATION=2)
    def test_blank(self):
        self.add_annotations(self.user, self.img1, {1: 'B'})
        post_data = self.default_search_params.copy()
        post_data['optional_columns'] = ['machine_suggestions']
        response = self.export_annotations(post_data)

        expected_lines = [
            'Name,Row,Column,Label'
            ',Machine suggestion 1,Machine confidence 1'
            ',Machine suggestion 2,Machine confidence 2',
            '1.jpg,149,199,B,,,,',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    @override_settings(NBR_SCORES_PER_ANNOTATION=2)
    def test_all_suggestions_filled(self):
        robot = self.create_robot(self.source)
        # Normally we don't make assumptions on how add_robot_annotations()
        # assigns confidences after the first one, but since we only have 2
        # labels in the labelset, it should be safe to assume confidences of
        # 60 and 40 if we pass a top score of 60.
        self.add_robot_annotations(robot, self.img1, {1: ('B', 60)})

        post_data = self.default_search_params.copy()
        post_data['optional_columns'] = ['machine_suggestions']
        response = self.export_annotations(post_data)

        expected_lines = [
            'Name,Row,Column,Label'
            ',Machine suggestion 1,Machine confidence 1'
            ',Machine suggestion 2,Machine confidence 2',
            '1.jpg,149,199,B,B,60,A,40',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    @override_settings(NBR_SCORES_PER_ANNOTATION=3)
    def test_some_suggestions_filled(self):
        robot = self.create_robot(self.source)
        # As before, we're assuming this gets confidences of 60 and 40.
        self.add_robot_annotations(robot, self.img1, {1: ('B', 60)})

        post_data = self.default_search_params.copy()
        post_data['optional_columns'] = ['machine_suggestions']
        response = self.export_annotations(post_data)

        expected_lines = [
            'Name,Row,Column,Label'
            ',Machine suggestion 1,Machine confidence 1'
            ',Machine suggestion 2,Machine confidence 2'
            ',Machine suggestion 3,Machine confidence 3',
            '1.jpg,149,199,B,B,60,A,40,,',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)


class MetadataAuxColumnsTest(BaseExportTest):
    """Test the optional aux. metadata columns."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user,
            default_point_generation_method=dict(
                type='uniform', cell_rows=1, cell_columns=1),
        )
        labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, labels)

        cls.img1 = cls.upload_image(
            cls.user, cls.source,
            dict(filename='1.jpg', width=400, height=300))

    def test_blank(self):
        self.add_annotations(self.user, self.img1, {1: 'B'})
        post_data = self.default_search_params.copy()
        post_data['optional_columns'] = ['metadata_date_aux']
        response = self.export_annotations(post_data)

        expected_lines = [
            'Name,Date,Aux1,Aux2,Aux3,Aux4,Aux5,Row,Column,Label',
            '1.jpg,,,,,,,149,199,B',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_filled(self):
        self.img1.metadata.photo_date = datetime.date(2001, 2, 3)
        self.img1.metadata.aux1 = "Site A"
        self.img1.metadata.aux2 = "Transect 1-2"
        self.img1.metadata.aux3 = "Quadrant 5"
        self.img1.metadata.save()
        self.add_annotations(self.user, self.img1, {1: 'B'})

        post_data = self.default_search_params.copy()
        post_data['optional_columns'] = ['metadata_date_aux']
        response = self.export_annotations(post_data)

        expected_lines = [
            'Name,Date,Aux1,Aux2,Aux3,Aux4,Aux5,Row,Column,Label',
            '1.jpg,2001-02-03,Site A,Transect 1-2,Quadrant 5,,,149,199,B',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_named_aux_fields(self):
        self.source.key1 = "Site"
        self.source.key2 = "Transect"
        self.source.key3 = "Quadrant"
        self.source.save()
        self.img1.metadata.photo_date = datetime.date(2001, 2, 3)
        self.img1.metadata.aux1 = "Site A"
        self.img1.metadata.aux2 = "Transect 1-2"
        self.img1.metadata.aux3 = "Quadrant 5"
        self.img1.metadata.save()
        self.add_annotations(self.user, self.img1, {1: 'B'})

        post_data = self.default_search_params.copy()
        post_data['optional_columns'] = ['metadata_date_aux']
        response = self.export_annotations(post_data)

        expected_lines = [
            'Name,Date,Site,Transect,Quadrant,Aux4,Aux5,Row,Column,Label',
            '1.jpg,2001-02-03,Site A,Transect 1-2,Quadrant 5,,,149,199,B',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)


class MetadataOtherColumnsTest(BaseExportTest):
    """Test the optional other metadata columns."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user,
            default_point_generation_method=dict(
                type='uniform', cell_rows=1, cell_columns=1),
        )
        labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, labels)

        cls.img1 = cls.upload_image(
            cls.user, cls.source,
            dict(filename='1.jpg', width=400, height=300))

    def test_blank(self):
        self.add_annotations(self.user, self.img1, {1: 'B'})
        post_data = self.default_search_params.copy()
        post_data['optional_columns'] = ['metadata_other']
        response = self.export_annotations(post_data)

        expected_lines = [
            'Name,Height (cm),Latitude,Longitude,Depth,Camera,Photographer'
            ',Water quality,Strobes,Framing gear used,White balance card'
            ',Comments,Row,Column,Label',
            '1.jpg,,,,,,,,,,,,149,199,B',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_filled(self):
        self.img1.metadata.height_in_cm = 40
        self.img1.metadata.latitude = "5.789"
        self.img1.metadata.longitude = "-50"
        self.img1.metadata.depth = "10m"
        self.img1.metadata.camera = "Nikon"
        self.img1.metadata.photographer = "John Doe"
        self.img1.metadata.water_quality = "Clear"
        self.img1.metadata.strobes = "White A"
        self.img1.metadata.framing = "Framing set C"
        self.img1.metadata.balance = "Card B"
        self.img1.metadata.comments = "Here are\nsome comments."
        self.img1.metadata.save()
        self.add_annotations(self.user, self.img1, {1: 'B'})

        post_data = self.default_search_params.copy()
        post_data['optional_columns'] = ['metadata_other']
        response = self.export_annotations(post_data)

        expected_lines = [
            'Name,Height (cm),Latitude,Longitude,Depth,Camera,Photographer'
            ',Water quality,Strobes,Framing gear used,White balance card'
            ',Comments,Row,Column,Label',
            '1.jpg,40,5.789,-50,10m,Nikon,John Doe'
            ',Clear,White A,Framing set C,Card B'
            ',"Here are\nsome comments.",149,199,B',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)


class MoreOptionalColumnsCasesTest(BaseExportTest):
    """Test combinations of optional column sets, and invalid columns."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user,
            default_point_generation_method=dict(
                type='uniform', cell_rows=1, cell_columns=1),
        )
        labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, labels)

        cls.img1 = cls.upload_image(
            cls.user, cls.source,
            dict(filename='1.jpg', width=400, height=300))

    def test_both_metadata_column_sets(self):
        self.source.key1 = "Site"
        self.source.key2 = "Transect"
        self.source.key3 = "Quadrant"
        self.source.save()
        self.img1.metadata.photo_date = datetime.date(2001, 2, 3)
        self.img1.metadata.aux1 = "Site A"
        self.img1.metadata.aux2 = "Transect 1-2"
        self.img1.metadata.aux3 = "Quadrant 5"
        self.img1.metadata.height_in_cm = 40
        self.img1.metadata.latitude = "5.789"
        self.img1.metadata.longitude = "-50"
        self.img1.metadata.depth = "10m"
        self.img1.metadata.camera = "Nikon"
        self.img1.metadata.photographer = "John Doe"
        self.img1.metadata.water_quality = "Clear"
        self.img1.metadata.strobes = "White A"
        self.img1.metadata.framing = "Framing set C"
        self.img1.metadata.balance = "Card B"
        self.img1.metadata.comments = "Here are\nsome comments."
        self.img1.metadata.save()
        self.add_annotations(self.user, self.img1, {1: 'B'})

        post_data = self.default_search_params.copy()
        post_data['optional_columns'] = ['metadata_date_aux', 'metadata_other']
        response = self.export_annotations(post_data)

        expected_lines = [
            'Name,Date,Site,Transect,Quadrant,Aux4,Aux5'
            ',Height (cm),Latitude,Longitude,Depth,Camera,Photographer'
            ',Water quality,Strobes,Framing gear used,White balance card'
            ',Comments,Row,Column,Label',
            '1.jpg,2001-02-03,Site A,Transect 1-2,Quadrant 5'
            ',,,40,5.789,-50,10m,Nikon,John Doe'
            ',Clear,White A,Framing set C,Card B'
            ',"Here are\nsome comments.",149,199,B',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_another_combination_of_two_sets(self):
        self.source.key1 = "Site"
        self.source.key2 = "Transect"
        self.source.key3 = "Quadrant"
        self.source.save()
        self.img1.metadata.photo_date = datetime.date(2001, 2, 3)
        self.img1.metadata.aux1 = "Site A"
        self.img1.metadata.aux2 = "Transect 1-2"
        self.img1.metadata.aux3 = "Quadrant 5"
        self.img1.metadata.save()
        self.add_annotations(self.user, self.img1, {1: 'B'})

        post_data = self.default_search_params.copy()
        post_data['optional_columns'] = ['annotator_info', 'metadata_date_aux']
        response = self.export_annotations(post_data)

        annotation_date = \
            Annotation.objects.get(image=self.img1).annotation_date
        date_str = annotation_date.strftime('%Y-%m-%d %H:%M:%S+00:00')

        expected_lines = [
            'Name,Date,Site,Transect,Quadrant,Aux4,Aux5'
            ',Row,Column,Label,Annotator,Date annotated',
            '1.jpg,2001-02-03,Site A,Transect 1-2,Quadrant 5,,'
            ',149,199,B,{username},{date}'.format(
                username=self.user.username, date=date_str),
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    @override_settings(NBR_SCORES_PER_ANNOTATION=2)
    def test_all_sets(self):
        self.source.key1 = "Site"
        self.source.key2 = "Transect"
        self.source.key3 = "Quadrant"
        self.source.save()
        self.img1.metadata.photo_date = datetime.date(2001, 2, 3)
        self.img1.metadata.aux1 = "Site A"
        self.img1.metadata.aux2 = "Transect 1-2"
        self.img1.metadata.aux3 = "Quadrant 5"
        self.img1.metadata.height_in_cm = 40
        self.img1.metadata.latitude = "5.789"
        self.img1.metadata.longitude = "-50"
        self.img1.metadata.depth = "10m"
        self.img1.metadata.camera = "Nikon"
        self.img1.metadata.photographer = "John Doe"
        self.img1.metadata.water_quality = "Clear"
        self.img1.metadata.strobes = "White A"
        self.img1.metadata.framing = "Framing set C"
        self.img1.metadata.balance = "Card B"
        self.img1.metadata.comments = "Here are\nsome comments."
        self.img1.metadata.save()

        robot = self.create_robot(self.source)
        self.add_robot_annotations(robot, self.img1, {1: ('B', 60)})
        self.add_annotations(self.user, self.img1, {1: 'B'})

        post_data = self.default_search_params.copy()
        post_data['optional_columns'] = [
            'annotator_info', 'machine_suggestions',
            'metadata_date_aux', 'metadata_other']
        response = self.export_annotations(post_data)

        annotation_date = \
            Annotation.objects.get(image=self.img1).annotation_date
        date_str = annotation_date.strftime('%Y-%m-%d %H:%M:%S+00:00')

        expected_lines = [
            'Name,Date,Site,Transect,Quadrant,Aux4,Aux5'
            ',Height (cm),Latitude,Longitude,Depth,Camera,Photographer'
            ',Water quality,Strobes,Framing gear used,White balance card'
            ',Comments,Row,Column,Label'
            ',Annotator,Date annotated'
            ',Machine suggestion 1,Machine confidence 1'
            ',Machine suggestion 2,Machine confidence 2',
            '1.jpg,2001-02-03,Site A,Transect 1-2,Quadrant 5,,'
            ',40,5.789,-50,10m,Nikon,John Doe'
            ',Clear,White A,Framing set C,Card B'
            ',"Here are\nsome comments.",149,199,B'
            ',{username},{date},B,60,A,40'.format(
                username=self.user.username, date=date_str),
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_invalid_column_name(self):
        self.add_annotations(self.user, self.img1, {1: 'B'})

        post_data = self.default_search_params.copy()
        post_data['optional_columns'] = ['jpg_files']
        response = self.export_annotations(post_data)

        # Display an error in HTML instead of serving CSV.
        self.assertTrue(response['content-type'].startswith('text/html'))
        self.assertContains(
            response,
            "Select a valid choice."
            " jpg_files is not one of the available choices.")


class UnicodeTest(BaseExportTest):
    """Test that non-ASCII characters don't cause problems."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user,
            default_point_generation_method=dict(
                type='uniform', cell_rows=1, cell_columns=1),
        )

        labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, labels)
        # Unicode custom label code
        local_label = cls.source.labelset.locallabel_set.get(code='B')
        local_label.code = 'い'
        local_label.save()

        cls.img1 = cls.upload_image(
            cls.user, cls.source,
            dict(filename='あ.jpg', width=400, height=300))

    def test(self):
        self.add_annotations(self.user, self.img1, {1: 'い'})

        post_data = self.default_search_params.copy()
        response = self.export_annotations(post_data)

        expected_lines = [
            'Name,Row,Column,Label',
            'あ.jpg,149,199,い',
        ]
        self.assert_csv_content_equal(
            response.content, expected_lines)


class UploadAndExportSameDataTest(BaseExportTest):
    """Test that we can upload a CSV and then export the exact same CSV."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user,
            default_point_generation_method=dict(
                type='uniform', cell_rows=1, cell_columns=1),
        )
        labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, labels)

    def test(self):
        self.img1 = self.upload_image(
            self.user, self.source,
            dict(filename='1.jpg', width=400, height=300))

        # Upload annotations
        content = ''
        csv_lines = [
            'Name,Row,Column,Label',
            '1.jpg,149,199,A',
        ]
        for line in csv_lines:
            content += (line + '\n')
        csv_file = ContentFile(content, name='annotations.csv')

        self.client.force_login(self.user)
        self.client.post(
            reverse('upload_annotations_csv_preview_ajax',
                    args=[self.source.pk]),
            {'csv_file': csv_file},
        )
        self.client.post(
            reverse('upload_annotations_csv_confirm_ajax',
                    args=[self.source.pk]),
        )

        # Export annotations
        post_data = self.default_search_params.copy()
        response = self.export_annotations(post_data)

        self.assert_csv_content_equal(response.content, csv_lines)


class QueriesPerPointTest(BaseExportTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user,
            # 100 points per image
            default_point_generation_method=dict(
                type='uniform', cell_rows=10, cell_columns=10))
        labels = cls.create_labels(
            # At least enough labels to fill in 5 suggestions
            cls.user, ['A', 'B', 'C', 'D', 'E', 'F', 'G'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, labels)

        cls.img1 = cls.upload_image(
            cls.user, cls.source,
            dict(filename='1.jpg', width=400, height=300))
        cls.img2 = cls.upload_image(
            cls.user, cls.source,
            dict(filename='2.jpg', width=400, height=300))
        cls.img3 = cls.upload_image(
            cls.user, cls.source,
            dict(filename='3.jpg', width=400, height=300))

    def test_default_columns(self):
        self.add_annotations(self.user, self.img1)
        self.add_annotations(self.user, self.img2)
        self.add_annotations(self.user, self.img3)

        # Number of queries should be less than the point count.
        with self.assert_queries_less_than(3*100):
            response = self.export_annotations(self.default_search_params)

        csv_content = response.content.decode()
        self.assertEqual(
            csv_content.count('\n'), 301,
            msg="Sanity check: CSV should have one line per point plus"
                " header and total rows = 302 lines, 301 newlines")

    def test_with_all_optional_columns(self):
        # Machine suggestions and some confirmed annotations
        robot = self.create_robot(self.source)
        self.add_robot_annotations(robot, self.img1)
        self.add_annotations(self.user, self.img1)
        self.add_robot_annotations(robot, self.img2)
        self.add_annotations(self.user, self.img2)
        self.add_robot_annotations(robot, self.img3)

        # Image metadata
        self.img1.metadata.photo_date = datetime.date(2001, 2, 3)
        self.img1.metadata.aux1 = "Site A"
        self.img1.metadata.camera = "Canon"
        self.img1.metadata.save()
        self.img2.metadata.photo_date = datetime.date(2001, 2, 3)
        self.img2.metadata.aux1 = "Site A"
        self.img2.metadata.camera = "Canon"
        self.img2.metadata.save()
        self.img3.metadata.photo_date = datetime.date(2003, 4, 5)
        self.img3.metadata.aux1 = "Site B"
        self.img3.metadata.camera = "Nikon"
        self.img3.metadata.save()

        post_data = self.default_search_params.copy()
        post_data['optional_columns'] = [
            'annotator_info', 'machine_suggestions',
            'metadata_date_aux', 'metadata_other']

        # Number of queries should be less than the point count.
        with self.assert_queries_less_than(3*100):
            response = self.export_annotations(post_data)

        csv_content = response.content.decode()
        self.assertEqual(
            csv_content.count('\n'), 301,
            msg="Sanity check: CSV should have one line per point plus"
                " header and total rows = 302 lines, 301 newlines")
        self.assertIn(
            "Machine suggestion 5", csv_content,
            msg="Sanity check: CSV should have machine suggestion columns")
        self.assertIn(
            "Nikon", csv_content,
            msg="Sanity check: CSV should have some expected metadata")


class QueriesPerImageTest(BaseExportTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user,
            # 1 point per image
            default_point_generation_method=dict(
                type='uniform', cell_rows=1, cell_columns=1))
        labels = cls.create_labels(
            cls.user,
            # A larger labelset could make the queries per image go up if
            # handled naively.
            ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J'],
            'GroupA',
        )
        cls.create_labelset(cls.user, cls.source, labels)

        cls.images = []
        for n in range(1, 40+1):
            cls.images.append(cls.upload_image(
                cls.user, cls.source,
                dict(filename=f'{n}.jpg', width=50, height=50),
            ))

    def test_default_columns(self):
        for image in self.images:
            self.add_annotations(self.user, image)

        # Number of queries should be linear in image count, but with
        # not too large of a constant factor.
        with self.assert_queries_less_than(40*5):
            response = self.export_annotations(self.default_search_params)

        csv_content = response.content.decode()
        self.assertEqual(
            csv_content.count('\n'), 41,
            msg="Sanity check: CSV should have one line per point plus"
                " header and total rows = 42 lines, 41 newlines")

    def test_with_all_optional_columns(self):
        robot = self.create_robot(self.source)
        for image in self.images:
            # Machine suggestions and confirmed annotations
            self.add_robot_annotations(robot, image)
            self.add_annotations(self.user, image)
            # Image metadata
            image.metadata.photo_date = datetime.date(2001, 2, 3)
            image.metadata.aux1 = "Site A"
            image.metadata.camera = "Canon"
            image.metadata.save()

        post_data = self.default_search_params.copy()
        post_data['optional_columns'] = [
            'annotator_info', 'machine_suggestions',
            'metadata_date_aux', 'metadata_other']

        with self.assert_queries_less_than(40*5):
            response = self.export_annotations(post_data)

        csv_content = response.content.decode()
        self.assertEqual(
            csv_content.count('\n'), 41,
            msg="Sanity check: CSV should have one line per point plus"
                " header and total rows = 42 lines, 41 newlines")
        self.assertIn(
            "Machine suggestion 5", csv_content,
            msg="Sanity check: CSV should have machine suggestion columns")
        self.assertIn(
            "Canon", csv_content,
            msg="Sanity check: CSV should have some expected metadata")
