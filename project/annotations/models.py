from django.contrib.auth.models import User
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from images.models import Image, Point
from labels.models import Label, LocalLabel
from sources.models import Source
from vision_backend.models import Classifier
from vision_backend.utils import schedule_source_check_on_commit
from .managers import AnnotationManager, AnnotationQuerySet
from .model_utils import ImageAnnoStatuses, image_annotation_status


class Annotation(models.Model):
    objects = AnnotationManager.from_queryset(AnnotationQuerySet)()

    annotation_date = models.DateTimeField(
        blank=True, auto_now=True, editable=False)
    point = models.OneToOneField(Point, on_delete=models.CASCADE, editable=False)
    image = models.ForeignKey(Image, on_delete=models.CASCADE, editable=False)

    # The user who made this annotation
    user = models.ForeignKey(User, on_delete=models.SET_NULL, editable=False, null=True)
    # Only fill this in if the user is the robot user
    robot_version = models.ForeignKey(Classifier, on_delete=models.SET_NULL, editable=False, null=True)

    label = models.ForeignKey(Label, on_delete=models.PROTECT)
    source = models.ForeignKey(Source, on_delete=models.CASCADE, editable=False)

    @property
    def label_code(self):
        local_label = LocalLabel.objects.get(
            global_label=self.label, labelset=self.source.labelset)
        return local_label.code

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.image.annoinfo.update_annotation_progress_fields()

    def delete(self, *args, **kwargs):
        return_values = super().delete(*args, **kwargs)
        self.image.annoinfo.update_annotation_progress_fields()
        return return_values

    def __str__(self):
        return "%s - %s - %s" % (
            self.image, self.point.point_number, self.label_code)


class ImageAnnotationInfo(models.Model):
    """
    Annotation-related info for a single image.
    """
    image = models.OneToOneField(
        Image, on_delete=models.CASCADE, editable=False,
        # Name of reverse relation
        related_name='annoinfo')

    # The image's annotation status. This is a redundant field, in the sense
    # that it can be computed from the annotations. But it's necessary
    # for image-searching performance.
    status = models.CharField(
        max_length=30, choices=ImageAnnoStatuses.choices,
        default=ImageAnnoStatuses.UNCLASSIFIED.value,
    )

    # Latest updated annotation for this image. This is a redundant field, in
    # the sense that it can be computed from the annotations. But it's
    # necessary for performance of queries such as 'find the 20 most recently
    # annotated images'.
    last_annotation = models.ForeignKey(
        'annotations.Annotation', on_delete=models.SET_NULL,
        editable=False, null=True,
        # + means don't define a reverse relation. It wouldn't be helpful in
        # this case.
        related_name='+')

    def update_annotation_progress_fields(self):
        """
        Ensure the redundant annotation-progress fields (which exist for
        performance reasons) are up to date.

        This should be called after saving, deleting, bulk-deleting, or
        bulk-creating Annotations or Points.
        """
        # Update the last_annotation.
        # If there are no annotations, then first() returns None.
        last_annotation = self.image.annotation_set.order_by(
            '-annotation_date').first()
        self.last_annotation = last_annotation

        # Update status.
        previously_confirmed = self.confirmed
        self.status = image_annotation_status(self.image)

        self.save()

        if self.confirmed and not previously_confirmed:

            # With a new image confirmed, let's see if a new robot can be
            # trained.
            schedule_source_check_on_commit(self.image.source.pk)

        elif last_annotation is None:

            # Image has no annotations now. Let's see if machine annotations
            # can be added.
            schedule_source_check_on_commit(self.image.source.pk)

    @property
    def confirmed(self):
        return self.status == ImageAnnoStatuses.CONFIRMED.value

    @property
    def classified(self):
        return self.status != ImageAnnoStatuses.UNCLASSIFIED.value

    @property
    def status_display(self):
        return ImageAnnoStatuses(self.status).label


class AnnotationToolAccess(models.Model):
    access_date = models.DateTimeField(
        blank=True, auto_now=True, editable=False)
    image = models.ForeignKey(Image, on_delete=models.CASCADE, editable=False)
    source = models.ForeignKey(Source, on_delete=models.CASCADE, editable=False)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, editable=False, null=True)


class AnnotationToolSettings(models.Model):

    user = models.OneToOneField(User, on_delete=models.CASCADE, editable=False)

    POINT_MARKER_CHOICES = (
        ('crosshair', 'Crosshair'),
        ('circle', 'Circle'),
        ('crosshair and circle', 'Crosshair and circle'),
        ('box', 'Box'),
        )
    MIN_POINT_MARKER_SIZE = 1
    MAX_POINT_MARKER_SIZE = 30
    MIN_POINT_NUMBER_SIZE = 1
    MAX_POINT_NUMBER_SIZE = 40

    point_marker = models.CharField(max_length=30, choices=POINT_MARKER_CHOICES, default='crosshair')
    point_marker_size = models.IntegerField(
        default=16,
        validators=[
            MinValueValidator(MIN_POINT_MARKER_SIZE),
            MaxValueValidator(MAX_POINT_MARKER_SIZE),
        ],
    )
    point_marker_is_scaled = models.BooleanField(default=False)

    point_number_size = models.IntegerField(
        default=24,
        validators=[
            MinValueValidator(MIN_POINT_NUMBER_SIZE),
            MaxValueValidator(MAX_POINT_NUMBER_SIZE),
        ],
    )
    point_number_is_scaled = models.BooleanField(default=False)

    unannotated_point_color = models.CharField(max_length=6, default='FFFF00', verbose_name='Not annotated point color')
    robot_annotated_point_color = models.CharField(max_length=6, default='FFFF00', verbose_name='Unconfirmed point color')
    human_annotated_point_color = models.CharField(max_length=6, default='8888FF', verbose_name='Confirmed point color')
    selected_point_color = models.CharField(max_length=6, default='00FF00')

    show_machine_annotations = models.BooleanField(default=True)
