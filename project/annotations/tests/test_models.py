from django_migration_testcase import MigrationTest

from accounts.utils import get_robot_user
from images.models import Point
from lib.tests.utils import ClientTest
from lib.tests.utils_data import sample_image_as_file
from ..model_utils import (
    ImageAnnoStatuses,
    image_annotation_status,
    image_annotation_verbose_status,
)
from ..models import Annotation


image_defaults = dict(
    original_width=32,
    original_height=32,
)


class ImageStatusLogicTest(ClientTest):

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
            self.image.annotation_set.exclude(
                point__point_number__in=unconfirmed).delete()
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
        self.image.point_set.delete()
        self.do_test(
            'unclassified', 'not_started',
            unconfirmed=[], confirmed=[])


class AnnoInfoUpdateTest(ClientTest):

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

    def assertStatusEqual(self, expected_status, msg=None):
        self.image.annoinfo.refresh_from_db()
        self.assertEqual(
            self.image.annoinfo.status, expected_status, msg=msg)

    def test_point_save_delete(self):
        self.assertStatusEqual('confirmed', msg="Sanity check")

        point = Point(image=self.image, row=10, column=10, point_number=4)
        point.save()
        self.assertStatusEqual('unclassified')

        point.delete()
        self.assertStatusEqual('confirmed')

    def test_point_bulk_create_delete(self):
        self.assertStatusEqual('confirmed', msg="Sanity check")

        points = [
            Point(image=self.image, row=10, column=10, point_number=4),
            Point(image=self.image, row=20, column=20, point_number=5),
        ]
        points = Point.objects.bulk_create(points)
        self.assertStatusEqual('unclassified')

        Point.objects.filter(pk__in=[p.pk for p in points]).delete()
        self.assertStatusEqual('confirmed')

    def test_annotation_save(self):
        self.assertStatusEqual('confirmed', msg="Sanity check")

        annotation = Annotation.objects.get(
            image=self.image, point__point_number=1)
        annotation.user = get_robot_user()
        annotation.save()
        self.assertStatusEqual('unconfirmed')

    def test_annotation_delete(self):
        self.assertStatusEqual('confirmed', msg="Sanity check")

        annotation = Annotation.objects.get(
            image=self.image, point__point_number=1)
        annotation.delete()
        self.assertStatusEqual('unclassified')

    def test_annotation_bulk_delete(self):
        self.assertStatusEqual('confirmed', msg="Sanity check")

        self.image.annotation_set.delete()
        self.assertStatusEqual('unclassified')

        # Whenever django-reversion is replaced and bulk creation of
        # Annotations is viable again, the below code can be used to test
        # bulk creation.

        # annotations = [
        #     Annotation(
        #         source=self.image.source,
        #         image=self.image,
        #         point=self.image.point_set.get(point_number=1),
        #         label=self.labels.get(name='A'),
        #         user=get_robot_user(),
        #     ),
        #     Annotation(
        #         source=self.image.source,
        #         image=self.image,
        #         point=self.image.point_set.get(point_number=2),
        #         label=self.labels.get(name='A'),
        #         user=get_robot_user(),
        #     ),
        #     Annotation(
        #         source=self.image.source,
        #         image=self.image,
        #         point=self.image.point_set.get(point_number=3),
        #         label=self.labels.get(name='A'),
        #         user=get_robot_user(),
        #     ),
        # ]
        # Annotation.objects.bulk_create(annotations)
        # self.assertStatusEqual('unconfirmed')
