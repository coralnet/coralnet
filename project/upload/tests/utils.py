from abc import ABC
import csv
from io import StringIO

from django.core.files.base import ContentFile
from django.urls import reverse

from accounts.utils import get_imported_user
from annotations.model_utils import AnnotationArea
from annotations.models import Annotation
from annotations.tests.utils import AnnotationHistoryTestMixin
from images.model_utils import PointGen
from images.models import Point
from lib.tests.utils import ClientTest


# Abstract class
class UploadAnnotationsTestMixin(ABC):

    @staticmethod
    def make_annotations_file(*args, **kwargs):
        raise NotImplementedError

    def preview_annotations(self, *args, **kwargs):
        raise NotImplementedError

    def upload_annotations(self, *args, **kwargs):
        raise NotImplementedError


class UploadAnnotationsCsvTestMixin(UploadAnnotationsTestMixin, ABC):

    @staticmethod
    def make_annotations_file(csv_filename, rows):
        stream = StringIO()
        writer = csv.writer(stream)
        for row in rows:
            writer.writerow(row)

        f = ContentFile(stream.getvalue(), name=csv_filename)
        return f

    def preview_annotations(self, user, source, csv_file):
        self.client.force_login(user)
        return self.client.post(
            reverse('upload_annotations_csv_preview_ajax', args=[source.pk]),
            {'csv_file': csv_file},
        )

    def upload_annotations(self, user, source):
        self.client.force_login(user)
        return self.client.post(
            reverse('upload_annotations_csv_confirm_ajax', args=[source.pk]),
        )


class UploadAnnotationsGeneralCasesTest(
        ClientTest, AnnotationHistoryTestMixin, ABC):
    """
    Testing general functionality for uploading annotations.
    This class is agnostic to the upload format. Subclasses may be
    format-specific, and must implement the actual test methods.
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

    def check_points_only(self, preview_response, upload_response):

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
                        createInfo="Will create 5 points, 0 annotations",
                    ),
                    dict(
                        name=self.img2.metadata.name,
                        link=reverse(
                            'annotation_tool',
                            kwargs=dict(image_id=self.img2.pk)),
                        createInfo="Will create 3 points, 0 annotations",
                    ),
                ],
                previewDetails=dict(
                    numImages=2,
                    totalPoints=8,
                    totalAnnotations=0,
                    numImagesWithExistingAnnotations=0,
                ),
            ),
        )

        self.assertDictEqual(upload_response.json(), dict(success=True))

        values_set = set(
            Point.objects.filter(image__in=[self.img1, self.img2])
            .values_list('column', 'row', 'point_number', 'image_id'))
        self.assertSetEqual(values_set, {
            (50, 50, 1, self.img1.pk),
            (60, 40, 2, self.img1.pk),
            (70, 30, 3, self.img1.pk),
            (80, 20, 4, self.img1.pk),
            (90, 10, 5, self.img1.pk),
            (0,  0,  1, self.img2.pk),
            (199, 99, 2, self.img2.pk),
            (44, 44, 3, self.img2.pk),
        })

        self.img1.refresh_from_db()
        self.assertEqual(
            self.img1.point_generation_method,
            PointGen(type='imported', points=5).db_value)
        self.assertEqual(
            self.img1.metadata.annotation_area,
            AnnotationArea(type=AnnotationArea.TYPE_IMPORTED).db_value)

        self.img2.refresh_from_db()
        self.assertEqual(
            self.img2.point_generation_method,
            PointGen(type='imported', points=3).db_value)
        self.assertEqual(
            self.img2.metadata.annotation_area,
            AnnotationArea(type=AnnotationArea.TYPE_IMPORTED).db_value)

    def check_all_annotations(self, preview_response, upload_response):

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
                        createInfo="Will create 2 points, 2 annotations",
                    ),
                    dict(
                        name=self.img2.metadata.name,
                        link=reverse(
                            'annotation_tool',
                            kwargs=dict(image_id=self.img2.pk)),
                        createInfo="Will create 2 points, 2 annotations",
                    ),
                ],
                previewDetails=dict(
                    numImages=2,
                    totalPoints=4,
                    totalAnnotations=4,
                    numImagesWithExistingAnnotations=0,
                ),
            ),
        )

        self.assertDictEqual(upload_response.json(), dict(success=True))

        values_set = set(
            Point.objects.filter(image__in=[self.img1, self.img2])
            .values_list('column', 'row', 'point_number', 'image_id'))
        self.assertSetEqual(values_set, {
            (50, 50, 1, self.img1.pk),
            (60, 40, 2, self.img1.pk),
            (70, 30, 1, self.img2.pk),
            (80, 20, 2, self.img2.pk),
        })

        annotations = Annotation.objects.filter(
            image__in=[self.img1, self.img2])
        values_set = set(
            (a.label_code, a.point.pk, a.image.pk)
            for a in annotations
        )
        self.assertSetEqual(values_set, {
            ('A', Point.objects.get(
                point_number=1, image=self.img1).pk, self.img1.pk),
            ('B', Point.objects.get(
                point_number=2, image=self.img1).pk, self.img1.pk),
            ('A', Point.objects.get(
                point_number=1, image=self.img2).pk, self.img2.pk),
            ('A', Point.objects.get(
                point_number=2, image=self.img2).pk, self.img2.pk),
        })
        for annotation in annotations:
            self.assertEqual(annotation.source.pk, self.source.pk)
            self.assertEqual(annotation.user.pk, get_imported_user().pk)
            self.assertEqual(annotation.robot_version, None)
            self.assertLess(
                self.source.create_date, annotation.annotation_date)

    def check_some_annotations(self, preview_response, upload_response):

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
                        createInfo="Will create 2 points, 2 annotations",
                    ),
                    dict(
                        name=self.img2.metadata.name,
                        link=reverse(
                            'annotation_tool',
                            kwargs=dict(image_id=self.img2.pk)),
                        createInfo="Will create 2 points, 1 annotations",
                    ),
                    dict(
                        name=self.img3.metadata.name,
                        link=reverse(
                            'annotation_tool',
                            kwargs=dict(image_id=self.img3.pk)),
                        createInfo="Will create 2 points, 0 annotations",
                    ),
                ],
                previewDetails=dict(
                    numImages=3,
                    totalPoints=6,
                    totalAnnotations=3,
                    numImagesWithExistingAnnotations=0,
                ),
            ),
        )

        self.assertDictEqual(upload_response.json(), dict(success=True))

        values_set = set(
            Point.objects.filter(
                image__in=[self.img1, self.img2, self.img3])
            .values_list('column', 'row', 'point_number', 'image_id'))
        self.assertSetEqual(values_set, {
            (50, 50, 1, self.img1.pk),
            (60, 40, 2, self.img1.pk),
            (70, 30, 1, self.img2.pk),
            (80, 20, 2, self.img2.pk),
            (70, 30, 1, self.img3.pk),
            (80, 20, 2, self.img3.pk),
        })

        annotations = Annotation.objects.filter(
            image__in=[self.img1, self.img2, self.img3])
        values_set = set(
            (a.label_code, a.point.pk, a.image.pk)
            for a in annotations
        )
        self.assertSetEqual(values_set, {
            ('A', Point.objects.get(
                point_number=1, image=self.img1).pk, self.img1.pk),
            ('B', Point.objects.get(
                point_number=2, image=self.img1).pk, self.img1.pk),
            ('A', Point.objects.get(
                point_number=1, image=self.img2).pk, self.img2.pk),
        })
        for annotation in annotations:
            self.assertEqual(annotation.source.pk, self.source.pk)
            self.assertEqual(annotation.user.pk, get_imported_user().pk)
            self.assertEqual(annotation.robot_version, None)
            self.assertLess(
                self.source.create_date, annotation.annotation_date)

    def check_overwrite_annotations(self, preview_response, upload_response):

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
                        createInfo="Will create 2 points, 2 annotations",
                        deleteInfo="Will delete 2 existing annotations",
                    ),
                    dict(
                        name=self.img2.metadata.name,
                        link=reverse(
                            'annotation_tool',
                            kwargs=dict(image_id=self.img2.pk)),
                        createInfo="Will create 2 points, 0 annotations",
                        deleteInfo="Will delete 1 existing annotations",
                    ),
                    dict(
                        name=self.img3.metadata.name,
                        link=reverse(
                            'annotation_tool',
                            kwargs=dict(image_id=self.img3.pk)),
                        createInfo="Will create 2 points, 2 annotations",
                    ),
                ],
                previewDetails=dict(
                    numImages=3,
                    totalPoints=6,
                    totalAnnotations=4,
                    numImagesWithExistingAnnotations=2,
                ),
            ),
        )

        self.assertDictEqual(upload_response.json(), dict(success=True))

        values_set = set(
            Point.objects.filter(
                image__in=[self.img1, self.img2, self.img3])
            .values_list('column', 'row', 'point_number', 'image_id'))
        self.assertSetEqual(values_set, {
            (10, 10, 1, self.img1.pk),
            (20, 20, 2, self.img1.pk),
            (30, 30, 1, self.img2.pk),
            (40, 40, 2, self.img2.pk),
            (50, 50, 1, self.img3.pk),
            (60, 60, 2, self.img3.pk),
        })

        annotations = Annotation.objects.filter(
            image__in=[self.img1, self.img2, self.img3])
        values_set = set(
            (a.label_code, a.point.pk, a.image.pk)
            for a in annotations
        )
        self.assertSetEqual(values_set, {
            ('A', Point.objects.get(
                point_number=1, image=self.img1).pk, self.img1.pk),
            ('A', Point.objects.get(
                point_number=2, image=self.img1).pk, self.img1.pk),
            ('A', Point.objects.get(
                point_number=1, image=self.img3).pk, self.img3.pk),
            ('B', Point.objects.get(
                point_number=2, image=self.img3).pk, self.img3.pk),
        })

        self.img1.annoinfo.refresh_from_db()
        self.assertIsNotNone(self.img1.annoinfo.last_annotation)
        self.img2.annoinfo.refresh_from_db()
        self.assertIsNone(self.img2.annoinfo.last_annotation)
        self.img3.annoinfo.refresh_from_db()
        self.assertIsNotNone(self.img3.annoinfo.last_annotation)

    def check_label_codes_different_case(
            self, preview_response, upload_response):

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
            ('Abc', Point.objects.get(
                point_number=1, image=self.img1).pk, self.img1.pk),
        })

    def check_skipped_filenames(self, preview_response, upload_response):

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
            (50, 50, 1, self.img1.pk),
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

    def check_annotation_history(self):

        response = self.view_history(self.user, img=self.img1)
        self.assert_history_table_equals(
            response,
            [
                ['Point 1: A<br/>Point 3: B', 'Imported'],
            ]
        )

    def check_transaction_rollback(self):

        # No annotations should be saved
        annotations = Annotation.objects.filter(image__in=[self.img1])
        values_set = set(
            (a.label_code, a.point.pk, a.image.pk)
            for a in annotations
        )
        self.assertSetEqual(values_set, set())

        # No history should be saved
        response = self.view_history(self.user, img=self.img1)
        self.assert_history_table_equals(
            response,
            []
        )


class UploadAnnotationsMultipleSourcesTest(ClientTest, ABC):
    """
    Test involving multiple sources.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)
        cls.source2 = cls.create_source(cls.user)

        labels = cls.create_labels(cls.user, ['A', 'B'], 'Group1')
        cls.create_labelset(cls.user, cls.source, labels)
        cls.create_labelset(cls.user, cls.source2, labels)

        cls.img1_s1 = cls.upload_image(
            cls.user, cls.source,
            image_options=dict(filename='1.png', width=100, height=100))
        cls.img1_s2 = cls.upload_image(
            cls.user, cls.source2,
            image_options=dict(filename='1.png', width=100, height=100))
        cls.img2_s2 = cls.upload_image(
            cls.user, cls.source2,
            image_options=dict(filename='2.png', width=100, height=100))

        cls.image_dimensions = (100, 100)

    def check_other_sources_unaffected(
            self, preview_response, upload_response):

        # Check source 1 responses

        self.assertDictEqual(
            preview_response.json(),
            dict(
                success=True,
                previewTable=[
                    dict(
                        name=self.img1_s1.metadata.name,
                        link=reverse(
                            'annotation_tool',
                            kwargs=dict(image_id=self.img1_s1.pk)),
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

        # Check source 1 objects

        values_set = set(
            Point.objects.filter(image__in=[self.img1_s1])
            .values_list('column', 'row', 'point_number', 'image_id'))
        self.assertSetEqual(values_set, {
            (50, 50, 1, self.img1_s1.pk),
        })

        annotations = Annotation.objects.filter(image__in=[self.img1_s1])
        values_set = set(
            (a.label_code, a.point.pk, a.image.pk)
            for a in annotations
        )
        self.assertSetEqual(values_set, {
            ('A', Point.objects.get(
                point_number=1, image=self.img1_s1).pk, self.img1_s1.pk),
        })

        # Check source 2 objects

        values_set = set(
            Point.objects.filter(image__in=[self.img1_s2, self.img2_s2])
            .values_list('column', 'row', 'point_number', 'image_id'))
        self.assertSetEqual(values_set, {
            (10, 10, 1, self.img1_s2.pk),
            (20, 20, 2, self.img1_s2.pk),
            (15, 15, 1, self.img2_s2.pk),
            (25, 25, 2, self.img2_s2.pk),
        })

        annotations = Annotation.objects.filter(
            image__in=[self.img1_s2, self.img2_s2])
        values_set = set(
            (a.label_code, a.point.pk, a.image.pk)
            for a in annotations
        )
        self.assertSetEqual(values_set, {
            ('B', Point.objects.get(
                point_number=1, image=self.img1_s2).pk, self.img1_s2.pk),
            ('B', Point.objects.get(
                point_number=2, image=self.img1_s2).pk, self.img1_s2.pk),
            ('A', Point.objects.get(
                point_number=1, image=self.img2_s2).pk, self.img2_s2.pk),
            ('A', Point.objects.get(
                point_number=2, image=self.img2_s2).pk, self.img2_s2.pk),
        })


class UploadAnnotationsFormatTest(ClientTest, ABC):
    """
    Tests (mostly error cases) related to file format, which apply regardless
    of what the format specifically is.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)

        labels = cls.create_labels(cls.user, ['A', 'B'], 'Group1')
        cls.create_labelset(cls.user, cls.source, labels)
        # Unicode custom label code
        local_label = cls.source.labelset.locallabel_set.get(code='B')
        local_label.code = 'い'
        local_label.save()

        cls.img1 = cls.upload_image(
            cls.user, cls.source,
            image_options=dict(filename='1.png', width=100, height=100))
        cls.imgA = cls.upload_image(
            cls.user, cls.source,
            image_options=dict(filename='あ.png', width=100, height=100))

        cls.image_dimensions = (100, 100)

    def check(self, preview_response, upload_response, img, label_code):

        self.assertDictEqual(
            preview_response.json(),
            dict(
                success=True,
                previewTable=[
                    dict(
                        name=img.metadata.name,
                        link=reverse(
                            'annotation_tool',
                            kwargs=dict(image_id=img.pk)),
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
            Point.objects.filter(image__in=[img])
            .values_list('column', 'row', 'point_number', 'image_id'))
        self.assertSetEqual(values_set, {
            (50, 50, 1, img.pk),
        })

        annotations = Annotation.objects.filter(image__in=[img])
        values_set = set(
            (a.label_code, a.point.pk, a.image.pk)
            for a in annotations
        )
        self.assertSetEqual(values_set, {
            (label_code, Point.objects.get(
                point_number=1, image=img).pk, img.pk),
        })
