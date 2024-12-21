# Tests that only really apply to CSV annotation uploads
# (not other annotation upload formats).

from django.core.files.base import ContentFile
from django.urls import reverse

from annotations.models import Annotation
from images.models import Point
from lib.tests.utils import ClientTest
from .utils import UploadAnnotationsCsvTestMixin


class AnnotationsCSVFormatTest(ClientTest, UploadAnnotationsCsvTestMixin):
    """
    Tests (mostly error cases) specific to CSV format.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)
        cls.labels = cls.create_labels(cls.user, ['A', 'B'], 'Group1')
        cls.create_labelset(cls.user, cls.source, cls.labels)

        cls.img1 = cls.upload_image(
            cls.user, cls.source,
            image_options=dict(filename='1.png', width=100, height=100))

    def check(self, preview_response, upload_response):

        self.assertDictEqual(
            preview_response.json(),
            dict(
                success=True,
                previewTable=[
                    dict(
                        name=self.img1.metadata.name,
                        link=reverse(
                            'annotation_tool',
                            kwargs=dict(image_id=self.img1.pk)),
                        createInfo="Will create 1 points, 1 annotations",
                    ),
                ],
                previewDetails=dict(
                    numImages=1,
                    totalPoints=1,
                    totalAnnotations=1,
                    numImagesWithExistingAnnotations=0,
                ),
            ),
        )
        self.assertDictEqual(upload_response.json(), dict(success=True))

        values_set = set(
            Point.objects.filter(image__in=[self.img1])
            .values_list('column', 'row', 'point_number', 'image_id'))
        self.assertSetEqual(values_set, {
            (60, 40, 1, self.img1.pk),
        })

        annotations = Annotation.objects.filter(image__in=[self.img1])
        values_set = set(
            (a.label_code, a.point.pk, a.image.pk)
            for a in annotations
        )
        self.assertSetEqual(values_set, {
            ('A', Point.objects.get(
                point_number=1, image=self.img1).pk, self.img1.pk),
        })

    def test_skipped_csv_columns(self):
        """
        The CSV can have column names that we don't recognize. Those columns
        will just be ignored.
        """
        rows = [
            ['Name', 'Column', 'Row', 'Annotator', 'Label code'],
            ['1.png', 60, 40, 'Jane', 'A'],
        ]
        csv_file = self.make_annotations_file('A.csv', rows)
        preview_response = self.preview_annotations(
            self.user, self.source, csv_file)
        upload_response = self.upload_annotations(self.user, self.source)

        self.check(preview_response, upload_response)

    def test_columns_different_order(self):
        """
        The CSV columns can be in a different order.
        """
        rows = [
            ['Row', 'Name', 'Label code', 'Column'],
            [40, '1.png', 'A', 60],
        ]
        csv_file = self.make_annotations_file('A.csv', rows)
        preview_response = self.preview_annotations(
            self.user, self.source, csv_file)
        upload_response = self.upload_annotations(self.user, self.source)

        self.check(preview_response, upload_response)

    def test_columns_different_case(self):
        """
        The CSV column names can use different upper/lower case and still
        be matched to the expected column names.
        """
        rows = [
            ['name', 'coLUmN', 'ROW', 'Label Code'],
            ['1.png', 60, 40, 'A'],
        ]
        csv_file = self.make_annotations_file('A.csv', rows)
        preview_response = self.preview_annotations(
            self.user, self.source, csv_file)
        upload_response = self.upload_annotations(self.user, self.source)

        self.check(preview_response, upload_response)

    def test_no_name_column(self):
        """
        No CSV columns correspond to the name field.
        """
        rows = [
            ['Column', 'Row', 'Label code'],
            [50, 50, 'A'],
            [60, 40, 'B'],
        ]
        csv_file = self.make_annotations_file('A.csv', rows)
        preview_response = self.preview_annotations(
            self.user, self.source, csv_file)

        self.assertDictEqual(
            preview_response.json(),
            dict(error="CSV must have a column called Name"),
        )

    def test_no_row_column(self):
        """
        No CSV columns correspond to the row field.
        """
        rows = [
            ['Name', 'Column', 'Label code'],
            ['1.png', 50, 'A'],
            ['1.png', 60, 'B'],
        ]
        csv_file = self.make_annotations_file('A.csv', rows)
        preview_response = self.preview_annotations(
            self.user, self.source, csv_file)

        self.assertDictEqual(
            preview_response.json(),
            dict(error="CSV must have a column called Row"),
        )

    def test_no_column_column(self):
        """
        No CSV columns correspond to the column field.
        """
        rows = [
            ['Name', 'Row'],
            ['1.png', 50],
            ['1.png', 40],
        ]
        csv_file = self.make_annotations_file('A.csv', rows)
        preview_response = self.preview_annotations(
            self.user, self.source, csv_file)

        self.assertDictEqual(
            preview_response.json(),
            dict(error="CSV must have a column called Column"),
        )

    def test_missing_row(self):
        """
        A row is missing the row field.
        """
        rows = [
            ['Name', 'Column', 'Row'],
            ['1.png', 50, 50],
            ['1.png', 60, ''],
        ]
        csv_file = self.make_annotations_file('A.csv', rows)
        preview_response = self.preview_annotations(
            self.user, self.source, csv_file)

        self.assertDictEqual(
            preview_response.json(),
            dict(error="CSV row 3: Must have a value for Row"),
        )

    def test_missing_column(self):
        """
        A row is missing the column field.
        """
        rows = [
            ['Name', 'Column', 'Row'],
            ['1.png', '', 50],
            ['1.png', 60, 40],
        ]
        csv_file = self.make_annotations_file('A.csv', rows)
        preview_response = self.preview_annotations(
            self.user, self.source, csv_file)

        self.assertDictEqual(
            preview_response.json(),
            dict(error="CSV row 2: Must have a value for Column"),
        )

    def test_label_id(self):
        """
        Label ID instead of label code.
        """
        rows = [
            ['Name', 'Column', 'Row', 'Label ID'],
            ['1.png', 60, 40, self.labels.get(name='A').pk],
        ]
        csv_file = self.make_annotations_file('A.csv', rows)
        preview_response = self.preview_annotations(
            self.user, self.source, csv_file)
        upload_response = self.upload_annotations(self.user, self.source)

        self.check(preview_response, upload_response)

    def test_label_id_non_integer(self):
        rows = [
            ['Name', 'Column', 'Row', 'Label ID'],
            ['1.png', 60, 40, 'A'],
        ]
        csv_file = self.make_annotations_file('A.csv', rows)
        preview_response = self.preview_annotations(
            self.user, self.source, csv_file)

        self.assertDictEqual(
            preview_response.json(),
            dict(error="For image 1.png, point 1:"
                       " Label ID should be a positive integer, not A"),
        )

    def test_label_id_not_in_labelset(self):
        # This global label exists, but isn't in the labelset.
        label_c = self.create_labels(self.user, ['C'], 'Group1').get(name='C')

        rows = [
            ['Name', 'Column', 'Row', 'Label ID'],
            ['1.png', 60, 40, label_c.pk],
        ]
        csv_file = self.make_annotations_file('A.csv', rows)
        preview_response = self.preview_annotations(
            self.user, self.source, csv_file)

        self.assertDictEqual(
            preview_response.json(),
            dict(error=f"For image 1.png, point 1: No label of ID {label_c.pk}"
                       " found in this source's labelset"),
        )

    def test_label_legacy(self):
        """
        Legacy column name for label code.
        """
        rows = [
            ['Name', 'Column', 'Row', 'Label'],
            ['1.png', 60, 40, 'A'],
        ]
        csv_file = self.make_annotations_file('A.csv', rows)
        preview_response = self.preview_annotations(
            self.user, self.source, csv_file)
        upload_response = self.upload_annotations(self.user, self.source)

        self.check(preview_response, upload_response)

    def test_multiple_label_columns(self):
        """
        Multiple columns corresponding to the label.
        """
        rows = [
            ['Name', 'Column', 'Row', 'Label code', 'Label ID'],
            ['1.png', '', 50, 'A', self.labels.get(name='A').pk],
            ['1.png', 60, 40, 'B', self.labels.get(name='B').pk],
        ]
        csv_file = self.make_annotations_file('A.csv', rows)
        preview_response = self.preview_annotations(
            self.user, self.source, csv_file)

        self.assertDictEqual(
            preview_response.json(),
            dict(error="CSV cannot have multiple columns specifying the label"
                       " (Label code, Label ID)"),
        )

    def test_multiple_label_columns_case_insensitive_and_partly_blank(self):
        rows = [
            ['Name', 'Column', 'Row', 'LABEL', 'label code'],
            ['1.png', '', 50, 'A', ''],
            ['1.png', 60, 40, '', 'B'],
        ]
        csv_file = self.make_annotations_file('A.csv', rows)
        preview_response = self.preview_annotations(
            self.user, self.source, csv_file)

        self.assertDictEqual(
            preview_response.json(),
            dict(error="CSV cannot have multiple columns specifying the label"
                       " (Label, Label code)"),
        )

    def test_field_with_newline(self):
        """Field value with a newline character in it (within quotation marks).
        There's no reason to have this in any of the recognized columns, so we
        use an extra ignored column to test."""
        content = (
            'Name,Column,Row,Comments,Label code'
            '\n1.png,60,40,"Here are\nsome comments.",A'
        )
        csv_file = ContentFile(content, name='A.csv')
        preview_response = self.preview_annotations(
            self.user, self.source, csv_file)
        upload_response = self.upload_annotations(self.user, self.source)

        self.check(preview_response, upload_response)

    def test_field_with_surrounding_quotes(self):
        content = (
            'Name,Column,Row,Label code'
            '\n"1.png","60","40","A"'
        )
        csv_file = ContentFile(content, name='A.csv')
        preview_response = self.preview_annotations(
            self.user, self.source, csv_file)
        upload_response = self.upload_annotations(self.user, self.source)

        self.check(preview_response, upload_response)

    def test_field_with_surrounding_whitespace(self):
        """Strip whitespace surrounding the CSV values."""
        content = (
            'Name ,\tColumn\t,  Row,\tLabel code    '
            '\n\t1.png,    60   , 40,A'
        )
        csv_file = ContentFile(content, name='A.csv')
        preview_response = self.preview_annotations(
            self.user, self.source, csv_file)
        upload_response = self.upload_annotations(self.user, self.source)

        self.check(preview_response, upload_response)

    def test_non_csv(self):
        """
        Do at least basic detection of non-CSV files.
        """
        f = self.sample_image_as_file('A.jpg')
        preview_response = self.preview_annotations(
            self.user, self.source, f)

        self.assertDictEqual(
            preview_response.json(),
            dict(
                error="The selected file is not a CSV file.",
            ),
        )
