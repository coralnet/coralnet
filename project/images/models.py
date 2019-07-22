from __future__ import division
import posixpath

from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ObjectDoesNotExist
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from easy_thumbnails.fields import ThumbnailerImageField
from guardian.shortcuts import (
    get_objects_for_user, get_users_with_perms, get_perms, assign, remove_perm)

from .model_utils import PointGen
from accounts.utils import is_robot_user
from annotations.model_utils import AnnotationAreaUtils
from labels.models import LabelSet
from lib.utils import rand_string

# Unfortunate import b/c risk of circular reference, but wasn't sure how to
# get rid of it.
from vision_backend.models import Classifier, Features, Score


class SourceManager(models.Manager):
    def get_by_natural_key(self, name):
        """
        Allow fixtures to refer to Sources by name instead of by id.
        """
        return self.get(name=name)


class Source(models.Model):
    objects = SourceManager()

    class VisibilityTypes:
        PUBLIC = 'b'
        PUBLIC_VERBOSE = 'Public'
        PRIVATE = 'v'
        PRIVATE_VERBOSE = 'Private'

    # Example: 'Moorea'
    name = models.CharField(max_length=200, unique=True)

    VISIBILITY_CHOICES = (
        (VisibilityTypes.PUBLIC, VisibilityTypes.PUBLIC_VERBOSE),
        (VisibilityTypes.PRIVATE, VisibilityTypes.PRIVATE_VERBOSE),
    )
    visibility = models.CharField(
        max_length=1, choices=VISIBILITY_CHOICES,
        default=VisibilityTypes.PUBLIC)

    # Automatically set to the date and time of creation.
    create_date = models.DateTimeField(
        'Date created',
        auto_now_add=True, editable=False)

    description = models.TextField()

    affiliation = models.CharField(max_length=200)

    labelset = models.ForeignKey(
        LabelSet, on_delete=models.PROTECT,
        null=True)
    
    # Names for auxiliary metadata fields.
    # key1, key2, etc. are historical names from the "location key" days.
    key1 = models.CharField('Aux. metadata 1', max_length=50, default="Aux1")
    key2 = models.CharField('Aux. metadata 2', max_length=50, default="Aux2")
    key3 = models.CharField('Aux. metadata 3', max_length=50, default="Aux3")
    key4 = models.CharField('Aux. metadata 4', max_length=50, default="Aux4")
    key5 = models.CharField('Aux. metadata 5', max_length=50, default="Aux5")

    POINT_GENERATION_CHOICES = (
        (PointGen.Types.SIMPLE, PointGen.Types.SIMPLE_VERBOSE),
        (PointGen.Types.STRATIFIED, PointGen.Types.STRATIFIED_VERBOSE),
        (PointGen.Types.UNIFORM, PointGen.Types.UNIFORM_VERBOSE),
    )
    default_point_generation_method = models.CharField(
        "Point generation method",
        help_text=(
            "When we create annotation points for uploaded images, this is how"
            " we'll generate the point locations. Note that if you change this"
            " setting later on, it will NOT apply to images that are already"
            " uploaded."),
        max_length=50,
        default=PointGen.args_to_db_format(
                    point_generation_type=PointGen.Types.SIMPLE,
                    simple_number_of_points=200)
    )

    image_annotation_area = models.CharField(
        "Default image annotation area",
        help_text=(
            "This defines a rectangle of the image where annotation points are"
            " allowed to be generated.\n"
            "For example, X boundaries of 10% and 95% mean that the leftmost"
            " 10% and the rightmost 5% of the image will not have any points."
            " Decimals like 95.6% are allowed.\n"
            "Later, you can also set these boundaries as pixel counts on a"
            " per-image basis; for images that don't have a specific value"
            " set, these percentages will be used."),
        max_length=50,
        null=True
    )

    # CPCe parameters given during the last .cpc import or export.
    # These are used as the default values for the next .cpc export.
    cpce_code_filepath = models.CharField(
        "Local absolute path to the CPCe code file",
        max_length=1000,
        default='',
    )
    cpce_image_dir = models.CharField(
        "Local absolute path to the directory with image files",
        help_text="Ending slash can be present or not",
        max_length=1000,
        default='',
    )

    confidence_threshold = models.IntegerField(
        "Confidence threshold (%)",
        validators=[MinValueValidator(0),
                    MaxValueValidator(100)],
        default=100,
    )

    enable_robot_classifier = models.BooleanField(
        "Enable robot classifier",
        default=True,
        help_text=(
            "With this option on, the automatic classification system will"
            " go through your images and add unconfirmed annotations to them."
            " Then when you enter the annotation tool, you will be able to"
            " start from the system's suggestions instead of from a blank"
            " slate."),
    )

    longitude = models.CharField(max_length=20, blank=True)
    latitude = models.CharField(max_length=20, blank=True)

    class Meta:
        # Permissions for users to perform actions on Sources.
        # (Unfortunately, inner classes can't use outer-class
        # variables such as constants... so we've hardcoded these.)
        permissions = (
            ('source_view', 'View'),
            ('source_edit', 'Edit'),
            ('source_admin', 'Admin'),
        )

    class PermTypes:
        class ADMIN:
            code = 'source_admin'
            fullCode = 'images.' + code
            verbose = 'Admin'

        class EDIT:
            code = 'source_edit'
            fullCode = 'images.' + code
            verbose = 'Edit'

        class VIEW:
            code = 'source_view'
            fullCode = 'images.' + code
            verbose = 'View'

    ##########
    # Helper methods for sources
    ##########
    @staticmethod
    def get_public_sources():
        return Source.objects.filter(visibility=Source.VisibilityTypes.PUBLIC)\
            .order_by('name')

    @staticmethod
    def get_sources_of_user(user):
        # For superusers, this returns ALL sources.
        if user.is_authenticated():
            return get_objects_for_user(user, Source.PermTypes.VIEW.fullCode)\
                .order_by('name')
        else:
            return Source.objects.none()

    @staticmethod
    def get_other_public_sources(user):
        return Source.get_public_sources() \
            .exclude(pk__in=Source.get_sources_of_user(user))

    def has_member(self, user):
        return user in self.get_members()

    def get_members(self):
        return get_users_with_perms(self).order_by('username')

    def get_member_role(self, user):
        """
        Get a user's conceptual "role" in the source.

        If they have admin perms, their role is admin.
        Otherwise, if they have edit perms, their role is edit.
        Otherwise, if they have view perms, their role is view.
        Role is None if user is not a Source member.
        """
        perms = get_perms(user, self)

        for permType in [Source.PermTypes.ADMIN,
                         Source.PermTypes.EDIT,
                         Source.PermTypes.VIEW]:
            if permType.code in perms:
                return permType.verbose

    @staticmethod
    def _member_sort_key(member_and_role):
        role = member_and_role[1]
        if role == Source.PermTypes.ADMIN.verbose:
            return 1
        elif role == Source.PermTypes.EDIT.verbose:
            return 2
        elif role == Source.PermTypes.VIEW.verbose:
            return 3

    def get_members_ordered_by_role(self):
        """
        Admin first, then edit, then view.

        Within a role, members are sorted by username.  This is
        because get_members() orders members by username, and Python
        sorts are stable (meaning that when multiple records have
        the same key, their original order is preserved).
        """

        members = self.get_members()
        members_and_roles = [(m, self.get_member_role(m)) for m in members]
        members_and_roles.sort(key=Source._member_sort_key)
        ordered_members = [mr[0] for mr in members_and_roles]
        return ordered_members

    def assign_role(self, user, role):
        """
        Shortcut method to assign a conceptual "role" to a user,
        so assigning permissions can be done compactly.

        Admin role: admin, edit, view perms
        Edit role: edit, view perms
        View role: view perm
        """

        if role == Source.PermTypes.ADMIN.code:
            assign(Source.PermTypes.ADMIN.code, user, self)
            assign(Source.PermTypes.EDIT.code, user, self)
            assign(Source.PermTypes.VIEW.code, user, self)
        elif role == Source.PermTypes.EDIT.code:
            assign(Source.PermTypes.EDIT.code, user, self)
            assign(Source.PermTypes.VIEW.code, user, self)
        elif role == Source.PermTypes.VIEW.code:
            assign(Source.PermTypes.VIEW.code, user, self)
        else:
            raise ValueError("Invalid Source role: %s" % role)

    def reassign_role(self, user, role):
        """
        Shortcut method that works similarly to assign_role, but removes
        the permissions of the user before reassigning their role. User
        this if the user already has access to a particular source.
        """
        self.remove_role(user)
        self.assign_role(user, role)

    def remove_role(self, user):
        """
        Shortcut method that removes the user from the source.
        """
        remove_perm(Source.PermTypes.ADMIN.code, user, self)
        remove_perm(Source.PermTypes.EDIT.code, user, self)
        remove_perm(Source.PermTypes.VIEW.code, user, self)

    def is_public(self):
        """Can be a pain to check this in templates otherwise."""
        return self.visibility == Source.VisibilityTypes.PUBLIC

    def visible_to_user(self, user):
        return (self.visibility == Source.VisibilityTypes.PUBLIC) or \
               user.has_perm(Source.PermTypes.VIEW.code, self)

    def get_all_images(self):
        return Image.objects.filter(source=self)

    @property
    def nbr_confirmed_images(self):
        qs = self.get_all_images()
        return qs.exclude(confirmed=False).count()

    @property
    def nbr_images(self):
        return self.get_all_images().count()

    @property
    def nbr_valid_robots(self):
        return len(self.get_valid_robots())

    def image_annotation_area_display(self):
        """
        Display the annotation-area parameters in templates.
        Usage: {{ mysource.annotation_area_display }}
        """
        return AnnotationAreaUtils.db_format_to_display(
            self.image_annotation_area)

    def point_gen_method_display(self):
        """
        Display the point generation method in templates.
        Usage: {{ mysource.point_gen_method_display }}
        """
        return PointGen.db_to_readable_format(
            self.default_point_generation_method)

    def annotation_area_display(self):
        """
        Display the annotation area parameters in templates.
        Usage: {{ mysource.annotation_area_display }}
        """
        return AnnotationAreaUtils.db_format_to_display(
            self.image_annotation_area)

    def get_latest_robot(self):
        """
        return the latest robot associated with this source.
        if no robots, return None
        """
        robots = self.get_valid_robots()
        if robots.count() > 0:
            return robots[0]
        else:
            return None

    def get_valid_robots(self):
        """
        returns a list of all robots that have valid metadata
        """
        return Classifier.objects.filter(source=self, valid=True)\
            .order_by('-id')

    def nbr_images_in_latest_robot(self):
        # NOTE: Here we include also those not valid.
        robots = Classifier.objects.filter(source=self).order_by('-id')
        if robots.count() > 0:
            return robots[0].nbr_train_images
        else:
            return 0

    def need_new_robot(self):
        """
        Check whether there are sufficient number of newly annotated images to
        train a new robot version.
        Needs to be settings.NEW_MODEL_THRESHOLD more than used in the previous
        model and > settings.MIN_NBR_ANNOTATED_IMAGES
        """
        
        nbr_verified_images_with_features = Image.objects.filter(
            source=self, confirmed=True, features__extracted=True).count()
        return (
            nbr_verified_images_with_features >
            settings.NEW_CLASSIFIER_TRAIN_TH * self.nbr_images_in_latest_robot()
            and
            nbr_verified_images_with_features >=
            settings.MIN_NBR_ANNOTATED_IMAGES
            and
            self.enable_robot_classifier)

    def has_robot(self):
        """
        Returns true if source has a robot.
        """
        return self.get_valid_robots().count() > 0
        
    def all_image_names_are_unique(self):
        """
        Return true if all images in the source have unique names.
        NOTE: this will be enforced during import moving forward, but it
        wasn't originally.
        """
        images = Image.objects.filter(source=self)
        nimages = images.count()
        nunique = len(set([i.metadata.name for i in images]))
        return nunique == images.count()

    def get_nonunique_image_names(self):
        """
        returns a list of image names which occur for multiple images in the
        source.
        NOTE: there is probably a fancy SQL way to do this, but I found it
        cleaner with a python solution. It's not time critical.
        """
        imnames = [i.metadata.name for i in Image.objects.filter(source=self)] 
        return list(set([name for name in imnames if imnames.count(name) > 1]))

    def to_dict(self):
        field_names = ['name', 'longitude', 'latitude', 'create_date', 'nbr_confirmed_images',
                       'nbr_images', 'description', 'affiliation', 'nbr_valid_robots']
        return {field: str(getattr(self, field)) for field in field_names}

    def __unicode__(self):
        """
        To-string method.
        """
        return self.name


class SourceInvite(models.Model):
    """
    Invites will be deleted once they're accepted.
    """
    sender = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name='invites_sent', editable=False)
    recipient = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name='invites_received')
    source = models.ForeignKey(
        Source, on_delete=models.CASCADE,
        editable=False)
    source_perm = models.CharField(
        max_length=50, choices=Source._meta.permissions)

    class Meta:
        # A user can only be invited once to a source.
        unique_together = ['recipient', 'source']

    def source_perm_verbose(self):
        for permType in [Source.PermTypes.ADMIN,
                         Source.PermTypes.EDIT,
                         Source.PermTypes.VIEW]:
            if self.source_perm == permType.code:
                return permType.verbose


class Metadata(models.Model):
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

    def __unicode__(self):
        return "Metadata of " + self.name

    def to_dict(self):
        return {field: str(getattr(self, field)) for field in self.EDIT_FORM_FIELDS}


def get_original_image_upload_path(instance, filename):
    """
    Generate a destination path (on the server filesystem) for
    a data-image upload.

    # TODO: Check for filename collisions with existing files.
    # To unit test this, use a Mocker or similar on the filename randomizer,
    # and reduce the set of possible filenames to make collisions a
    # near certainty.
    """
    return settings.IMAGE_FILE_PATTERN.format(
        name=rand_string(10),
        extension=posixpath.splitext(filename)[-1])


class Image(models.Model):
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

    features = models.ForeignKey(
        'vision_backend.Features', on_delete=models.PROTECT, editable=False)

    confirmed = models.BooleanField(default=False)

    POINT_GENERATION_CHOICES = (
        (PointGen.Types.SIMPLE, PointGen.Types.SIMPLE_VERBOSE),
        (PointGen.Types.STRATIFIED, PointGen.Types.STRATIFIED_VERBOSE),
        (PointGen.Types.UNIFORM, PointGen.Types.UNIFORM_VERBOSE),
        (PointGen.Types.IMPORTED, PointGen.Types.IMPORTED_VERBOSE),
    )
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

    metadata = models.ForeignKey(Metadata, on_delete=models.PROTECT)

    source = models.ForeignKey(Source, on_delete=models.CASCADE)

    @property
    def valset(self):
        return self.pk % 8 == 0

    @property
    def trainset(self):
        return not self.valset

    def __unicode__(self):
        return self.metadata.name

    def get_image_element_title(self):
        """
        Use this as the "title" element of the image on an HTML page
        (hover the mouse over the image to see this).
        """
        # Just use the image name (usually filename).
        return self.metadata.name

    def get_annotation_status_code(self):
        """
        Returns a code for the annotation status of this image.
        """
        if self.source.enable_robot_classifier:
            if self.confirmed:
                return "confirmed"
            elif self.features.classified:
                return "unconfirmed"
            else:
                return "needs_annotation"
        else:
            if self.confirmed:
                return "annotated"
            else:
                return "needs_annotation"

    def get_annotation_status_str(self):
        """
        Returns a string describing the annotation status of this image.
        """
        code = self.get_annotation_status_code()
        if code == "confirmed":
            return "Confirmed"
        elif code == "unconfirmed":
            return "Unconfirmed"
        elif code == "needs_annotation":
            return "Needs annotation"
        elif code == "annotated":
            return "Annotated"

    def point_gen_method_display(self):
        """
        Display the point generation method in templates.
        Usage: {{ myimage.point_gen_method_display }}
        """
        return PointGen.db_to_readable_format(self.point_generation_method)

    def height_cm(self):
        return self.metadata.height_in_cm

    def annotation_area_display(self):
        """
        Display the annotation area parameters in templates.
        Usage: {{ myimage.annotation_area_display }}
        """
        return AnnotationAreaUtils.db_format_to_display(
            self.metadata.annotation_area)

    def get_process_date_short_str(self):
        """
        Return the image's (pre)process date in YYYY-MM-DD format.

        Advantage over YYYY-(M)M-(D)D: alphabetized = sorted by date
        Advantage over YYYY(M)M(D)D: date is unambiguous
        """
        return "{0}-{1:02}-{2:02}".format(
            self.process_date.year, self.process_date.month,
            self.process_date.day)


class Point(models.Model):
    row = models.IntegerField()
    column = models.IntegerField()
    point_number = models.IntegerField()
    # TODO: Is this even used anywhere? If not, delete this and rename
    # annotation_status_property to annotation_status.
    annotation_status = models.CharField(max_length=1, blank=True)
    image = models.ForeignKey(Image, on_delete=models.CASCADE)

    @property
    def annotation_status_property(self):
        try:
            annotation = self.annotation
        except ObjectDoesNotExist:
            # We use ObjectDoesNotExist instead of Annotation.DoesNotExist
            # to avoid having to import annotations.models.
            return 'unclassified'

        if is_robot_user(annotation.user):
            return 'unconfirmed'
        return 'confirmed'

    @property
    def label_code(self):
        try:
            annotation = self.annotation
        except ObjectDoesNotExist:
            # Unannotated point
            return ''

        # Annotated point
        return annotation.label_code

    @property
    def machine_confidence(self):
        try:
            scores = [s.score for s in self.score_set.all()]
            return max(scores)
        except ValueError:
            # No scores means max(scores) will raise this
            return 0

    def __unicode__(self):
        """
        To-string method.
        """
        return "Point %s" % self.point_number
