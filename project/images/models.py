import posixpath

from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ImproperlyConfigured
from django.core.mail import mail_admins
from django.core.validators import MinValueValidator
from django.db import models
from easy_thumbnails.fields import ThumbnailerImageField

from annotations.model_utils import AnnotationArea
from lib.utils import rand_string
from sources.models import Source
from .managers import ImageQuerySet, PointQuerySet
from .model_utils import PointGen


def get_original_image_upload_path(instance, filename):
    """
    Generate a destination path (on the server filesystem) for
    a data-image upload.
    """
    base_name = None
    max_tries = 10

    for try_number in range(1, max_tries+1):
        base_name = rand_string(10)

        # The base name should come after the directory separator (forward
        # slash even on Windows) and before the extension in the full path.
        pattern = '/' + base_name + '.'

        if Image.objects.filter(original_file__contains=pattern).exists():

            # We have a base name collision with an existing image.

            if try_number >= max_tries:

                # If we're here, we weren't able to generate a unique base
                # name ourselves. We have to let the Django storage framework
                # append a suffix as needed to ensure we get a unique full
                # filename.
                #
                # We don't generally want to be here, since the storage
                # framework will allow, say, a.png and a.jpg as completely
                # different images (same base name, 'a'). This might not cause
                # actual errors, but at the least, it can be confusing for us.
                mail_admins(
                    "Image upload filename problem",
                    "Image upload may be running out of possible base names"
                    " for files. Wasn't able to generate a unique base name"
                    " after {} tries. Currently using a duplicate base name"
                    " of {}, letting Django storage auto-generate a suffix"
                    " as needed.".format(max_tries, base_name)
                )

        else:

            # We have a unique base name, so use it.
            break

    return settings.IMAGE_FILE_PATTERN.format(
        name=base_name, extension=posixpath.splitext(filename)[-1])


class Image(models.Model):
    objects = ImageQuerySet.as_manager()

    # width_field and height_field allow Django to cache the
    # width and height values, so that the image file doesn't have
    # to be read every time we want the width and height.
    # The cache is only updated when the image is saved.
    original_file = ThumbnailerImageField(
        upload_to=get_original_image_upload_path,
        width_field="original_width", height_field="original_height")

    # Cached width and height values for the file field.
    original_width = models.IntegerField()
    original_height = models.IntegerField()

    upload_date = models.DateTimeField(
        'Upload date',
        auto_now_add=True, editable=False)
    uploaded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        editable=False, null=True)

    point_generation_method = models.CharField(
        'How points were generated',
        max_length=50,
        blank=True,
    )

    # If a .cpc is uploaded for this image, we save the entire .cpc content
    # (including parts of the .cpc that CoralNet doesn't use) as well as the
    # .cpc filename so that upload -> export can preserve as much info as
    # possible.
    cpc_content = models.TextField(
        "File content of last .cpc uploaded for this image",
        default='',
    )
    cpc_filename = models.CharField(
        "Filename of last .cpc uploaded for this image",
        default='',
        max_length=1000,
    )

    source = models.ForeignKey(Source, on_delete=models.CASCADE)

    # Set this only if a technical issue prevents the image from
    # being processed in the backend (e.g. feature extraction).
    # For example, if the image's points were generated while the
    # point-count-limit checks were buggy/deficient.
    unprocessable_reason = models.CharField(default="", max_length=200)

    @property
    def valset(self):
        """
        Returns True if the image is considered part of the validation set
        (not the training set) when creating a new classifier, else False.
        """
        if settings.VALSET_SELECTION_METHOD == 'id':
            # This is a very simple method, but can make unit tests
            # unpredictable.
            return self.pk % 8 == 0
        if settings.VALSET_SELECTION_METHOD == 'name':
            # This is unsuitable for production use, since users should be able
            # to give images any names they want. But this is useful for unit
            # tests, where we want predictability (and sometimes precise
            # control) regarding which images are in the validation set.
            return self.metadata.name.startswith('val')
        raise ImproperlyConfigured(
            "Unrecognized VALSET_SELECTION_METHOD: {}".format(
                settings.VALSET_SELECTION_METHOD))

    @property
    def trainset(self):
        """
        Returns True if the image is considered part of the training set
        (not the validation set) when creating a new classifier, else False.
        """
        return not self.valset

    @property
    def max_column(self):
        # Highest column (x) pixel within the image dimensions.
        return self.original_width - 1

    @property
    def max_row(self):
        # Highest row (y) pixel within the image dimensions.
        return self.original_height - 1

    def __str__(self):
        return (
            f"Image {self.pk}"
            f" [Source: {self.source} [{self.source.pk}]]")

    def get_image_element_title(self):
        """
        Use this as the "title" element of the image on an HTML page
        (hover the mouse over the image to see this).
        """
        # Just use the image name (usually filename).
        return self.metadata.name

    def point_gen_method_display(self):
        """
        Display the point generation method in templates.
        Usage: {{ myimage.point_gen_method_display }}
        """
        return str(PointGen.from_db_value(self.point_generation_method))

    def height_cm(self):
        return self.metadata.height_in_cm

    def annotation_area_display(self):
        """
        Display the annotation area parameters in templates.
        Usage: {{ myimage.annotation_area_display }}
        """
        return str(
            AnnotationArea.from_db_value(self.metadata.annotation_area))

    def get_process_date_short_str(self):
        """
        Return the image's (pre)process date in YYYY-MM-DD format.

        Advantage over YYYY-(M)M-(D)D: alphabetized = sorted by date
        Advantage over YYYY(M)M(D)D: date is unambiguous
        """
        return "{0}-{1:02}-{2:02}".format(
            self.process_date.year, self.process_date.month,
            self.process_date.day)


class Metadata(models.Model):
    image = models.OneToOneField(Image, on_delete=models.CASCADE)

    # Redundant with image.source, but enables creation of useful
    # database indexes.
    # We won't create an index for just this column, as we'd rather have
    # multi-column indexes starting with source.
    source = models.ForeignKey(
        Source, on_delete=models.CASCADE, db_index=False)

    name = models.CharField("Name", max_length=200, blank=True)
    photo_date = models.DateField(
        "Date",
        help_text='Format: YYYY-MM-DD',
        null=True, blank=True,
    )

    latitude = models.CharField("Latitude", max_length=20, blank=True)
    longitude = models.CharField("Longitude", max_length=20, blank=True)
    depth = models.CharField("Depth", max_length=45, blank=True)

    height_in_cm = models.IntegerField(
        "Height (cm)",
        help_text=(
            "The number of centimeters of substrate the image covers,"
            " from the top of the image to the bottom."),
        validators=[MinValueValidator(0)],
        null=True, blank=True
    )

    annotation_area = models.CharField(
        "Annotation area",
        help_text=(
            "This defines a rectangle of the image where annotation points are"
            " allowed to be generated."
            " If you change this, then new points will be generated for this"
            " image, and the old points will be deleted."),
        max_length=50,
        null=True, blank=True
    )

    camera = models.CharField("Camera", max_length=200, blank=True)
    photographer = models.CharField("Photographer", max_length=45, blank=True)
    water_quality = models.CharField("Water quality", max_length=45, blank=True)

    strobes = models.CharField("Strobes", max_length=200, blank=True)
    framing = models.CharField("Framing gear used", max_length=200, blank=True)
    balance = models.CharField("White balance card", max_length=200, blank=True)

    comments = models.TextField("Comments", max_length=1000, blank=True)

    aux1 = models.CharField(max_length=50, blank=True)
    aux2 = models.CharField(max_length=50, blank=True)
    aux3 = models.CharField(max_length=50, blank=True)
    aux4 = models.CharField(max_length=50, blank=True)
    aux5 = models.CharField(max_length=50, blank=True)

    # Names of fields that may be included in a basic 'edit metadata' form.
    # annotation_area is more complex to edit, which is why it's
    # not included here.
    EDIT_FORM_FIELDS = [
        'name', 'photo_date', 'aux1', 'aux2', 'aux3', 'aux4', 'aux5',
        'height_in_cm', 'latitude', 'longitude', 'depth',
        'camera', 'photographer', 'water_quality',
        'strobes', 'framing', 'balance', 'comments',
    ]

    def __str__(self):
        return "Metadata of " + self.name

    def to_dict(self):
        """
        Returns the model as python dict of the form:
            {field_name: field_value}
        Both field name and values are strings.
        """
        return {field: str(getattr(self, field)) for
                field in self.EDIT_FORM_FIELDS}


class Point(models.Model):
    objects = PointQuerySet.as_manager()

    row = models.IntegerField()
    column = models.IntegerField()
    point_number = models.IntegerField()
    # TODO: Is this even used anywhere? If not, delete the field.
    annotation_status = models.CharField(max_length=1, blank=True)
    image = models.ForeignKey(Image, on_delete=models.CASCADE)

    def save(self, *args, **kwargs):
        # Check row/column against image bounds before saving.
        #
        # We do this validation in save() because we only ever create Points
        # through direct ORM save() calls, not through Forms or ModelForms.
        # When calling save() directly, model field validators, clean(), etc.
        # are not used.
        assert self.row >= 0, "Row below minimum"
        assert self.row <= self.image.max_row, "Row above maximum"
        assert self.column >= 0, "Column below minimum"
        assert self.column <= self.image.max_column, "Column above maximum"

        super().save(*args, **kwargs)

        # The image's annotation status may need updating.
        self.image.annoinfo.update_annotation_progress_fields()

    def delete(self, *args, **kwargs):
        return_values = super().delete(*args, **kwargs)
        self.image.annoinfo.update_annotation_progress_fields()
        return return_values

    def __str__(self):
        """
        To-string method.
        """
        return "Point %s" % self.point_number
