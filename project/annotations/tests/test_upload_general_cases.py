# Tests which apply regardless of the annotation upload format, but are
# implemented as CSV-upload tests in this case.
# CPC version is at cpce/tests/test_upload_general_cases.py.

import codecs
from unittest import mock

from django.core.files.base import ContentFile
from django.test.utils import override_settings
from django.urls import reverse

from images.models import Point
from lib.tests.utils import BasePermissionTest, ClientTest
from .utils import (
    UploadAnnotationsCsvTestMixin,
    UploadAnnotationsFormatTest,
    UploadAnnotationsGeneralCasesTest,
    UploadAnnotationsMultipleSourcesTest,
)


class PermissionTest(BasePermissionTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, cls.labels)

    def test_annotations_csv(self):
        url = reverse('annotations_upload_page', args=[self.source.pk])
        template = 'annotations/upload.html'

        self.source_to_private()
        self.assertPermissionLevel(url, self.SOURCE_EDIT, template=template)
        self.source_to_public()
        self.assertPermissionLevel(url, self.SOURCE_EDIT, template=template)

    def test_annotations_csv_preview_ajax(self):
        url = reverse('annotations_upload_preview', args=[self.source.pk])

        self.source_to_private()
        self.assertPermissionLevel(
            url, self.SOURCE_EDIT, is_json=True, post_data={})
        self.source_to_public()
        self.assertPermissionLevel(
            url, self.SOURCE_EDIT, is_json=True, post_data={})

    def test_annotations_csv_confirm_ajax(self):
        url = reverse('annotations_upload_confirm', args=[self.source.pk])

        self.source_to_private()
        self.assertPermissionLevel(
            url, self.SOURCE_EDIT, is_json=True, post_data={})
        self.source_to_public()
        self.assertPermissionLevel(
            url, self.SOURCE_EDIT, is_json=True, post_data={})


class UploadAnnotationsNoLabelsetTest(ClientTest):
    """
    Point/annotation upload attempts with no labelset.
    This should just fail to reach the page.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)

    def test_page(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('annotations_upload_page', args=[self.source.pk]),
        )
        self.assertContains(
            response,
            "You must create a labelset before uploading annotations.")
        self.assertTemplateUsed(response, 'labels/labelset_required.html')

    def test_preview(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('annotations_upload_preview', args=[self.source.pk]),
        )
        self.assertContains(
            response,
            "You must create a labelset before uploading annotations.")
        self.assertTemplateUsed(response, 'labels/labelset_required.html')

    def test_confirm(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('annotations_upload_confirm', args=[self.source.pk]),
        )
        self.assertContains(
            response,
            "You must create a labelset before uploading annotations.")
        self.assertTemplateUsed(response, 'labels/labelset_required.html')


class GeneralCasesTest(
        UploadAnnotationsGeneralCasesTest, UploadAnnotationsCsvTestMixin):
    """
    General functionality.
    """
    def test_points_only(self):
        """
        No annotations on specified points.
        """
        rows = [
            ['Name', 'Column', 'Row'],
            ['1.png', 50, 50],
            ['1.png', 60, 40],
            ['1.png', 70, 30],
            ['1.png', 80, 20],
            ['1.png', 90, 10],
            ['2.png', 0, 0],
            ['2.png', 199, 99],
            ['2.png', 44, 44],
        ]
        csv_file = self.make_annotations_file('A.csv', rows)
        preview_response = self.preview_annotations(
            self.user, self.source, csv_file)
        upload_response = self.upload_annotations(self.user, self.source)

        self.check_points_only(preview_response, upload_response)

    def test_all_annotations(self):
        """
        Annotations on all specified points.
        """
        rows = [
            ['Name', 'Column', 'Row', 'Label'],
            ['1.png', 50, 50, 'A'],
            ['1.png', 60, 40, 'B'],
            ['2.png', 70, 30, 'A'],
            ['2.png', 80, 20, 'A'],
        ]
        csv_file = self.make_annotations_file('A.csv', rows)
        preview_response = self.preview_annotations(
            self.user, self.source, csv_file)
        upload_response = self.upload_annotations(self.user, self.source)

        self.check_all_annotations(preview_response, upload_response)

    def test_some_annotations(self):
        """
        Annotations on some specified points, but not all.
        """
        rows = [
            ['Name', 'Column', 'Row', 'Label'],
            ['1.png', 50, 50, 'A'],
            ['1.png', 60, 40, 'B'],
            ['2.png', 70, 30, 'A'],
            ['2.png', 80, 20],
            ['3.png', 70, 30],
            ['3.png', 80, 20],
        ]
        csv_file = self.make_annotations_file('A.csv', rows)
        preview_response = self.preview_annotations(
            self.user, self.source, csv_file)
        upload_response = self.upload_annotations(self.user, self.source)

        self.check_some_annotations(preview_response, upload_response)

    def test_overwrite_annotations(self):
        """
        Save some annotations, then overwrite those with other annotations.
        """
        rows = [
            ['Name', 'Column', 'Row', 'Label'],
            ['1.png', 50, 50, 'A'],
            ['1.png', 60, 40, 'B'],
            ['2.png', 70, 30, 'A'],
            ['2.png', 80, 20],
            ['3.png', 70, 30],
            ['3.png', 80, 20],
        ]
        csv_file = self.make_annotations_file('A.csv', rows)
        self.preview_annotations(self.user, self.source, csv_file)
        self.upload_annotations(self.user, self.source)

        rows = [
            ['Name', 'Column', 'Row', 'Label'],
            ['1.png', 10, 10, 'A'],
            ['1.png', 20, 20, 'A'],
            ['2.png', 30, 30],
            ['2.png', 40, 40],
            ['3.png', 50, 50, 'A'],
            ['3.png', 60, 60, 'B'],
        ]
        csv_file = self.make_annotations_file('B.csv', rows)
        preview_response = self.preview_annotations(
            self.user, self.source, csv_file)
        upload_response = self.upload_annotations(self.user, self.source)

        self.check_overwrite_annotations(preview_response, upload_response)

    def test_label_codes_different_case(self):
        """
        The import file's label codes can use different upper/lower case
        and still be matched to the corresponding labelset label codes.
        """
        # Make a longer-than-1-char label code so we can test that
        # lower() is being used on both the label's code and the CSV value
        labels = self.create_labels(self.user, ['Abc'], 'Group1')
        self.create_labelset(self.user, self.source, labels)

        rows = [
            ['Name', 'Column', 'Row', 'Label'],
            ['1.png', 60, 40, 'aBc'],
        ]
        csv_file = self.make_annotations_file('A.csv', rows)
        preview_response = self.preview_annotations(
            self.user, self.source, csv_file)
        upload_response = self.upload_annotations(self.user, self.source)

        self.check_label_codes_different_case(
            preview_response, upload_response)

    def test_skipped_filenames(self):
        """
        The CSV can have filenames that we don't recognize. Those rows
        will just be ignored.
        """
        rows = [
            ['Name', 'Column', 'Row', 'Label'],
            ['1.png', 50, 50, 'A'],
            ['4.png', 60, 40, 'B'],
        ]
        csv_file = self.make_annotations_file('A.csv', rows)
        preview_response = self.preview_annotations(
            self.user, self.source, csv_file)
        upload_response = self.upload_annotations(self.user, self.source)

        self.check_skipped_filenames(preview_response, upload_response)

    def test_annotation_history(self):
        """
        The upload should create an annotation history entry.
        """
        rows = [
            ['Name', 'Column', 'Row', 'Label'],
            ['1.png', 10, 10, 'A'],
            ['1.png', 20, 20, ''],
            ['1.png', 30, 30, 'B'],
        ]
        csv_file = self.make_annotations_file('A.csv', rows)
        self.preview_annotations(self.user, self.source, csv_file)
        self.upload_annotations(self.user, self.source)

        self.check_annotation_history()

    def test_transaction_rollback(self):
        """
        If the confirm view encounters an error after saving annotations,
        then the saves should be rolled back.
        """
        rows = [
            ['Name', 'Column', 'Row', 'Label'],
            ['1.png', 10, 10, 'A'],
            ['1.png', 20, 20, ''],
            ['1.png', 30, 30, 'B'],
        ]
        csv_file = self.make_annotations_file('A.csv', rows)
        self.preview_annotations(self.user, self.source, csv_file)

        def raise_error(self, *args, **kwargs):
            raise ValueError

        with mock.patch('annotations.views.reset_features', raise_error):
            with self.assertRaises(ValueError):
                self.upload_annotations(self.user, self.source)

        self.check_transaction_rollback()


class MultipleSourcesTest(
        UploadAnnotationsMultipleSourcesTest, UploadAnnotationsCsvTestMixin):
    """
    Test involving multiple sources.
    """
    def test_other_sources_unaffected(self):
        """
        We shouldn't touch images of other sources which happen to have
        the same image names.
        """
        # Upload to source 2
        rows = [
            ['Name', 'Column', 'Row', 'Label'],
            ['1.png', 10, 10, 'B'],
            ['1.png', 20, 20, 'B'],
            ['2.png', 15, 15, 'A'],
            ['2.png', 25, 25, 'A'],
        ]
        csv_file = self.make_annotations_file('A.csv', rows)
        self.preview_annotations(self.user, self.source2, csv_file)
        self.upload_annotations(self.user, self.source2)

        # Upload to source 1
        rows = [
            ['Name', 'Column', 'Row', 'Label'],
            ['1.png', 50, 50, 'A'],
            # This image doesn't exist in source 1
            ['2.png', 60, 40, 'B'],
        ]
        csv_file = self.make_annotations_file('B.csv', rows)
        preview_response = self.preview_annotations(
            self.user, self.source, csv_file)
        upload_response = self.upload_annotations(self.user, self.source)

        self.check_other_sources_unaffected(preview_response, upload_response)


class UploadAnnotationsContentsTest(ClientTest, UploadAnnotationsCsvTestMixin):
    """
    Annotation upload edge cases and error cases related to contents.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)
        # Labels in labelset
        labels = cls.create_labels(cls.user, ['A', 'B'], 'Group1')
        cls.create_labelset(cls.user, cls.source, labels)
        # Label not in labelset
        cls.create_labels(cls.user, ['C'], 'Group1')

        cls.img1 = cls.upload_image(
            cls.user, cls.source,
            image_options=dict(filename='1.png', width=200, height=100))
        cls.img2 = cls.upload_image(
            cls.user, cls.source,
            image_options=dict(filename='2.png', width=100, height=200))

        cls.image_dimensions_1 = (200, 100)
        cls.image_dimensions_2 = (100, 200)

    def do_success(self, point_data, expected_points_set):
        rows = [['1.png']+list(p) for p in point_data]
        if len(rows[0]) == 3:
            header_row = ['Name', 'Column', 'Row']
        else:
            header_row = ['Name', 'Column', 'Row', 'Label']
        csv_file = self.make_annotations_file('A.csv', [header_row] + rows)
        self.preview_annotations(self.user, self.source, csv_file)
        self.upload_annotations(self.user, self.source)

        values_set = set(
            Point.objects.filter(image__in=[self.img1])
            .values_list('column', 'row', 'point_number', 'image_id'))
        self.assertSetEqual(values_set, expected_points_set)

    def do_error(self, point_data, expected_error):
        rows = [['1.png']+list(p) for p in point_data]
        if len(rows[0]) == 3:
            header_row = ['Name', 'Column', 'Row']
        else:
            header_row = ['Name', 'Column', 'Row', 'Label']
        csv_file = self.make_annotations_file('A.csv', [header_row] + rows)
        preview_response = self.preview_annotations(
            self.user, self.source, csv_file)

        self.assertDictEqual(
            preview_response.json(),
            dict(error=expected_error))

    def test_row_not_number(self):
        """A row/col which can't be parsed as a number should result in an
        appropriate error message."""
        self.do_error(
            [(50, 'abc')],
            "For image 1.png, point 1:"
            " Row should be a non-negative integer, not abc")

    def test_column_not_number(self):
        self.do_error(
            [('1abc', 50)],
            "For image 1.png, point 1:"
            " Column should be a non-negative integer, not 1abc")

    def test_row_is_float(self):
        """A row/col which can't be parsed as an integer should result in an
        appropriate error message."""
        self.do_error(
            [(50, 40.8)],
            "For image 1.png, point 1:"
            " Row should be a non-negative integer, not 40.8")

    def test_column_is_float(self):
        self.do_error(
            [(50.88, 40)],
            "For image 1.png, point 1:"
            " Column should be a non-negative integer, not 50.88")

    def test_row_minimum_value(self):
        """Minimum acceptable row value."""
        self.do_success(
            [(50, 0)],
            {(50, 0, 1, self.img1.pk)})

    def test_column_minimum_value(self):
        self.do_success(
            [(0, 40)],
            {(0, 40, 1, self.img1.pk)})

    def test_row_too_small(self):
        """Below the minimum acceptable row value."""
        self.do_error(
            [(50, -1)],
            "For image 1.png, point 1:"
            " Row should be a non-negative integer, not -1")

    def test_column_too_small(self):
        self.do_error(
            [(-1, 50)],
            "For image 1.png, point 1:"
            " Column should be a non-negative integer, not -1")

    def test_row_maximum_value(self):
        """Maximum acceptable row value given the image dimensions."""
        self.do_success(
            [(50, 99)],
            {(50, 99, 1, self.img1.pk)})

    def test_column_maximum_value(self):
        self.do_success(
            [(199, 40)],
            {(199, 40, 1, self.img1.pk)})

    def test_row_too_large(self):
        """Above the maximum acceptable row value given the
        image dimensions."""
        self.do_error(
            [(50, 100)],
            "For image 1.png, point 1:"
            " Row value is 100, but the image is only 100 pixels high"
            " (accepted values are 0~99)")

    def test_column_too_large(self):
        self.do_error(
            [(200, 50)],
            "For image 1.png, point 1:"
            " Column value is 200, but the image is only 200 pixels wide"
            " (accepted values are 0~199)")

    def test_multiple_points_same_row_column(self):
        """
        More than one point in the same image on the exact same position
        (same row and same column) should be allowed.
        """
        self.do_success(
            [(150, 90), (20, 20), (150, 90)],
            {
                (150, 90, 1, self.img1.pk),
                (20, 20, 2, self.img1.pk),
                (150, 90, 3, self.img1.pk),
            })

    @override_settings(MAX_POINTS_PER_IMAGE=3)
    def test_max_points(self):
        self.do_success(
            [(10, 10), (20, 20), (30, 30)],
            {
                (10, 10, 1, self.img1.pk),
                (20, 20, 2, self.img1.pk),
                (30, 30, 3, self.img1.pk),
            })

    @override_settings(MAX_POINTS_PER_IMAGE=3)
    def test_above_max_points(self):
        self.do_error(
            [(10, 10), (20, 20), (30, 30), (40, 40)],
            "For image 1.png:"
            " Found 4 points, which exceeds the"
            " maximum allowed of 3")

    def test_label_not_in_labelset(self):
        self.do_error(
            [(150, 90, 'B'), (20, 20, 'C')],
            "For image 1.png, point 2:"
            " No label of code C found in this source's labelset")

    def test_no_specified_images_found_in_source(self):
        """
        The import data has no filenames that can be found in the source.
        """
        csv_file = self.make_annotations_file('A.csv', [
            ['Name', 'Column', 'Row'],
            ['3.png', 50, 50],
            ['4.png', 60, 40]])
        preview_response = self.preview_annotations(
            self.user, self.source, csv_file)

        self.assertDictEqual(
            preview_response.json(),
            dict(
                error="No matching image names found in the source",
            ),
        )


class FormatTest(UploadAnnotationsFormatTest, UploadAnnotationsCsvTestMixin):
    """
    Tests (mostly error cases) related to file format.
    """
    def test_unicode(self):
        """Test Unicode image filenames and label codes."""
        content = (
            'Name,Column,Row,Label\n'
            'あ.png,50,50,い\n'
        )
        csv_file = ContentFile(content, name='A.csv')

        preview_response = self.preview_annotations(
            self.user, self.source, csv_file)
        upload_response = self.upload_annotations(self.user, self.source)

        self.check(preview_response, upload_response, self.imgA, 'い')

    def test_crlf(self):
        content = (
            'Name,Column,Row,Label\r\n'
            '1.png,50,50,A\r\n'
        )
        csv_file = ContentFile(content, name='A.csv')

        preview_response = self.preview_annotations(
            self.user, self.source, csv_file)
        upload_response = self.upload_annotations(self.user, self.source)

        self.check(preview_response, upload_response, self.img1, 'A')

    def test_cr(self):
        content = (
            'Name,Column,Row,Label\r'
            '1.png,50,50,A\r'
        )
        csv_file = ContentFile(content, name='A.csv')

        preview_response = self.preview_annotations(
            self.user, self.source, csv_file)
        upload_response = self.upload_annotations(self.user, self.source)

        self.check(preview_response, upload_response, self.img1, 'A')

    def test_utf8_bom(self):
        content = (
            codecs.BOM_UTF8.decode() + 'Name,Column,Row,Label\n'
            '1.png,50,50,A\n'
        )
        csv_file = ContentFile(content, name='A.csv')

        preview_response = self.preview_annotations(
            self.user, self.source, csv_file)
        upload_response = self.upload_annotations(self.user, self.source)

        self.check(preview_response, upload_response, self.img1, 'A')

    def test_empty_file(self):
        csv_file = ContentFile('', name='A.csv')

        preview_response = self.preview_annotations(
            self.user, self.source, csv_file)

        self.assertDictEqual(
            preview_response.json(),
            dict(error="The submitted file is empty."),
        )
