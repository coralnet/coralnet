from django.conf import settings

from accounts.utils import get_robot_user
from images.models import Image, Point
from lib.tests.utils import CnMigrationTest, CnStandardTest
from lib.tests.utils_data import sample_image_as_file
from ..model_utils import (
    image_annotation_status,
    image_annotation_verbose_status,
)
from ..models import Annotation
from .utils import (
    controlled_sort_hashes, EXPECTED_HASHES)


image_defaults = dict(
    original_width=32,
    original_height=32,
)


class ImageStatusLogicTest(CnStandardTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user,
            default_point_generation_method=dict(type='simple', points=3),
        )

        cls.classifier = cls.create_robot(cls.source)
        cls.image = cls.upload_image(cls.user, cls.source)

        cls.labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, cls.labels)

    def do_test(
        self,
        expected_status,
        expected_verbose_status,
        unconfirmed: list[int],
        confirmed: list[int],
    ):
        if unconfirmed:
            # Adding robot annotations is all-or-nothing, so we add for
            # all first, then delete the ones we don't want for the
            # purposes of the test.
            self.add_robot_annotations(self.classifier, self.image)
            for annotation in self.image.annotation_set.exclude(
                point__point_number__in=unconfirmed
            ):
                annotation.delete()
        if confirmed:
            self.add_annotations(
                self.user, self.image,
                dict([(point_num, 'A') for point_num in confirmed]),
            )

        self.assertEqual(
            image_annotation_status(self.image),
            expected_status,
        )
        self.assertEqual(
            image_annotation_verbose_status(self.image),
            expected_verbose_status,
        )

    def test_has_unclassified_unconfirmed_confirmed(self):
        self.do_test(
            'unclassified', 'partially_confirmed',
            unconfirmed=[2], confirmed=[3])

    def test_has_unclassified_unconfirmed(self):
        self.do_test(
            'unclassified', 'not_started',
            unconfirmed=[2, 3], confirmed=[])

    def test_has_unclassified_confirmed(self):
        self.do_test(
            'unclassified', 'partially_confirmed',
            unconfirmed=[], confirmed=[2, 3])

    def test_has_unclassified(self):
        self.do_test(
            'unclassified', 'not_started',
            unconfirmed=[], confirmed=[])

    def test_has_unconfirmed_confirmed(self):
        self.do_test(
            'unconfirmed', 'partially_confirmed',
            unconfirmed=[1, 2], confirmed=[3])

    def test_has_unconfirmed(self):
        self.do_test(
            'unconfirmed', 'unconfirmed',
            unconfirmed=[1, 2, 3], confirmed=[])

    def test_has_confirmed(self):
        self.do_test(
            'confirmed', 'confirmed',
            unconfirmed=[], confirmed=[1, 2, 3])

    def test_has_no_points(self):
        Point.objects.delete_for_image(self.image)
        self.do_test(
            'unclassified', 'not_started',
            unconfirmed=[], confirmed=[])


class AnnoInfoUpdateTest(CnStandardTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user,
            default_point_generation_method=dict(type='simple', points=3),
        )

        cls.labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, cls.labels)

        cls.image = cls.upload_image(cls.user, cls.source)
        cls.add_annotations(cls.user, cls.image)
        cls.image2 = cls.upload_image(cls.user, cls.source)
        cls.add_robot_annotations(cls.create_robot(cls.source), cls.image2)

    def assert_status_equal(self, expected_status, msg=None):
        self.image.annoinfo.refresh_from_db()
        self.assertEqual(
            self.image.annoinfo.status, expected_status, msg=msg)

    def assert_image2_status_equal(self, expected_status, msg=None):
        self.image2.annoinfo.refresh_from_db()
        self.assertEqual(
            self.image2.annoinfo.status, expected_status, msg=msg)

    def test_point_save_delete(self):
        self.assert_status_equal('confirmed', msg="Sanity check")

        point = Point(image=self.image, row=10, column=10, point_number=4)
        point.save()
        self.assert_status_equal('unclassified')

        point.delete()
        self.assert_status_equal('confirmed')

    def test_point_bulk_create(self):
        self.assert_status_equal('confirmed', msg="Sanity check")

        points = [
            Point(image=self.image, row=10, column=10, point_number=4),
            Point(image=self.image, row=20, column=20, point_number=5),
        ]
        Point.objects.bulk_create(points)
        self.assert_status_equal('unclassified')

    def test_point_delete_for_image(self):
        self.assert_status_equal('confirmed', msg="Sanity check")

        Point.objects.delete_for_image(self.image)
        self.assertEqual(self.image.point_set.count(), 0, msg="Sanity check")
        self.assert_status_equal('unclassified')

    def test_annotation_save(self):
        self.assert_status_equal('confirmed', msg="Sanity check")

        annotation = Annotation.objects.get(
            image=self.image, point__point_number=1)
        annotation.user = get_robot_user()
        annotation.save()
        self.assert_status_equal('unconfirmed')

    def test_annotation_delete(self):
        self.assert_status_equal('confirmed', msg="Sanity check")

        annotation = Annotation.objects.get(
            image=self.image, point__point_number=1)
        annotation.delete()
        self.assert_status_equal('unclassified')

    def test_annotations_delete_for_image(self):
        self.assert_status_equal('confirmed', msg="Sanity check")

        Annotation.objects.delete_for_image(self.image)
        self.assert_status_equal('unclassified')

    def test_annotations_delete_for_image_set(self):
        self.assert_status_equal('confirmed', msg="Sanity check")
        self.assert_image2_status_equal('unconfirmed', msg="Sanity check")

        Annotation.objects.delete_for_image_set(Image.objects.all())
        self.assert_status_equal('unclassified')
        self.assert_image2_status_equal('unclassified')

    def test_annotations_delete_unconfirmed_for_source(self):
        self.assert_status_equal('confirmed', msg="Sanity check")
        self.assert_image2_status_equal('unconfirmed', msg="Sanity check")

        Annotation.objects.delete_unconfirmed_for_source(self.source)
        self.assert_status_equal('confirmed')
        self.assert_image2_status_equal('unclassified')

    def test_annotation_bulk_create_for_image(self):
        self.assert_status_equal('confirmed', msg="Sanity check")

        Annotation.objects.delete_for_image(self.image)
        self.assert_status_equal('unclassified', msg="Sanity check")

        annotations = [
            Annotation(
                point=self.image.point_set.get(point_number=point_number),
                label=self.labels.get(name='A'),
                user=self.user,
                source=self.image.source,
            )
            for point_number in [1,2,3]
        ]
        Annotation.objects.bulk_create_for_image(annotations, self.image)
        self.assert_status_equal('confirmed')


class AnnotationCreateTest(CnStandardTest):
    """
    Aspects of Annotation creation methods other than annoinfo fields.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user,
            default_point_generation_method=dict(type='simple', points=3),
        )

        cls.labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, cls.labels)

        cls.image = cls.upload_image(cls.user, cls.source)

    def test_image_fks_present(self):
        annotations = [
            Annotation(
                point=self.image.point_set.get(point_number=point_number),
                label=self.labels.get(name='A'),
                user=self.user,
                image=self.image,
                source=self.source,
            )
            for point_number in [1,2,3]
        ]
        Annotation.objects.bulk_create_for_image(annotations, self.image)

        self.assertEqual(self.image.annotation_set.count(), 3)

    def test_image_fks_present_but_mismatched(self):
        image2 = self.upload_image(self.user, self.source)

        annotations = [
            Annotation(
                point=image2.point_set.get(point_number=point_number),
                label=self.labels.get(name='A'),
                user=self.user,
                image=image2,
                source=self.source,
            )
            for point_number in [1,2,3]
        ]
        with self.assertRaises(ValueError) as cm:
            Annotation.objects.bulk_create_for_image(annotations, self.image)

        self.assertEqual(
            str(cm.exception),
            f"Args have clashing Images:"
            f" ID {image2.pk} vs. ID {self.image.pk}")

        self.assertEqual(self.image.annotation_set.count(), 0)

    def test_image_fks_present_but_source_mismatched(self):
        source2 = self.create_source(self.user)

        annotations = [
            Annotation(
                point=self.image.point_set.get(point_number=point_number),
                label=self.labels.get(name='A'),
                user=self.user,
                image=self.image,
                source=source2,
            )
            for point_number in [1,2,3]
        ]
        with self.assertRaises(ValueError) as cm:
            Annotation.objects.bulk_create_for_image(annotations, self.image)

        self.assertEqual(
            str(cm.exception),
            f"Args have clashing Sources:"
            f" ID {source2.pk} vs. ID {self.source.pk}")

        self.assertEqual(self.image.annotation_set.count(), 0)

    def test_image_fks_absent(self):
        annotations = [
            Annotation(
                point=self.image.point_set.get(point_number=point_number),
                label=self.labels.get(name='A'),
                user=self.user,
                source=self.source,
            )
            for point_number in [1,2,3]
        ]
        Annotation.objects.bulk_create_for_image(annotations, self.image)

        self.assertEqual(self.image.annotation_set.count(), 3)

    def test_image_fks_absent_but_source_mismatched(self):
        source2 = self.create_source(self.user)

        annotations = [
            Annotation(
                point=self.image.point_set.get(point_number=point_number),
                label=self.labels.get(name='A'),
                user=self.user,
                source=source2,
            )
            for point_number in [1,2,3]
        ]
        with self.assertRaises(ValueError) as cm:
            Annotation.objects.bulk_create_for_image(annotations, self.image)

        self.assertEqual(
            str(cm.exception),
            f"Args have clashing Sources:"
            f" ID {source2.pk} vs. ID {self.source.pk}")

        self.assertEqual(self.image.annotation_set.count(), 0)

    def test_bulk_create_error(self):
        annotations = [
            Annotation(
                point=self.image.point_set.get(point_number=point_number),
                label=self.labels.get(name='A'),
                user=self.user,
                image=self.image,
                source=self.source,
            )
            for point_number in [1,2,3]
        ]
        with self.assertRaises(TypeError) as cm:
            Annotation.objects.bulk_create(annotations)

        self.assertEqual(
            str(cm.exception),
            "Use bulk_create_for_image() instead."
            " Or create the Annotations one by one.")

        self.assertEqual(self.image.annotation_set.count(), 0)


class ScrambledSortKeyTest(CnStandardTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)
        cls.labels = cls.create_labels(cls.user, ['A', 'B'], "Group1")
        cls.create_labelset(cls.user, cls.source, cls.labels)
        cls.source.refresh_from_db()

        cls.image = cls.upload_image(cls.user, cls.source)

    def test_basic(self):
        with controlled_sort_hashes(seed=10, pk_sequence=[5,6]):
            anno_1 = Annotation(
                user=self.user, source=self.source, image=self.image,
                point=self.image.point_set.get(point_number=1),
                label=self.labels.get(default_code='A'),
            )
            anno_1.save()
            anno_2 = Annotation(
                user=self.user, source=self.source, image=self.image,
                point=self.image.point_set.get(point_number=2),
                label=self.labels.get(default_code='B'),
            )
            anno_2.save()

        anno_1.refresh_from_db()
        self.assertEqual(anno_1.scrambled_sort_key, EXPECTED_HASHES[15])
        anno_2.refresh_from_db()
        self.assertEqual(anno_2.scrambled_sort_key, EXPECTED_HASHES[16])

    def test_id_larger_than_max_small_integer(self):
        """
        If the annotation ID is greater than the max small integer value,
        it should get modded by 2**16 before continuing as normal.
        """
        pk_sequence = [(65536*10)+6, (65536*10)+7]

        with controlled_sort_hashes(seed=10, pk_sequence=pk_sequence):
            anno_1 = Annotation(
                user=self.user, source=self.source, image=self.image,
                point=self.image.point_set.get(point_number=1),
                label=self.labels.get(default_code='A'),
            )
            anno_1.save()
            anno_2 = Annotation(
                user=self.user, source=self.source, image=self.image,
                point=self.image.point_set.get(point_number=2),
                label=self.labels.get(default_code='B'),
            )
            anno_2.save()

        anno_1.refresh_from_db()
        self.assertEqual(anno_1.scrambled_sort_key, EXPECTED_HASHES[16])
        anno_2.refresh_from_db()
        self.assertEqual(anno_2.scrambled_sort_key, EXPECTED_HASHES[17])


class PopulateConfirmedMigrationTest(CnMigrationTest):

    before = [
        ('accounts', '0001_squashed_0012_field_string_attributes_to_unicode'),
        ('annotations', '0039_annotation_confirmed'),
    ]
    after = [('annotations', '0040_annotation_confirmed_populate')]

    def test_migration(self):
        User = self.get_model_before('auth.User')
        Source = self.get_model_before('sources.Source')
        LabelGroup = self.get_model_before('labels.LabelGroup')
        Label = self.get_model_before('labels.Label')
        Image = self.get_model_before('images.Image')
        Point = self.get_model_before('images.Point')
        Annotation = self.get_model_before('annotations.Annotation')

        user1 = User(username='user1')
        user1.save()
        user2 = User(username='user2')
        user2.save()
        robot_user = User.objects.get(username=settings.ROBOT_USERNAME)

        group = LabelGroup(name="Group 1")
        group.save()
        label = Label(group=group, name="A", default_code='A')
        label.save()

        source = Source(name="Test source")
        source.save()
        image = Image(
            source=source,
            original_file=sample_image_as_file('a.png'),
            uploaded_by=user1,
            point_generation_method=source.default_point_generation_method,
        )
        image.save()

        p1 = Point(image=image, row=1, column=1, point_number=1)
        p1.save()
        p2 = Point(image=image, row=2, column=2, point_number=2)
        p2.save()
        p3 = Point(image=image, row=3, column=3, point_number=3)
        p3.save()
        p4 = Point(image=image, row=4, column=4, point_number=4)
        p4.save()
        p5 = Point(image=image, row=5, column=5, point_number=5)
        p5.save()

        a1 = Annotation(
            point=p1, image=image, source=source, label=label, user=user1)
        a1.save()
        a2 = Annotation(
            point=p2, image=image, source=source, label=label, user=user1)
        a2.save()
        a3 = Annotation(
            point=p3, image=image, source=source, label=label, user=robot_user)
        a3.save()
        a4 = Annotation(
            point=p4, image=image, source=source, label=label, user=user2)
        a4.save()
        a5 = Annotation(
            point=p5, image=image, source=source, label=label, user=robot_user)
        a5.save()

        self.run_migration()

        Annotation = self.get_model_after('annotations.Annotation')

        self.assertTrue(
            Annotation.objects.get(pk=a1.pk).confirmed)
        self.assertTrue(
            Annotation.objects.get(pk=a2.pk).confirmed)
        self.assertFalse(
            Annotation.objects.get(pk=a3.pk).confirmed)
        self.assertTrue(
            Annotation.objects.get(pk=a4.pk).confirmed)
        self.assertFalse(
            Annotation.objects.get(pk=a5.pk).confirmed)
