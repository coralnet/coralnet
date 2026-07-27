# This module includes testing of Event subclass mechanics. It's easiest to
# test using an existing subclass, so we import one from vision_backend,
# although it's not the best thing from a dependencies/app-coupling standpoint.

from django.core.exceptions import ValidationError
from django.db.models import Model

from lib.tests.utils import CnMigrationTest, CnStandardTest
from vision_backend.models import ClassifyImageEvent
from ..models import Event


class ModelSaveTest(CnStandardTest):

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


class ManagerTest(CnStandardTest):

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


class MigrateClassifyImageEventToOtherAppTest(CnMigrationTest):

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


class PopulateCreatorForeignKeyTest(CnMigrationTest):

    before = [
        ('events', '0006_event_add_creator_fk'),
    ]
    after = [
        ('events', '0007_event_populate_creator_fk'),
    ]

    def test(self):
        Event = self.get_model_before('events.Event')
        User = self.get_model_before('auth.User')

        user_1 = User(username='user1')
        user_1.save()
        user_2 = User(username='user2')
        user_2.save()

        user_3 = User(username='user3')
        user_3.save()
        deleted_user_id = user_3.pk
        user_3.delete()

        # 2 events with existing user, 2 events with deleted user,
        # 2 events with null user.
        # Don't use Event.save() because that'll check for the new
        # creator field, which isn't populated yet.
        existing_1 = Event(
            type='annotation_upload', creator_id=user_1.pk, details={})
        Model.save(existing_1)
        existing_2 = Event(
            type='annotation_upload', creator_id=user_2.pk, details={})
        Model.save(existing_2)
        deleted_1 = Event(
            type='annotation_upload', creator_id=deleted_user_id, details={})
        Model.save(deleted_1)
        deleted_2 = Event(
            type='annotation_upload', creator_id=deleted_user_id, details={})
        Model.save(deleted_2)
        null_1 = Event(type='annotation_upload', creator_id=None, details={})
        Model.save(null_1)
        null_2 = Event(type='annotation_upload', creator_id=None, details={})
        Model.save(null_2)

        try:
            self.run_migration()
        except RuntimeError as e:
            self.assertEqual(
                str(e),
                f"User of ID {deleted_user_id} doesn't exist. Delete the"
                f" Events with this creator_id, then re-run this migration.")

        # Revise the Events to prevent the error.
        deleted_1.creator_id = None
        Model.save(deleted_1)
        deleted_2.creator_id = None
        Model.save(deleted_2)

        self.run_migration()

        # Check new field's values on each Event.
        existing_1 = Event.objects.get(pk=existing_1.pk)
        self.assertEqual(existing_1.creator_new_id, user_1.pk)
        existing_2 = Event.objects.get(pk=existing_2.pk)
        self.assertEqual(existing_2.creator_new_id, user_2.pk)
        deleted_1 = Event.objects.get(pk=deleted_1.pk)
        self.assertIsNone(deleted_1.creator_new_id)
        deleted_2 = Event.objects.get(pk=deleted_2.pk)
        self.assertIsNone(deleted_2.creator_new_id)
        null_1 = Event.objects.get(pk=null_1.pk)
        self.assertIsNone(null_1.creator_new_id)
        null_2 = Event.objects.get(pk=null_2.pk)
        self.assertIsNone(null_2.creator_new_id)
