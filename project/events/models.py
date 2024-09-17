from collections import Counter

from django.core.exceptions import ValidationError
from django.db import models

from images.models import Image
from labels.models import Label
from .managers import EventManager


class Event(models.Model):

    objects = EventManager()

    class Types(models.TextChoices):
        CLASSIFY_IMAGE = 'classify_image', "Classify image"
    type = models.CharField(
        max_length=30, choices=Types.choices)

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
        s += self.type or "(No type)"
        if self.source_id:
            s += f" - Source {self.source_id}"
        if self.image_id:
            s += f" - Image {self.image_id}"
        if self.classifier_id:
            s += f" - Classifier {self.classifier_id}"
        if self.creator_id:
            s += f" - by User {self.creator_id}"
        return s


class ClassifyImageEvent(Event):
    class Meta:
        proxy = True

    type_for_subclass = Event.Types.CLASSIFY_IMAGE.value
    required_id_fields = ['source_id', 'image_id', 'classifier_id']

    @property
    def summary_text(self):
        return (
            f"Image {self.image_id}"
            f" checked by classifier {self.classifier_id}"
        )

    @property
    def details_text(self, image_context=False):
        """
        Details example:
        {
            1: dict(label=28, result='added'),
            2: dict(label=12, result='updated'),
            3: dict(label=28, result='no change'),
        }
        """
        if image_context:
            text = (
                f"Checked by classifier {self.classifier_id}"
                f"\n"
            )
        else:
            image = Image.objects.get(pk=self.image_id)
            text = (
                f"Image '{image.metadata.name}' (ID {self.image_id})"
                f" checked by classifier {self.classifier_id}"
                f"\n"
            )

        label_ids = set(
            [d['label'] for _, d in self.details.items()]
        )
        label_values = \
            Label.objects.filter(pk__in=label_ids).values('pk', 'name')
        label_ids_to_names = {
            vs['pk']: vs['name'] for vs in label_values
        }
        result_counter = Counter()

        for point_number, d in self.details.items():
            result = d['result']
            text += (
                f"\nPoint {point_number}"
                f" - {label_ids_to_names[d['label']]}"
                f" - {result}"
            )
            result_counter[result] += 1

        counter_line_items = []
        for result, count in result_counter.items():
            counter_line_items.append(f"{count} {result}")
        text += (
            "\n"
            "\nSummary: " + ", ".join(counter_line_items)
        )

        return text
