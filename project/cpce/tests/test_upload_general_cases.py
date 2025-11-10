# These tests should be one-to-one with
# annotations/tests/test_annotations_general_cases.py.

import codecs
from unittest import mock

from django.core.files.base import ContentFile
from django.test.utils import override_settings
from django.urls import reverse

from annotations.tests.utils import (
    UploadAnnotationsFormatTest,
    UploadAnnotationsGeneralCasesTest,
    UploadAnnotationsMultipleSourcesTest,
    UploadAnnotationsQueriesPerImageTest,
    UploadAnnotationsQueriesPerPointTest,
)
from images.models import Point
from lib.tests.utils import BasePermissionTest, ClientTest
from .utils import UploadAnnotationsCpcTestMixin


class PermissionTest(BasePermissionTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, cls.labels)

    def test_upload_page(self):
        url = reverse('cpce:upload_page', args=[self.source.pk])
        template = 'cpce/upload.html'

        self.source_to_private()
        self.assertPermissionLevel(url, self.SOURCE_EDIT, template=template)
        self.source_to_public()
        self.assertPermissionLevel(url, self.SOURCE_EDIT, template=template)

    def test_upload_preview_ajax(self):
        url = reverse('cpce:upload_preview_ajax', args=[self.source.pk])

        self.source_to_private()
        self.assertPermissionLevel(
            url, self.SOURCE_EDIT, is_json=True, post_data={})
        self.source_to_public()
        self.assertPermissionLevel(
            url, self.SOURCE_EDIT, is_json=True, post_data={})

    def test_upload_confirm_ajax(self):
        url = reverse('cpce:upload_confirm_ajax', args=[self.source.pk])

        self.source_to_private()
        self.assertPermissionLevel(
            url, self.SOURCE_EDIT, is_json=True, post_data={})
        self.source_to_public()
        self.assertPermissionLevel(
            url, self.SOURCE_EDIT, is_json=True, post_data={})


class NoLabelsetTest(ClientTest):
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
            reverse('cpce:upload_page', args=[self.source.pk]),
        )
        self.assertContains(
            response,
            "You must create a labelset before uploading annotations.")
        self.assertTemplateUsed(response, 'labels/labelset_required.html')

    def test_preview(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('cpce:upload_preview_ajax', args=[self.source.pk]),
        )
        self.assertContains(
            response,
            "You must create a labelset before uploading annotations.")
        self.assertTemplateUsed(response, 'labels/labelset_required.html')

    def test_confirm(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('cpce:upload_confirm_ajax', args=[self.source.pk]),
        )
        self.assertContains(
            response,
            "You must create a labelset before uploading annotations.")
        self.assertTemplateUsed(response, 'labels/labelset_required.html')


class GeneralCasesTest(
        UploadAnnotationsGeneralCasesTest, UploadAnnotationsCpcTestMixin):
    """
    General functionality.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)
        labels = cls.create_labels(cls.user, ['A', 'B'], 'Group1')
        cls.create_labelset(cls.user, cls.source, labels)
        cls.img1 = cls.upload_image(
            cls.user, cls.source,
            image_options=dict(filename='1.png', width=200, height=100))
        cls.img2 = cls.upload_image(
            cls.user, cls.source,
            image_options=dict(filename='2.png', width=200, height=100))
        cls.img3 = cls.upload_image(
            cls.user, cls.source,
            image_options=dict(filename='3.png', width=200, height=100))

        cls.image_dimensions = (200, 100)

        # Get full diff output if something like an assertEqual fails
        cls.maxDiff = None

    def test_points_only(self):
        """
        No annotations on specified points.
        """
        cpc_files = [
            self.make_annotations_file(
                self.image_dimensions, '1.cpc',
                r"C:\My Photos\2017-05-13 GBR\1.png", [
                    (50*15, 50*15, ''),
                    (60*15, 40*15, ''),
                    (70*15, 30*15, ''),
                    (80*15, 20*15, ''),
                    (90*15, 10*15, '')]),
            self.make_annotations_file(
                self.image_dimensions, '2.cpc',
                r"C:\My Photos\2017-05-13 GBR\2.png", [
                    (0, 0, ''),
                    (2992, 1492, ''),
                    (44*15, 44*15, '')]),
        ]
        preview_response = self.preview_annotations(
            self.user, self.source, cpc_files)
        upload_response = self.upload_annotations(self.user, self.source)

        self.check_points_only(preview_response, upload_response)

    def test_all_annotations(self):
        """
        Annotations on all specified points.
        """
        cpc_files = [
            self.make_annotations_file(
                self.image_dimensions, '1.cpc',
                r"C:\My Photos\2017-05-13 GBR\1.png", [
                    (50*15, 50*15, 'A'),
                    (60*15, 40*15, 'B')]),
            self.make_annotations_file(
                self.image_dimensions, '2.cpc',
                r"C:\My Photos\2017-05-13 GBR\2.png", [
                    (70*15, 30*15, 'A'),
                    (80*15, 20*15, 'A')]),
        ]
        preview_response = self.preview_annotations(
            self.user, self.source, cpc_files)
        upload_response = self.upload_annotations(self.user, self.source)

        self.check_all_annotations(preview_response, upload_response)

    def test_some_annotations(self):
        """
        Annotations on some specified points, but not all.
        """
        cpc_files = [
            self.make_annotations_file(
                self.image_dimensions, '1.cpc',
                r"C:\My Photos\2017-05-13 GBR\1.png", [
                    (50*15, 50*15, 'A'),
                    (60*15, 40*15, 'B')]),
            self.make_annotations_file(
                self.image_dimensions, '2.cpc',
                r"C:\My Photos\2017-05-13 GBR\2.png", [
                    (70*15, 30*15, 'A'),
                    (80*15, 20*15, '')]),
            self.make_annotations_file(
                self.image_dimensions, '3.cpc',
                r"C:\My Photos\2017-05-13 GBR\3.png", [
                    (70*15, 30*15, ''),
                    (80*15, 20*15, '')]),
        ]
        preview_response = self.preview_annotations(
            self.user, self.source, cpc_files)
        upload_response = self.upload_annotations(self.user, self.source)

        self.check_some_annotations(preview_response, upload_response)

    def test_overwrite_annotations(self):
        """
        Save some annotations, then overwrite those with other annotations.
        """
        cpc_files = [
            self.make_annotations_file(
                self.image_dimensions, '1.cpc',
                r"C:\My Photos\2017-05-13 GBR\1.png", [
                    (50*15, 50*15, 'A'),
                    (60*15, 40*15, 'B')]),
            self.make_annotations_file(
                self.image_dimensions, '2.cpc',
                r"C:\My Photos\2017-05-13 GBR\2.png", [
                    (70*15, 30*15, 'A'),
                    (80*15, 20*15, '')]),
            self.make_annotations_file(
                self.image_dimensions, '3.cpc',
                r"C:\My Photos\2017-05-13 GBR\3.png", [
                    (70*15, 30*15, ''),
                    (80*15, 20*15, '')]),
        ]
        self.preview_annotations(self.user, self.source, cpc_files)
        self.upload_annotations(self.user, self.source)

        cpc_files = [
            self.make_annotations_file(
                self.image_dimensions, '1.cpc',
                r"C:\My Photos\2017-05-13 GBR\1.png", [
                    (10*15, 10*15, 'A'),
                    (20*15, 20*15, 'A')]),
            self.make_annotations_file(
                self.image_dimensions, '2.cpc',
                r"C:\My Photos\2017-05-13 GBR\2.png", [
                    (30*15, 30*15, ''),
                    (40*15, 40*15, '')]),
            self.make_annotations_file(
                self.image_dimensions, '3.cpc',
                r"C:\My Photos\2017-05-13 GBR\3.png", [
                    (50*15, 50*15, 'A'),
                    (60*15, 60*15, 'B')]),
        ]
        preview_response = self.preview_annotations(
            self.user, self.source, cpc_files)
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

        cpc_files = [
            self.make_annotations_file(
                self.image_dimensions, '1.cpc',
                r"C:\My Photos\2017-05-13 GBR\1.png", [
                    (60*15, 40*15, 'aBc')]),
        ]
        preview_response = self.preview_annotations(
            self.user, self.source, cpc_files)
        upload_response = self.upload_annotations(self.user, self.source)

        self.check_label_codes_different_case(
            preview_response, upload_response)

    def test_skipped_filenames(self):
        """
        There can be CPCs corresponding to filenames that we don't recognize.
        Those CPCs will just be ignored.
        """
        cpc_files = [
            self.make_annotations_file(
                self.image_dimensions, '1.cpc',
                r"C:\My Photos\2017-05-13 GBR\1.png", [
                    (50*15, 50*15, 'A')]),
            # image parameter is just for getting image dimensions.
            # This cpc should be skipped anyway, so we don't care which image
            # we pass in.
            self.make_annotations_file(
                self.image_dimensions, '4.cpc',
                r"C:\My Photos\2017-05-13 GBR\4.png", [
                    (60*15, 40*15, 'B')]),
        ]
        preview_response = self.preview_annotations(
            self.user, self.source, cpc_files)
        upload_response = self.upload_annotations(self.user, self.source)

        self.check_skipped_filenames(preview_response, upload_response)

    def test_annotation_history(self):
        """
        The upload should create an annotation history entry.
        """
        cpc_files = [
            self.make_annotations_file(
                self.image_dimensions, '1.cpc',
                r"C:\My Photos\2017-05-13 GBR\1.png", [
                    (9*15, 9*15, 'A'),
                    (19*15, 19*15, ''),
                    (29*15, 29*15, 'B')]),
        ]
        self.preview_annotations(self.user, self.source, cpc_files)
        self.upload_annotations(self.user, self.source)

        self.check_annotation_history()

    def test_transaction_rollback(self):
        """
        If the confirm view encounters an error after saving annotations,
        then the saves should be rolled back.
        """
        cpc_files = [
            self.make_annotations_file(
                self.image_dimensions, '1.cpc',
                r"C:\My Photos\2017-05-13 GBR\1.png", [
                    (9*15, 9*15, 'A'),
                    (19*15, 19*15, ''),
                    (29*15, 29*15, 'B')]),
        ]
        self.preview_annotations(self.user, self.source, cpc_files)

        def raise_error(self, *args, **kwargs):
            raise ValueError

        with mock.patch('annotations.utils.reset_features', raise_error):
            with self.assertRaises(ValueError):
                self.upload_annotations(self.user, self.source)

        self.check_transaction_rollback()


class MultipleSourcesTest(
        UploadAnnotationsMultipleSourcesTest, UploadAnnotationsCpcTestMixin):
    """
    Test involving multiple sources.
    """
    def test_other_sources_unaffected(self):
        """
        We shouldn't touch images of other sources which happen to have
        the same image names.
        """
        # Upload to source 2
        cpc_files = [
            self.make_annotations_file(
                self.image_dimensions, '1.cpc',
                r"C:\My Photos\2017-05-13 GBR\1.png", [
                    (10*15, 10*15, 'B'),
                    (20*15, 20*15, 'B')]),
            self.make_annotations_file(
                self.image_dimensions, '2.cpc',
                r"C:\My Photos\2017-05-13 GBR\2.png", [
                    (15*15, 15*15, 'A'),
                    (25*15, 25*15, 'A')]),
        ]
        self.preview_annotations(self.user, self.source2, cpc_files)
        self.upload_annotations(self.user, self.source2)

        # Upload to source 1
        cpc_files = [
            self.make_annotations_file(
                self.image_dimensions, '1.cpc',
                r"C:\My Photos\2017-05-13 GBR\1.png", [
                    (50*15, 50*15, 'A')]),
            # This image doesn't exist in source 1
            self.make_annotations_file(
                self.image_dimensions, '2.cpc',
                r"C:\My Photos\2017-05-13 GBR\2.png", [
                    (60*15, 40*15, 'B')]),
        ]
        preview_response = self.preview_annotations(
            self.user, self.source, cpc_files)
        upload_response = self.upload_annotations(self.user, self.source)

        self.check_other_sources_unaffected(preview_response, upload_response)


class ContentsEdgeAndErrorCasesTest(ClientTest, UploadAnnotationsCpcTestMixin):
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
        if len(point_data[0]) == 2:
            # point_data elements have (column, row). Add a blank label code.
            point_data = [p+('',) for p in point_data]
        cpc_files = [
            self.make_annotations_file(
                self.image_dimensions_1,
                '1.cpc', r"C:\My Photos\2017-05-13 GBR\1.png",
                point_data)]
        self.preview_annotations(self.user, self.source, cpc_files)
        self.upload_annotations(self.user, self.source)

        values_set = set(
            Point.objects.filter(image__in=[self.img1])
            .values_list('column', 'row', 'point_number', 'image_id'))
        self.assertSetEqual(values_set, expected_points_set)

    def do_error(self, point_data, expected_error):
        if len(point_data[0]) == 2:
            point_data = [p+('',) for p in point_data]
        cpc_files = [
            self.make_annotations_file(
                self.image_dimensions_1,
                '1.cpc', r"C:\My Photos\2017-05-13 GBR\1.png",
                point_data)]
        preview_response = self.preview_annotations(
            self.user, self.source, cpc_files)

        self.assertDictEqual(
            preview_response.json(),
            dict(error=expected_error))

    def test_row_not_number(self):
        self.do_error(
            [(50*15, '?.;')],
            "From file 1.cpc: Point 1:"
            " Row should be a non-negative integer, not ?.;")

    def test_column_not_number(self):
        self.do_error(
            [('abc2', 50*15)],
            "From file 1.cpc: Point 1:"
            " Column should be a non-negative integer, not abc2")

    def test_row_is_float(self):
        self.do_error(
            [(50*15, 40*15+0.8)],
            "From file 1.cpc: Point 1:"
            " Row should be a non-negative integer, not 600.8")

    def test_column_is_float(self):
        self.do_error(
            [(50*15+0.88, 40*15)],
            "From file 1.cpc: Point 1:"
            " Column should be a non-negative integer, not 750.88")

    def test_row_minimum_value(self):
        self.do_success(
            [(50*15, 0)],
            {(50, 0, 1, self.img1.pk)})

    def test_column_minimum_value(self):
        self.do_success(
            [(0, 40*15)],
            {(0, 40, 1, self.img1.pk)})

    def test_row_too_small(self):
        self.do_error(
            [(50*15, -1)],
            "From file 1.cpc: Point 1:"
            " Row should be a non-negative integer, not -1")

    def test_column_too_small(self):
        self.do_error(
            [(-1, 50*15)],
            "From file 1.cpc: Point 1:"
            " Column should be a non-negative integer, not -1")

    def test_row_maximum_value(self):
        self.do_success(
            [(50*15, 99*15)],
            {(50, 99, 1, self.img1.pk)})

    def test_column_maximum_value(self):
        self.do_success(
            [(199*15, 40*15)],
            {(199, 40, 1, self.img1.pk)})

    def test_row_too_large(self):
        self.do_error(
            [(50*15, 100*15)],
            "From file 1.cpc: Point 1:"
            " Row value of 1500 corresponds to pixel 100,"
            " but image 1.png is only 100 pixels high"
            " (accepted values are 0~99)")

    def test_column_too_large(self):
        self.do_error(
            [(200*15, 50*15)],
            "From file 1.cpc: Point 1:"
            " Column value of 3000 corresponds to pixel 200,"
            " but image 1.png is only 200 pixels wide"
            " (accepted values are 0~199)")

    def test_multiple_points_same_row_column(self):
        # These CPC file values for points 1 and 3
        # are different, but they map to the same pixel.
        self.do_success(
            [(150*15-2, 90*15-2), (20*15, 20*15), (150*15+2, 90*15+2)],
            {
                (150, 90, 1, self.img1.pk),
                (20, 20, 2, self.img1.pk),
                (150, 90, 3, self.img1.pk),
            })

    @override_settings(MAX_POINTS_PER_IMAGE=3)
    def test_max_points(self):
        self.do_success(
            [(10*15, 10*15), (20*15, 20*15), (30*15, 30*15)],
            {
                (10, 10, 1, self.img1.pk),
                (20, 20, 2, self.img1.pk),
                (30, 30, 3, self.img1.pk),
            })

    @override_settings(MAX_POINTS_PER_IMAGE=3)
    def test_above_max_points(self):
        self.do_error(
            [(10*15, 10*15), (20*15, 20*15), (30*15, 30*15), (40*15, 40*15)],
            "From file 1.cpc:"
            " Found 4 points, which exceeds the"
            " maximum allowed of 3")

    def test_label_not_in_labelset(self):
        self.do_error(
            [(150*15, 90*15, 'B'), (20*15, 20*15, 'C')],
            "From file 1.cpc: Point 2:"
            " No label of code C found in this source's labelset")

    def test_no_specified_images_found_in_source(self):
        cpc_files = [
            # We don't care which image we pass as the first parameter.
            self.make_annotations_file(
                self.image_dimensions_1,
                '3.cpc', r"C:\My Photos\2017-05-13 GBR\3.png", [
                    (50*15, 50*15, '')]),
            self.make_annotations_file(
                self.image_dimensions_1,
                '4.cpc', r"C:\My Photos\2017-05-13 GBR\4.png", [
                    (60*15, 40*15, '')]),
        ]
        preview_response = self.preview_annotations(
            self.user, self.source, cpc_files)

        self.assertDictEqual(
            preview_response.json(),
            dict(
                error="No matching image names found in the source",
            ),
        )


class FormatTest(UploadAnnotationsFormatTest, UploadAnnotationsCpcTestMixin):
    """
    Tests (mostly error cases) related to file format.
    """
    def test_unicode(self):
        """
        Test Unicode label codes. Don't know if CPC with
        non-ASCII is possible in practice, but might as well test that it
        works.

        TODO: Once we upgrade to Python 3.7, test Unicode image filenames as
        well. re.escape() (used in annotations_cpc_verify_contents()) has
        undesired behavior with Unicode in Python 3.6 (adds too many
        backslashes).
        To test that, change the filename to あ.png and pass self.imgA to
        self.check().
        """
        cpc_files = [
            self.make_annotations_file(
                self.image_dimensions,
                '1.cpc', r"C:\My Photos\2017-05-13 GBR\1.png",
                [(50*15, 50*15, 'い')]),
        ]
        preview_response = self.preview_annotations(
            self.user, self.source, cpc_files)
        upload_response = self.upload_annotations(self.user, self.source)

        self.check(preview_response, upload_response, self.img1, 'い')

    def test_crlf(self):
        """Most of the CPC tests use linefeed only, but CPCe is Windows
        software, so it'll use carriage return + linefeed."""
        cpc_file_lf = self.make_annotations_file(
            self.image_dimensions,
            '1.cpc', r"C:\My Photos\2017-05-13 GBR\1.png",
            [(50*15, 50*15, 'A')])
        cpc_file_crlf_content = cpc_file_lf.read().replace('\n', '\r\n')
        cpc_files = [
            ContentFile(cpc_file_crlf_content, name='1.cpc'),
        ]
        preview_response = self.preview_annotations(
            self.user, self.source, cpc_files)
        upload_response = self.upload_annotations(self.user, self.source)

        self.check(preview_response, upload_response, self.img1, 'A')

    def test_cr(self):
        """Don't know if CPC with cr newlines is possible in practice, but
        might as well test that it works."""
        cpc_file_lf = self.make_annotations_file(
            self.image_dimensions,
            '1.cpc', r"C:\My Photos\2017-05-13 GBR\1.png",
            [(50*15, 50*15, 'A')])
        cpc_file_crlf_content = cpc_file_lf.read().replace('\n', '\r')
        cpc_files = [
            ContentFile(cpc_file_crlf_content, name='1.cpc'),
        ]
        preview_response = self.preview_annotations(
            self.user, self.source, cpc_files)
        upload_response = self.upload_annotations(self.user, self.source)

        self.check(preview_response, upload_response, self.img1, 'A')

    def test_utf8_bom(self):
        """Don't know if CPC with UTF-8 BOM is possible in practice, but
        might as well test that it works."""
        cpc_file_lf = self.make_annotations_file(
            self.image_dimensions,
            '1.cpc', r"C:\My Photos\2017-05-13 GBR\1.png",
            [(50*15, 50*15, 'A')])
        cpc_file_crlf_content = (
            codecs.BOM_UTF8.decode() + cpc_file_lf.read())
        cpc_files = [
            ContentFile(cpc_file_crlf_content, name='1.cpc'),
        ]
        preview_response = self.preview_annotations(
            self.user, self.source, cpc_files)
        upload_response = self.upload_annotations(self.user, self.source)

        self.check(preview_response, upload_response, self.img1, 'A')

    def test_empty_file(self):
        cpc_files = [
            ContentFile('', name='1.cpc')
        ]

        preview_response = self.preview_annotations(
            self.user, self.source, cpc_files)

        # TODO: The form's error handling should be improved so that the
        # message is "1.cpc: The submitted file is empty." instead.
        self.assertDictEqual(
            preview_response.json(),
            dict(error="The submitted file is empty."),
        )


class QueriesPerPointTest(
    UploadAnnotationsQueriesPerPointTest, UploadAnnotationsCpcTestMixin
):

    def test(self):
        point_data = [
            [column, row]
            # 100 points per image
            for column, row in self.point_positions()
        ]
        label_codes = self.label_codes()

        cpc_files = []
        for stem in ['1', '2', '3']:
            image_label_codes = [next(label_codes) for _ in range(100)]
            annotation_data = [
                entry + [label_code]
                for entry, label_code in zip(point_data, image_label_codes)
            ]
            cpc_files.append(
                self.make_annotations_file(
                    self.image_dimensions,
                    f'{stem}.cpc',
                    fr'C:\Photos\{stem}.jpg',
                    annotation_data,
                )
            )

        # Number of queries should be less than the point count.
        with self.assert_queries_less_than(3*100):
            self.preview_annotations(
                self.user, self.source, cpc_files)
            self.upload_annotations(self.user, self.source)

        for image in [self.img1, self.img2, self.img3]:
            self.assertEqual(
                image.annotation_set.count(), 100,
                "Sanity check: should have 100 annotations per image")


class QueriesPerImageTest(
    UploadAnnotationsQueriesPerImageTest, UploadAnnotationsCpcTestMixin
):

    def test(self):
        point_data = [
            [column, row]
            # 1 point per image
            for column, row in self.point_positions()
        ]
        label_codes = self.label_codes()

        cpc_files = []
        for stem in [str(n) for n in range(1, 20+1)]:
            image_label_codes = [next(label_codes)]
            annotation_data = [
                entry + [label_code]
                for entry, label_code in zip(point_data, image_label_codes)
            ]
            cpc_files.append(
                self.make_annotations_file(
                    self.image_dimensions,
                    f'{stem}.cpc',
                    fr'C:\Photos\{stem}.jpg',
                    annotation_data,
                )
            )

        # Number of queries should be linear in image count, but with
        # not TOO large of a constant factor.
        # TODO: Improve this. At this time of writing, it can't get under
        #  40 queries per image.
        with self.assert_queries_less_than(20*50):
            self.preview_annotations(
                self.user, self.source, cpc_files)
            self.upload_annotations(self.user, self.source)

        for image in [self.images[0], self.images[10], self.images[19]]:
            self.assertEqual(
                image.annotation_set.count(), 1,
                "Sanity check: should have 1 annotation per image")
