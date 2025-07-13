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


class PopulateAnnoInfoStatusTest(MigrationTest):

    before = [
        ('accounts', '0001_squashed_0012_field_string_attributes_to_unicode'),
        ('annotations', '0022_annoinfo_confirmed_to_status'),
        ('images', '0001_squashed_0033_remove_image_annotation_progress'),
    ]
    after = [
        ('annotations', '0023_populate_annoinfo_status')]

    def do_test(self, expected_status: str):
        User = self.get_model_before('auth.User')
        Source = self.get_model_before('images.Source')
        Metadata = self.get_model_before('images.Metadata')
        Image = self.get_model_before('images.Image')
        Point = self.get_model_before('images.Point')
        LabelGroup = self.get_model_before('labels.LabelGroup')
        Label = self.get_model_before('labels.Label')
        Annotation = self.get_model_before('annotations.Annotation')
        ImageAnnotationInfo = self.get_model_before(
            'annotations.ImageAnnotationInfo')

        user = User(username='testuser')
        user.save()
        # Not really sure if the robot user gets auto-created in this test,
        # even if the accounts migrations run.
        robot_user, _ = User.objects.get_or_create(username='robot')
        group = LabelGroup(name="Group1", code='g1')
        group.save()
        label = Label(name="A", default_code='A', group=group)
        label.save()
        source = Source(
            name="Test source", image_annotation_area='0;100;0;100')
        source.save()
        metadata = Metadata()
        metadata.save()
        image = Image(
            original_file=sample_image_as_file('a.png'),
            uploaded_by=user,
            point_generation_method=source.default_point_generation_method,
            metadata=metadata,
            source=source,
        )
        image.save()
        annoinfo = ImageAnnotationInfo(image=image)
        annoinfo.save()
        point = Point(image=image, row=1, column=1, point_number=1)
        point.save()

        if expected_status == 'confirmed':
            annotation = Annotation(
                source=source, image=image, point=point,
                user=user, label=label)
            annotation.save()
        elif expected_status == 'unconfirmed':
            annotation = Annotation(
                source=source, image=image, point=point,
                user=robot_user, label=label)
            annotation.save()

        # Undo any previous assignments of this field
        annoinfo.refresh_from_db()
        annoinfo.status = ImageAnnoStatuses.UNCLASSIFIED.value
        annoinfo.save()

        self.run_migration()

        annoinfo.refresh_from_db()
        self.assertEqual(annoinfo.status, expected_status)

    def test_confirmed(self):
        self.do_test(expected_status='confirmed')

    def test_unconfirmed(self):
        self.do_test(expected_status='unconfirmed')

    def test_unclassified(self):
        self.do_test(expected_status='unclassified')


class PopulateAnnoInfoClassifierTest(MigrationTest):

    before = [
        ('accounts', '0001_squashed_0012_field_string_attributes_to_unicode'),
        ('annotations', '0026_annoinfo_add_classifier'),
        ('events', '0004_indexes_for_type_source_image'),
        ('images', '0040_delete_source'),
        ('sources', '0010_populate_deployed_classifier'),
        ('vision_backend', '0027_sourcecheckrequestevent'),
    ]
    after = [
        ('annotations', '0027_annoinfo_populate_classifier')]

    def test(self):
        ImageAnnotationInfo = self.get_model_before(
            'annotations.ImageAnnotationInfo')
        User = self.get_model_before('auth.User')
        Event = self.get_model_before('events.Event')
        Metadata = self.get_model_before('images.Metadata')
        Image = self.get_model_before('images.Image')
        Point = self.get_model_before('images.Point')
        LabelGroup = self.get_model_before('labels.LabelGroup')
        Label = self.get_model_before('labels.Label')
        Source = self.get_model_before('sources.Source')
        Classifier = self.get_model_before('vision_backend.Classifier')
        Score = self.get_model_before('vision_backend.Score')

        user = User(username='testuser')
        user.save()
        robot_user, _ = User.objects.get_or_create(username='robot')
        group = LabelGroup(name="Group1", code='g1')
        group.save()
        label = Label(name="A", default_code='A', group=group)
        label.save()
        source = Source(name="Test source")
        source.save()
        classifier_1 = Classifier(source=source)
        classifier_1.save()
        classifier_2 = Classifier(source=source)
        classifier_2.save()

        image_ids = []
        for i in range(4):
            metadata = Metadata()
            metadata.save()
            image = Image(
                original_file=sample_image_as_file('a.png'),
                uploaded_by=user,
                point_generation_method=source.default_point_generation_method,
                metadata=metadata,
                source=source,
            )
            image.save()
            image_ids.append(image.pk)
            annoinfo = ImageAnnotationInfo(image=image)
            annoinfo.save()
            point = Point(image=image, row=1, column=1, point_number=1)
            point.save()

            if i == 0 or i == 2:
                event = Event(
                    type='classify_image', classifier_id=classifier_1.pk,
                    source_id=source.pk, image_id=image.pk, details={},
                )
                event.save()
                event = Event(
                    type='classify_image', classifier_id=classifier_2.pk,
                    source_id=source.pk, image_id=image.pk, details={},
                )
                event.save()
            elif i == 1:
                # Reverse order
                event = Event(
                    type='classify_image', classifier_id=classifier_2.pk,
                    source_id=source.pk, image_id=image.pk, details={},
                )
                event.save()
                event = Event(
                    type='classify_image', classifier_id=classifier_1.pk,
                    source_id=source.pk, image_id=image.pk, details={},
                )
                event.save()
            # i == 3: no event.

            if i == 0 or i == 1 or i == 3:
                score = Score(
                    label=label, point=point, source=source, image=image)
                score.save()
            # i == 2: no score.

        self.run_migration()

        Image = self.get_model_after('images.Image')

        image = Image.objects.get(pk=image_ids[0])
        self.assertEqual(
            image.annoinfo.classifier_id, classifier_2.pk,
            msg="Should be the classifier of this image's latest event")
        image = Image.objects.get(pk=image_ids[1])
        self.assertEqual(
            image.annoinfo.classifier_id, classifier_1.pk,
            msg="Should be the classifier of this image's latest event")

        image = Image.objects.get(pk=image_ids[2])
        self.assertIsNone(
            image.annoinfo.classifier_id,
            msg="Should not set classifier for images without scores")

        image = Image.objects.get(pk=image_ids[3])
        self.assertIsNone(
            image.annoinfo.classifier_id,
            msg="Should not set classifier for images without events")


class AnnoInfoSourceFieldMigrationTest(MigrationTest):
    """
    Test population of ImageAnnotationInfo.source from
    ImageAnnotationInfo.image.source.
    """

    before = [
        ('annotations', '0030_annotation_new_indexes'),
        ('images', '0051_unique_metadata_names_in_source'),
        ('sources', '0010_populate_deployed_classifier'),
    ]
    after = [
        ('annotations', '0033_annoinfo_source_schema2'),
    ]

    def test(self):
        Source = self.get_model_before('sources.Source')
        Image = self.get_model_before('images.Image')
        ImageAnnotationInfo = self.get_model_before(
            'annotations.ImageAnnotationInfo')

        source_1 = Source.objects.create(name="Source 1")
        source_1_pk = source_1.pk
        source_2 = Source.objects.create(name="Source 2")
        source_2_pk = source_2.pk
        image_1 = Image.objects.create(
            source=source_1, **image_defaults)
        annoinfo_1 = ImageAnnotationInfo.objects.create(image=image_1)
        annoinfo_1_pk = annoinfo_1.pk
        image_2 = Image.objects.create(
            source=source_2, **image_defaults)
        annoinfo_2 = ImageAnnotationInfo.objects.create(image=image_2)
        annoinfo_2_pk = annoinfo_2.pk
        image_3 = Image.objects.create(
            source=source_2, **image_defaults)
        annoinfo_3 = ImageAnnotationInfo.objects.create(image=image_3)
        annoinfo_3_pk = annoinfo_3.pk

        # source attributes shouldn't exist yet
        self.assertRaises(AttributeError, getattr, annoinfo_1, 'source')
        self.assertRaises(AttributeError, getattr, annoinfo_2, 'source')
        self.assertRaises(AttributeError, getattr, annoinfo_3, 'source')

        self.run_migration()

        ImageAnnotationInfo = self.get_model_after(
            'annotations.ImageAnnotationInfo')

        # source attributes should be filled in
        self.assertEqual(
            ImageAnnotationInfo.objects.get(pk=annoinfo_1_pk).source.pk,
            source_1_pk)
        self.assertEqual(
            ImageAnnotationInfo.objects.get(pk=annoinfo_2_pk).source.pk,
            source_2_pk)
        self.assertEqual(
            ImageAnnotationInfo.objects.get(pk=annoinfo_3_pk).source.pk,
            source_2_pk)
