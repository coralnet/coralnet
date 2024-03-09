import math
import posixpath
import re

from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from easy_thumbnails.fields import ThumbnailerImageField

from lib.utils import CacheableValue, rand_string


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

    @property
    def popularity(self):
        label_details = cacheable_label_details.get()
        if not label_details or self.pk not in label_details:
            return 0
        return label_details[self.pk]['popularity']

    @property
    def ann_count(self):
        """ Returns the number of annotations for this label """
        label_details = cacheable_label_details.get()
        if not label_details or self.pk not in label_details:
            return 0
        return label_details[self.pk]['annotation_count']


def compute_label_details():
    """
    Details (which are worth caching) for all labels, including annotation
    counts and popularities.
    As of 2023/11, this may take 1.5 hours to run in production.

    Annotation count can take several seconds to compute for a single
    widely-used label.

    Caching the first page of random patches is good for two reasons:
    1) On the label detail page, random patch generation involves computing
    the page count of the entire annotation set, and thus involves at least
    computing the annotation count.
    2) We don't have to generate different patch images for different
    visitors of the label detail page, in most cases. Most folks will only
    look at the first page of patches (if anything).
    """
    labels = Label.objects.all()
    details = dict()

    for label in labels:

        source_count = label.locallabel_set.count()
        annotation_count = label.annotation_set.count()

        # This popularity formula accounts for:
        # - The number of sources using the label
        # - The number of annotations using the label
        #
        # Overall, it's not too nuanced, and could use further tinkering
        # at some point.
        raw_score = (
            source_count * math.sqrt(annotation_count)
        )
        if raw_score == 0:
            popularity = 0
        else:
            # Map to a 0-100 scale.
            # The exponent determines the "shape" of the mapping.
            # -0.15 maps raw score of 10 to 29%, 100 to 50%,
            # 10000 to 75%, and 10000000 to 91%.
            popularity = 100 * (1 - raw_score**(-0.15))

        # List of annotation IDs to use for the first page of random patches
        # on the label detail page.
        random_patches_page_1 = list(
            label.annotation_set
            .order_by('?')
            .values_list('pk', flat=True)
            [:settings.LABEL_EXAMPLE_PATCHES_PER_PAGE]
        )

        details[label.pk] = dict(
            source_count=source_count,
            annotation_count=annotation_count,
            popularity=popularity,
            random_patches_page_1=random_patches_page_1,
        )

    return details


cacheable_label_details = CacheableValue(
    cache_key='label_details',
    compute_function=compute_label_details,
    cache_update_interval=60*60*24*7,
    cache_timeout_interval=60*60*24*30,
    on_demand_computation_ok=False,
    use_view_scoped_cache=True,
)


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
