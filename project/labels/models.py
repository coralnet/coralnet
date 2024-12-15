import posixpath
import re

from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.forms import model_to_dict
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

    def __str__(self):
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

    name = models.CharField(
        max_length=45,
        validators=[RegexValidator(
            r'^[a-zA-Z0-9{punctuation}]+\Z'.format(
                punctuation=re.escape(" &'()+,-./:;<>_")),
            message="You entered disallowed characters or punctuation.")],
        help_text="Please use English words and names.",
    )

    default_code = models.CharField(
        'Default Short Code', max_length=10,
        validators=[RegexValidator(
            r'^[a-zA-Z0-9{punctuation}]+\Z'.format(
                punctuation=re.escape(" &*+-./_")),
            message="You entered disallowed characters or punctuation.")],
        help_text=(
            "Up to 10 characters. Only a few types of punctuation are"
            " accepted. Note that this is just a default code; you can"
            " later customize the codes that are used in your source."),
    )

    group = models.ForeignKey(
        LabelGroup, on_delete=models.PROTECT, verbose_name='Functional Group')

    description = models.TextField(
        null=True,
        max_length=2000,
        help_text="Please use English.",
    )

    verified = models.BooleanField(default=False)
    duplicate = models.ForeignKey("Label", on_delete=models.SET_NULL,
                                  blank=True, null=True,
                                  limit_choices_to={'verified': True})

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
        if self.duplicate is not None and self.duplicate == self:
            raise ValidationError("A label can not be a duplicate of itself.")

    def __str__(self):
        """
        To-string method.
        """
        return self.name


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

    def global_pk_to_code_dict(self):
        """
        This helps to reduce database queries compared to calling
        global_pk_to_code() once per label.
        """
        local_labels_values = self.get_labels().values('global_label', 'code')
        return dict(
            (v['global_label'], v['code']) for v in local_labels_values)

    def save_copy(self) -> 'LabelSet':
        # Copy fields and save a new instance
        kwargs = model_to_dict(self, exclude=['id'])
        labelset_copy = LabelSet(**kwargs)
        labelset_copy.save()

        # Copy LocalLabel entries
        for local_label in list(self.locallabel_set.all()):
            ll_copy = LocalLabel(
                code=local_label.code,
                global_label_id=local_label.global_label_id,
                labelset=labelset_copy,
            )
            ll_copy.save()

        return labelset_copy

    def has_same_labels(self, other: 'LabelSet') -> bool:
        self_set = set(
            self.locallabel_set.values_list('global_label_id', flat=True))
        other_set = set(
            other.locallabel_set.values_list('global_label_id', flat=True))
        return self_set == other_set

    def __str__(self):
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
    global_label = models.ForeignKey(Label, on_delete=models.PROTECT)
    labelset = models.ForeignKey(LabelSet, on_delete=models.CASCADE)

    class Meta:
        constraints = [
            # A LabelSet can't have two entries pointing to the same label.
            models.UniqueConstraint(
                fields=['global_label', 'labelset'],
                name='unique_label_within_labelset',
            ),
        ]

    @property
    def name(self):
        return self.global_label.name

    @property
    def group(self):
        return self.global_label.group

    def __str__(self):
        """
        To-string method.
        """
        return self.code
