from django.urls import reverse
import pyexcel

from export.tests.utils import BaseExportTest
from labels.models import LocalLabel
from lib.tests.utils import BasePermissionTest
from visualization.tests.utils import BrowseActionsFormTest


class PermissionTest(BasePermissionTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, cls.labels)

    def test_image_covers(self):
        url = reverse('export_image_covers_prep', args=[self.source.pk])
        data = dict(label_display='code', export_format='csv')

        self.source_to_private()
        self.assertPermissionLevel(
            url, self.SOURCE_VIEW,
            is_json=True, post_data=data, content_type='text/csv')
        self.source_to_public()
        self.assertPermissionLevel(
            url, self.SIGNED_IN,
            is_json=True, post_data=data, content_type='text/csv',
            deny_type=self.REQUIRE_LOGIN)


class FormAvailabilityTest(BrowseActionsFormTest):
    form_id = 'export-image-covers-prep-form'

    def test_no_labelset(self):
        self.client.force_login(self.user)
        response = self.client.get(self.browse_url)
        self.assert_form_placeholdered(
            response,
            "This action isn't available because the source has no labelset.")

    def test_with_labelset(self):
        self.create_labelset(self.user, self.source, self.labels)

        self.client.force_login(self.user)
        response = self.client.get(self.browse_url)
        self.assert_form_available(response)

    def test_logged_out(self):
        self.create_labelset(self.user, self.source, self.labels)

        self.client.logout()
        response = self.client.get(self.browse_url)
        self.assert_form_absent(response)


class BaseImageCoversExportTest(BaseExportTest):
    """Subclasses must define self.client and self.source."""

    def export_image_covers_prep(self, data):
        if 'label_display' not in data:
            data['label_display'] = 'code'
        if 'export_format' not in data:
            data['export_format'] = 'csv'

        self.client.force_login(self.user)
        return self.client.post(
            reverse('export_image_covers_prep', args=[self.source.pk]),
            data, follow=True)

    def export_image_covers(self, data):
        prep_response = self.export_image_covers_prep(data)
        timestamp = prep_response.json()['session_data_timestamp']
        return self.client.get(
            reverse('source_export_serve', args=[self.source.pk]),
            dict(session_data_timestamp=timestamp),
        )


class NoLabelsetTest(BaseImageCoversExportTest):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)

    def test(self):
        response = self.export_image_covers_prep(dict())

        # Error in JSON instead of serving CSV.
        self.assertEqual(
            response.json()['error'],
            "You must create a labelset before exporting data.")


class FileTypeTest(BaseImageCoversExportTest):
    """Test the Excel export option."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user,
            default_point_generation_method=dict(type='simple', points=5))
        cls.labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, cls.labels)

        cls.img1 = cls.upload_image(
            cls.user, cls.source, dict(filename='1.jpg'))
        cls.img2 = cls.upload_image(
            cls.user, cls.source, dict(filename='2.jpg'))
        cls.img3 = cls.upload_image(
            cls.user, cls.source, dict(filename='3.jpg'))
        cls.add_annotations(cls.user, cls.img1, {
            1: 'A', 2: 'A', 3: 'A', 4: 'A', 5: 'A'})
        cls.add_annotations(cls.user, cls.img2, {
            1: 'A', 2: 'A', 3: 'A', 4: 'A', 5: 'A'})
        cls.add_annotations(cls.user, cls.img3, {
            1: 'A', 2: 'A', 3: 'A', 4: 'A', 5: 'A'})
        cls.img1.metadata.aux1 = 'X'
        cls.img1.metadata.save()
        cls.img2.metadata.aux1 = 'Y'
        cls.img2.metadata.save()
        cls.img3.metadata.aux1 = 'X'
        cls.img3.metadata.save()

    def test_csv(self):
        response = self.export_image_covers(dict())

        self.assertEqual(
            response['content-disposition'],
            'attachment;filename="percent_covers.csv"',
            msg="Filename should be as expected")

        self.assertEqual(
            response['content-type'], 'text/csv',
            msg="Content type should be CSV")

        # CSV contents are already covered by other tests, so no need to
        # re-test that here.

    def test_excel(self):
        data = self.default_search_params.copy()
        # Some, but not all, images
        data['aux1'] = 'X'
        data['export_format'] = 'excel'
        response = self.export_image_covers(data)

        self.assertEqual(
            response['content-disposition'],
            'attachment;filename="percent_covers.xlsx"',
            msg="Filename should be as expected")

        self.assertEqual(
            response['content-type'],
            'application/'
            'vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            msg="Content type should correspond to xlsx")

        book = pyexcel.get_book(
            file_type='xlsx', file_content=response.content)

        # Check data sheet contents
        expected_lines = [
            'Image ID,Image name,Annotation status,Points,A,B',
            # Excel will trim trailing zeros
            f'{self.img1.pk},1.jpg,Confirmed,5,100,0',
            f'{self.img3.pk},3.jpg,Confirmed,5,100,0',
            f'ALL IMAGES,,,,100,0',
        ]
        self.assert_csv_content_equal(book["Data"].csv, expected_lines)

        # Check meta sheet contents
        actual_rows = book["Meta"].array
        self.assertEqual(5, len(actual_rows))
        self.assertEqual(
            ["Source name", self.source.name], actual_rows[0])
        self.assertEqual(
            ["Image search method",
             "Filtering by aux1; Sorting by name, ascending"],
            actual_rows[1])
        self.assertEqual(
            ["Images in export", 2], actual_rows[2])
        self.assertEqual(
            ["Images in source", 3], actual_rows[3])
        # Currently being lazy and not checking the actual date here.
        self.assertEqual(
            "Export date", actual_rows[4][0])


class ImageSetTest(BaseImageCoversExportTest):
    """Test image covers export to CSV for different kinds of image subsets."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user,
            default_point_generation_method=dict(type='simple', points=5))
        cls.labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, cls.labels)

    def test_all_images_single(self):
        """Export for 1 out of 1 images."""
        img1 = self.upload_image(
            self.user, self.source, dict(filename='1.jpg'))
        self.add_annotations(self.user, img1, {
            1: 'A', 2: 'B', 3: 'A', 4: 'B', 5: 'A'})

        response = self.export_image_covers(dict())

        expected_lines = [
            'Image ID,Image name,Annotation status,Points,A,B',
            f'{img1.pk},1.jpg,Confirmed,5,60.000,40.000',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_all_images_multiple(self):
        """Export for n out of n images."""
        img1 = self.upload_image(
            self.user, self.source, dict(filename='1.jpg'))
        img2 = self.upload_image(
            self.user, self.source, dict(filename='2.jpg'))
        img3 = self.upload_image(
            self.user, self.source, dict(filename='3.jpg'))
        self.add_annotations(self.user, img1, {
            1: 'A', 2: 'B', 3: 'A', 4: 'B', 5: 'A'})
        self.add_annotations(self.user, img2, {
            1: 'A', 2: 'B', 3: 'B', 4: 'B', 5: 'B'})
        self.add_annotations(self.user, img3, {
            1: 'A', 2: 'A', 3: 'A', 4: 'A', 5: 'A'})

        response = self.export_image_covers(dict())

        expected_lines = [
            'Image ID,Image name,Annotation status,Points,A,B',
            f'{img1.pk},1.jpg,Confirmed,5,60.000,40.000',
            f'{img2.pk},2.jpg,Confirmed,5,20.000,80.000',
            f'{img3.pk},3.jpg,Confirmed,5,100.000,0.000',
            'ALL IMAGES,,,,60.000,40.000',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_image_subset_by_metadata(self):
        """Export for some, but not all, images."""
        img1 = self.upload_image(
            self.user, self.source, dict(filename='1.jpg'))
        img2 = self.upload_image(
            self.user, self.source, dict(filename='2.jpg'))
        img3 = self.upload_image(
            self.user, self.source, dict(filename='3.jpg'))
        self.add_annotations(self.user, img1, {
            1: 'A', 2: 'B', 3: 'A', 4: 'B', 5: 'A'})
        self.add_annotations(self.user, img2, {
            1: 'A', 2: 'B', 3: 'B', 4: 'B', 5: 'B'})
        self.add_annotations(self.user, img3, {
            1: 'A', 2: 'A', 3: 'A', 4: 'A', 5: 'A'})
        img1.metadata.aux1 = 'X'
        img1.metadata.save()
        img2.metadata.aux1 = 'Y'
        img2.metadata.save()
        img3.metadata.aux1 = 'X'
        img3.metadata.save()

        data = self.default_search_params.copy()
        data['aux1'] = 'X'
        response = self.export_image_covers(data)

        expected_lines = [
            'Image ID,Image name,Annotation status,Points,A,B',
            f'{img1.pk},1.jpg,Confirmed,5,60.000,40.000',
            f'{img3.pk},3.jpg,Confirmed,5,100.000,0.000',
            'ALL IMAGES,,,,80.000,20.000',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_image_empty_set(self):
        """Export for 0 images."""
        img1 = self.upload_image(
            self.user, self.source, dict(filename='1.jpg'))
        self.add_annotations(self.user, img1, {
            1: 'A', 2: 'B', 3: 'A', 4: 'B', 5: 'A'})

        data = self.default_search_params.copy()
        data['image_name'] = '5.jpg'
        response = self.export_image_covers(data)

        expected_lines = [
            'Image ID,Image name,Annotation status,Points,A,B',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_exclude_unannotated_images(self):
        """
        CSV should exclude unannotated images, regardless of whether the
        search filters include such images.
        """
        img1 = self.upload_image(
            self.user, self.source, dict(filename='1.jpg'))
        img2 = self.upload_image(
            self.user, self.source, dict(filename='2.jpg'))
        self.upload_image(
            self.user, self.source, dict(filename='3.jpg'))
        # 1st image confirmed
        self.add_annotations(self.user, img1, {
            1: 'A', 2: 'B', 3: 'A', 4: 'B', 5: 'A'})
        # 2nd image unconfirmed
        robot = self.create_robot(self.source)
        self.add_robot_annotations(robot, img2, {
            1: 'A', 2: 'B', 3: 'B', 4: 'B', 5: 'B'})
        # 3rd image unannotated

        response = self.export_image_covers(dict())

        expected_lines = [
            'Image ID,Image name,Annotation status,Points,A,B',
            f'{img1.pk},1.jpg,Confirmed,5,60.000,40.000',
            f'{img2.pk},2.jpg,Unconfirmed,5,20.000,80.000',
            'ALL IMAGES,,,,40.000,60.000',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_invalid_image_set_params(self):
        self.upload_image(self.user, self.source)

        data = self.default_search_params.copy()
        data['photo_date_0'] = 'abc'
        response = self.export_image_covers_prep(data)

        # Error in JSON instead of serving CSV.
        self.assertEqual(
            response.json()['error'],
            "Image-search parameters were invalid.")

    def test_dont_get_other_sources_images(self):
        """Don't export for other sources' images."""
        img1 = self.upload_image(
            self.user, self.source, dict(filename='1.jpg'))
        self.add_annotations(self.user, img1, {
            1: 'A', 2: 'B', 3: 'A', 4: 'B', 5: 'A'})

        source2 = self.create_source(
            self.user,
            default_point_generation_method=dict(type='simple', points=5))
        self.create_labelset(self.user, source2, self.labels)
        img2 = self.upload_image(self.user, source2, dict(filename='2.jpg'))
        self.add_annotations(self.user, img2, {
            1: 'A', 2: 'B', 3: 'A', 4: 'B', 5: 'A'})

        response = self.export_image_covers(dict())

        # Should have image 1, but not 2
        expected_lines = [
            'Image ID,Image name,Annotation status,Points,A,B',
            f'{img1.pk},1.jpg,Confirmed,5,60.000,40.000',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)


class LabelColumnsTest(BaseImageCoversExportTest):
    """Test naming and ordering of the per-label CSV columns."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user,
            default_point_generation_method=dict(type='simple', points=5))
        # To test ordering by group and then name/code, we'll stagger the
        # alphabetical ordering between two label groups.
        labels_a = cls.create_labels(cls.user, ['A1', 'B1', 'C1'], 'Group1')
        labels_b = cls.create_labels(cls.user, ['A2', 'B2'], 'Group2')
        cls.create_labelset(cls.user, cls.source, labels_a | labels_b)

        # Custom codes; ordering by these codes gives a different order from
        # ordering by name or default code. Again, alpha order is staggered
        # between groups.
        local_a = LocalLabel.objects.get(
            labelset=cls.source.labelset, code='A1')
        local_a.code = '21'
        local_a.save()
        local_b = LocalLabel.objects.get(
            labelset=cls.source.labelset, code='B1')
        local_b.code = '31'
        local_b.save()
        local_c = LocalLabel.objects.get(
            labelset=cls.source.labelset, code='C1')
        local_c.code = '11'
        local_c.save()

        local_d = LocalLabel.objects.get(
            labelset=cls.source.labelset, code='A2')
        local_d.code = '22'
        local_d.save()
        local_e = LocalLabel.objects.get(
            labelset=cls.source.labelset, code='B2')
        local_e.code = '12'
        local_e.save()

    def test_order_by_group_and_code(self):
        img1 = self.upload_image(
            self.user, self.source, dict(filename='1.jpg'))
        self.add_annotations(self.user, img1, {
            1: '21', 2: '31', 3: '31', 4: '22', 5: '12'})

        response = self.export_image_covers(dict())

        # Columns should have LocalLabel short codes
        expected_lines = [
            'Image ID,Image name,Annotation status,Points,11,21,31,12,22',
            f'{img1.pk},1.jpg,Confirmed,5,0.000,20.000,40.000,20.000,20.000',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_order_by_group_and_name(self):
        img1 = self.upload_image(
            self.user, self.source, dict(filename='1.jpg'))
        self.add_annotations(self.user, img1, {
            1: '21', 2: '31', 3: '31', 4: '22', 5: '12'})

        response = self.export_image_covers(dict(label_display='name'))

        # Columns should have global label names
        expected_lines = [
            'Image ID,Image name,Annotation status,Points,A1,B1,C1,A2,B2',
            f'{img1.pk},1.jpg,Confirmed,5,20.000,40.000,0.000,20.000,20.000',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)


class UnicodeTest(BaseImageCoversExportTest):
    """Test that non-ASCII characters don't cause problems."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user,
            default_point_generation_method=dict(type='simple', points=5))

        labels = cls.create_labels(cls.user, ['A'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, labels)
        # Unicode custom label code
        local_label = cls.source.labelset.locallabel_set.get(code='A')
        local_label.code = 'い'
        local_label.save()

    def test(self):
        img1 = self.upload_image(
            self.user, self.source, dict(filename='あ.jpg'))
        self.add_annotations(self.user, img1, {
            1: 'い', 2: 'い', 3: 'い', 4: 'い', 5: 'い'})

        response = self.export_image_covers(dict())

        expected_lines = [
            'Image ID,Image name,Annotation status,Points,い',
            f'{img1.pk},あ.jpg,Confirmed,5,100.000',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)


class PerformanceTest(BaseImageCoversExportTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user,
            default_point_generation_method=dict(type='simple', points=20))
        cls.labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, cls.labels)

    def test_num_queries(self):
        robot = self.create_robot(self.source)

        for i in range(20):
            img = self.upload_image(
                self.user, self.source, dict(filename=f'{i}.png'))

            if i < 10:
                # Half confirmed
                self.add_annotations(
                    self.user, img, {p: 'A' for p in range(1, 20+1)})
            else:
                # Half unconfirmed
                self.add_robot_annotations(
                    robot, img, {p: 'A' for p in range(1, 20+1)})

        # Number of queries should be a small constant factor from 20
        # (image count), and definitely less than 400 (annotation count).
        with self.assert_queries_less_than(20*3):
            response = self.export_image_covers(dict())
        self.assertStatusOK(response)
        self.assertEqual(response['content-type'], 'text/csv')
