import math
import posixpath
import random
from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import models
from easy_thumbnails.fields import ThumbnailerImageField
from lib.utils import rand_string


class LabelGroupManager(models.Manager):
    def get_by_natural_key(self, code):
        """
        Allow fixtures to refer to Label Groups by short code instead of by id.
        """
        return self.get(code=code)


class LabelGroup(models.Model):
    objects = LabelGroupManager()

    name = models.CharField(max_length=45, blank=True)
    code = models.CharField(max_length=10, blank=True)

    def __unicode__(self):
        """
        To-string method.
        """
        return self.name


def get_label_thumbnail_upload_path(instance, filename):
    """
    Generate a destination path (on the server filesystem) for
    an upload of a label's representative thumbnail image.
    """
    return settings.LABEL_THUMBNAIL_FILE_PATTERN.format(
        name=rand_string(10),
        extension=posixpath.splitext(filename)[-1])


class LabelManager(models.Manager):
    def get_by_natural_key(self, code):
        """
        Allow fixtures to refer to Labels by short code instead of by id.
        """
        return self.get(code=code)


class Label(models.Model):
    class Meta:
        permissions = (
            ('verify_label', "Can change verified field"),
        )

    objects = LabelManager()

    name = models.CharField(max_length=45)
    default_code = models.CharField('Default Short Code', max_length=10)
    group = models.ForeignKey(
        LabelGroup, on_delete=models.PROTECT, verbose_name='Functional Group')
    description = models.TextField(null=True)
    verified = models.BooleanField(default=False)
    duplicate = models.ForeignKey("Label", on_delete=models.SET_NULL, blank=True, null=True)

    # easy_thumbnails reference:
    # http://packages.python.org/easy-thumbnails/ref/processors.html
    THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT = 150, 150
    thumbnail = ThumbnailerImageField(
        'Example image (thumbnail)',
        upload_to=get_label_thumbnail_upload_path,
        resize_source=dict(
            size=(THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT), crop='smart'),
        help_text=(
            "For best results,"
            " please use an image that's close to {w} x {h} pixels."
            " Otherwise, we'll resize and crop your image"
            " to make sure it's that size.").format(
                w=THUMBNAIL_WIDTH, h=THUMBNAIL_HEIGHT),
        null=True,
    )

    create_date = models.DateTimeField(
        'Date created', auto_now_add=True, editable=False, null=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        verbose_name='Created by', editable=False, null=True)

    def clean(self):
        if self.duplicate is not None and not self.duplicate.verified:
            raise ValidationError("A label can only be a Duplicate of a Verified label")
        if self.duplicate is not None and self.verified:
            raise ValidationError("A label can not both be a Duplicate and Verified.")

    def __unicode__(self):
        """
        To-string method.
        """
        return self.name

    @property
    def popularity(self):
        cache_key = 'label_popularity_{pk}'.format(pk=self.pk)
        cached_value = cache.get(cache_key)
        if cached_value is not None:
            return cached_value
        return self._compute_popularity()

    def _compute_popularity(self):
        # TODO: This formula is most likely garbage; make a better one
        raw_score = (
            # Labelset count
            self.locallabel_set.count()
            # Square root of annotation count
            * math.sqrt(self.annotation_set.count())
        )

        if raw_score == 0:
            popularity = 0
        else:
            # Map to a 0-100 scale.
            popularity = 100 * (1 - raw_score**(-0.15))

        # Cache the value for a random duration between 2 and 3 days.
        # The duration is random so that the cached popularities don't all
        # expire at the same time.
        POPULARITY_CACHE_DURATION = random.randint(60*60*24*2, 60*60*24*3)
        cache_key = 'label_popularity_{pk}'.format(pk=self.pk)
        cache.set(cache_key, popularity, POPULARITY_CACHE_DURATION)

        return popularity


class LabelSet(models.Model):
    # description and location are obsolete if we're staying with a 1-to-1
    # correspondence between labelsets and sources.
    description = models.TextField(blank=True)
    location = models.CharField(max_length=45, blank=True)
    edit_date = models.DateTimeField(
        'Date edited', auto_now=True, editable=False)

    def get_labels(self):
        return self.locallabel_set.all()

    def get_locals_ordered_by_group_and_code(self):
        return self.get_labels().order_by('global_label__group', 'code')

    def get_globals(self):
        global_label_pks = self.get_labels().values_list(
            'global_label__pk', flat=True)
        return Label.objects.filter(pk__in=global_label_pks)

    def get_globals_ordered_by_name(self):
        return self.get_globals().order_by('name')

    def get_global_by_code(self, code):
        try:
            # Codes are case insensitive
            local_label = self.get_labels().get(code__iexact=code)
        except LocalLabel.DoesNotExist:
            return None
        return local_label.global_label

    def global_pk_to_code(self, global_pk):
        try:
            local_label = self.get_labels().get(global_label__pk=global_pk)
        except LocalLabel.DoesNotExist:
            return None
        return local_label.code

    def __unicode__(self):
        source = self.source_set.first()
        if source:
            # Labelset of a source
            return "%s labelset" % source
        else:
            # Labelset that's not in any source (either a really old
            # labelset from early site development, or a labelset of a
            # deleted source which wasn't properly cleaned up)
            return "(Labelset not used in any source) " + self.description


class LocalLabel(models.Model):
    code = models.CharField('Short Code', max_length=10)
    global_label = models.ForeignKey(Label)
    labelset = models.ForeignKey(LabelSet)

    @property
    def name(self):
        return self.global_label.name

    @property
    def group(self):
        return self.global_label.group

    def __unicode__(self):
        """
        To-string method.
        """
        return self.code
