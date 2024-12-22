import datetime

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from .managers import EventManager


class Event(models.Model):

    objects = EventManager()

    type = models.CharField(max_length=30)

    details = models.JSONField()

    # Not using foreign keys since we don't want to delete an Event if a
    # Source, User, etc. is deleted.
    # Such entities can then be displayed on the Event as <User 123> or
    # <Source 456> for example. This allows identifying related deleted
    # events while keeping a layer of anonymity (compared to, say, saving
    # usernames instead of user IDs).

    # User who did ("created") the action, if applicable.
    creator_id = models.IntegerField(null=True, blank=True)
    # Source this event pertains to, if any.
    source_id = models.IntegerField(null=True, blank=True)
    # Image this event pertains to, if any.
    image_id = models.IntegerField(null=True, blank=True)
    # Classifier this event pertains to, if any.
    classifier_id = models.IntegerField(null=True, blank=True)

    date = models.DateTimeField(auto_now_add=True, editable=False)

    type_for_subclass: str = None
    required_id_fields: list[str] = []

    class Meta:
        indexes = [
            models.Index(fields=['type']),
            models.Index(fields=['source_id']),
            models.Index(fields=['image_id']),
        ]

    def save(self, *args, **kwargs):
        if self.type_for_subclass and self.type != self.type_for_subclass:
            self.type = self.type_for_subclass

            # Custom save() methods which update field values should add those
            # field names to the update_fields kwarg.
            # https://docs.djangoproject.com/en/4.2/topics/db/models/#overriding-predefined-model-methods
            if (update_fields := kwargs.get('update_fields')) is not None:
                kwargs['update_fields'] = {'type'}.union(update_fields)

        for field_name in self.required_id_fields:
            if not getattr(self, field_name):
                raise ValidationError(
                    f"This event type requires the {field_name} field.",
                    code='required_for_type',
                )

        super().save(*args, **kwargs)

    def __str__(self):
        s = "Event: "

        if self.type:
            # my_type -> My type
            s += self.type.replace('_', ' ').capitalize()
        else:
            s += "(No type)"

        if self.source_id:
            s += f" - Source {self.source_id}"
        if self.image_id:
            s += f" - Image {self.image_id}"
        if self.classifier_id:
            s += f" - Classifier {self.classifier_id}"
        if self.creator_id:
            s += f" - by User {self.creator_id}"
        return s

    @staticmethod
    def label_id_to_display(label_id, label_ids_to_codes):
        try:
            return label_ids_to_codes[label_id]
        except KeyError:
            # Label is not currently in the labelset or was deleted
            return f"(Label of ID {label_id})"

    @staticmethod
    def get_user_display(user_id):
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return "(Unknown user)"
        else:
            return user.username

    @staticmethod
    def get_robot_display(robot_id, event_date):
        # On this date/time in UTC, CoralNet alpha had ended and CoralNet beta
        # robot runs had not yet started.
        beta_start_dt_naive = datetime.datetime(2016, 11, 20, 2)
        beta_start_dt = timezone.make_aware(
            beta_start_dt_naive, datetime.timezone.utc)

        if event_date < beta_start_dt:
            # Alpha
            return f"Robot alpha-{robot_id}"

        # Beta (versions had reset, hence the need for alpha/beta distinction)
        return f"Robot {robot_id}"
