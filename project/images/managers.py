from django.db import models

from annotations.model_utils import ImageAnnoStatuses


class ImageQuerySet(models.QuerySet):

    def confirmed(self):
        """Confirmed annotation status only."""
        return self.filter(
            annoinfo__status=ImageAnnoStatuses.CONFIRMED.value)

    def unconfirmed(self):
        """Unconfirmed annotation status only."""
        return self.filter(
            annoinfo__status=ImageAnnoStatuses.UNCONFIRMED.value)

    def unclassified(self):
        """Unclassified annotation status only."""
        return self.filter(
            annoinfo__status=ImageAnnoStatuses.UNCLASSIFIED.value)

    def incomplete(self):
        """
        Unconfirmed OR unclassified annotation status.
        Basically "status is not confirmed", but
        "not confirmed" would have been confusing versus "unconfirmed".
        """
        return self.exclude(
            annoinfo__status=ImageAnnoStatuses.CONFIRMED.value)

    def with_features(self):
        """Only images with feature vectors available."""
        return self.filter(features__extracted=True)

    def without_features(self):
        """Only (processable) images without feature vectors available."""
        return self.filter(features__extracted=False, unprocessable_reason="")


class PointQuerySet(models.QuerySet):

    def delete(self):
        """Batch-delete Points."""
        from .models import Image

        # Get all the images corresponding to these points.
        images = Image.objects.filter(point__in=self).distinct()
        # Evaluate the queryset before deleting the points.
        images = list(images)
        # Delete the points.
        return_values = super().delete()

        for image in images:
            image.annoinfo.update_annotation_progress_fields()

        return return_values

    def bulk_create(self, *args, **kwargs):
        from .models import Image

        new_points = super().bulk_create(*args, **kwargs)

        images = Image.objects.filter(point__in=new_points).distinct()
        for image in images:
            image.annoinfo.update_annotation_progress_fields()

        return new_points
