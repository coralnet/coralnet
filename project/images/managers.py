from django.db.models import Manager, QuerySet

from annotations.model_utils import ImageAnnoStatuses


class ImageQuerySet(QuerySet):

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


class PointQuerySet(QuerySet):

    def delete(self):
        """
        When we delete Points, we want to update the relevant Images'
        annotation-progress fields, while also being mindful of performance.
        The way we ensure this is to make the Annotation deletion API more
        specific, providing other functions like delete_for_image(),
        while disabling this generic delete() method so it can't
        be used by accident.

        When we do really want to use a generic delete (should be rare), we
        can still either delete the Points one by one, or we can do:
        QuerySet.delete(my_point_queryset)
        followed by some other code to update the ImageAnnotationInfo fields.
        """
        raise TypeError(
            "Use delete_for_image() instead."
            " Or delete the Points one by one."
        )


class PointManager(Manager):

    def delete_for_image(self, image: 'Image'):
        QuerySet.delete(self.model.objects.filter(image=image))

        # Annotation progress info may need updating.
        image.annoinfo.update_annotation_progress_fields()

    def bulk_create(self, objs, *args, **kwargs):
        """
        Similar idea to PointQuerySet.delete().
        """
        raise TypeError(
            "Use bulk_create_for_image() instead."
            " Or create the Points one by one."
        )

    def bulk_create_for_image(self, objs, image: 'Image'):
        for obj in objs:
            # image field can be set either by the caller or here. But it
            # shouldn't be set to a different Image.
            if obj.image_id is None:
                obj.image = image
            elif obj.image_id != image.pk:
                raise ValueError(
                    f"Args have clashing Images:"
                    f" ID {obj.image_id} vs. ID {image.pk}")

        new_points = Manager.bulk_create(self, objs)

        # Annotation progress info may need updating.
        image.annoinfo.update_annotation_progress_fields()

        return new_points
