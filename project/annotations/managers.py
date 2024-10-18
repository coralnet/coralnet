from enum import Enum
from typing import Union

from django.db import models

from accounts.utils import get_robot_user, is_robot_user
from images.models import Image


class AnnotationQuerySet(models.QuerySet):

    def confirmed(self):
        """Confirmed annotations only."""
        return self.exclude(user=get_robot_user())

    def unconfirmed(self):
        """Unconfirmed annotations only."""
        return self.filter(user=get_robot_user())

    def delete(self):
        """
        Batch-delete Annotations. Note that when this is used,
        Annotation.delete() will not be called for each individual Annotation,
        so we make sure to do the equivalent actions here.
        """
        # Get all the images corresponding to these annotations.
        images = Image.objects.filter(annotation__in=self).distinct()
        # Evaluate the queryset before deleting the annotations.
        images = list(images)
        # Delete the annotations.
        return_values = super().delete()

        # The images' annotation progress info may need updating.
        for image in images:
            image.annoinfo.update_annotation_progress_fields()

        return return_values

    def bulk_create(self, *args, **kwargs):
        raise NotImplementedError(
            "Bulk creation would skip django-reversion signals.")

        # new_annotations = super().bulk_create(*args, **kwargs)
        #
        # images = Image.objects.filter(
        #     annotation__in=new_annotations).distinct()
        # for image in images:
        #     image.annoinfo.update_annotation_progress_fields()
        #
        # return new_annotations


class AnnotationManager(models.Manager):

    # TODO: CoralNet 1.15 changed 'updated' to 'changed', and 'no change' to
    #  'not changed'. At some point, a data migration should be written to
    #  migrate pre-1.15 ClassifyImageEvents to use the new codes.
    #  There is no rush to do this until the details of pre-1.15
    #  ClassifyImageEvents are displayed in any way, which will probably be
    #  done on the Annotation History page at some point.
    #  The data migration may be difficult to make efficient in production
    #  due to the sheer number of Events, but that's OK since the migration
    #  should be safe to run while the web server is up.
    class UpdateResultsCodes(Enum):
        ADDED = 'added'
        CHANGED = 'changed'
        NOT_CHANGED = 'not changed'

    def update_point_annotation_if_applicable(
        self,
        point: 'Point',
        label: 'Label',
        now_confirmed: bool,
        user_or_robot_version: Union['User', 'Classifier'],
    ) -> str:
        """
        Update a single Point's Annotation in the database. If an Annotation
        exists for this point already, update it accordingly. Else, create a
        new Annotation.

        This function takes care of the logic for which annotations should be
        updated or not:
        - Don't overwrite confirmed with unconfirmed.
        - Only re-save the same label if overwriting unconfirmed with confirmed.

        This doesn't need to be used every time we save() an Annotation, but if
        the save has any kind of conditional logic on the annotation status
        (does the point already have an annotation? is the existing annotation
        confirmed or not?), then it's highly recommended to use this function.

        :param point: Point object we're interested in saving an Annotation to.
        :param label: Label object to save to the Annotation.
        :param now_confirmed: boolean saying whether the Annotation, if
          created/updated, would be considered confirmed or not.
        :param user_or_robot_version: a User if now_confirmed is True; a
          Classifier if now_confirmed is False.
        :return: String saying what the resulting action was.
        """
        try:
            annotation = point.annotation
        except self.model.DoesNotExist:
            # This point doesn't have an annotation in the database yet.
            # Create a new annotation.
            new_annotation = self.model(
                point=point, image=point.image,
                source=point.image.source, label=label)
            if now_confirmed:
                new_annotation.user = user_or_robot_version
            else:
                new_annotation.user = get_robot_user()
                new_annotation.robot_version = user_or_robot_version
            new_annotation.save()
            return self.UpdateResultsCodes.ADDED.value

        # An annotation for this point exists in the database
        previously_confirmed = not is_robot_user(annotation.user)

        if previously_confirmed and not now_confirmed:
            # Never overwrite confirmed with unconfirmed.
            return self.UpdateResultsCodes.NOT_CHANGED.value

        elif (not previously_confirmed and now_confirmed) \
                or (label != annotation.label):
            # Previously unconfirmed, and now a human user is
            # confirming or changing it
            # OR
            # Label was otherwise changed
            # In either case, we update the annotation.
            annotation.label = label
            if now_confirmed:
                annotation.user = user_or_robot_version
            else:
                annotation.user = get_robot_user()
                annotation.robot_version = user_or_robot_version
            annotation.save()
            return self.UpdateResultsCodes.CHANGED.value

        # Else, there's nothing to save, so don't do anything.
        return self.UpdateResultsCodes.NOT_CHANGED.value
