# This module includes testing of Event subclass mechanics. It's easiest to
# test using an existing subclass, so we import one from vision_backend,
# although it's not the best thing from a dependencies/app-coupling standpoint.

from django.core.exceptions import ValidationError
from django_migration_testcase import MigrationTest

from lib.tests.utils import ClientTest
from vision_backend.models import ClassifyImageEvent
from ..models import Event


class ModelSaveTest(ClientTest):

    def test_subclass_sets_type(self):
        user = self.create_user()
        source = self.create_source(user)
        image = self.upload_image(user, source)
        classifier = self.create_robot(source)

        classify_event = ClassifyImageEvent(
            source_id=source.pk,
            image_id=image.pk,
            classifier_id=classifier.pk,
            details={},
        )
        classify_event.save()
        classify_event.refresh_from_db()
        self.assertEqual(classify_event.type, 'classify_image')

    def test_subclass_required_fields(self):
        user = self.create_user()
        source = self.create_source(user)
        self.upload_image(user, source)
        classifier = self.create_robot(source)

        classify_event = ClassifyImageEvent(
            source_id=source.pk,
            classifier_id=classifier.pk,
            details={},
        )
        with self.assertRaises(ValidationError) as cm:
            classify_event.save()
        self.assertEqual(
            cm.exception.message,
            "This event type requires the image_id field.")


class ManagerTest(ClientTest):

    def test_queryset_default_filtering(self):
        user = self.create_user()
        source = self.create_source(user)
        image = self.upload_image(user, source)
        classifier = self.create_robot(source)

        event = Event(
            type='test',
            source_id=source.pk,
            details={},
        )
        event.save()
        classify_event = ClassifyImageEvent(
            source_id=source.pk,
            image_id=image.pk,
            classifier_id=classifier.pk,
            details={},
        )
        classify_event.save()

        # Set of all objects should filter by the event subclass's type,
        # if any.
        self.assertEqual(Event.objects.count(), 2)
        self.assertEqual(ClassifyImageEvent.objects.count(), 1)

        # get() should filter by the event subclass's type,
        # if any.
        with self.assertRaises(Event.MultipleObjectsReturned):
            Event.objects.get(source_id=source.pk)
        self.assertEqual(
            ClassifyImageEvent.objects.get(source_id=source.pk).pk,
            classify_event.pk,
        )


class MigrateClassifyImageEventToOtherAppTest(MigrationTest):

    before = [
        ('events', '0002_event_type_no_choices'),
    ]
    after = [
        ('events', '0003_delete_classifyimageevent'),
    ]

    def test_dont_delete_events(self):
        """
        Since it's just a proxy model being moved, no instances should
        get deleted.
        """
        Event = self.get_model_before('events.Event')
        event = Event(type='classify_image', details="Some details")
        event.save()
        event_id = event.pk

        self.run_migration()

        Event = self.get_model_after('events.Event')
        # This shouldn't get DoesNotExist
        event = Event.objects.get(pk=event_id)
        self.assertEqual(event.type, 'classify_image')
