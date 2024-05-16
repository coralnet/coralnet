import math
from typing import Tuple

from django.conf import settings
from django.contrib.auth.models import User
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from guardian.shortcuts import (
    assign_perm,
    get_objects_for_user,
    get_perms,
    get_users_with_perms,
    remove_perm,
)

from annotations.model_utils import AnnotationArea
from images.model_utils import PointGen
from labels.models import LabelSet
from vision_backend.common import SourceExtractorChoices
from vision_backend.models import Classifier


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

    # Will change this to a BigAutoField later.
    id = models.AutoField(primary_key=True)

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

    default_point_generation_method = models.CharField(
        "Point generation method",
        max_length=50,
        # 30 is the median for public sources as of late 2023.
        default=PointGen(type='simple', points=30).db_value,
    )

    image_annotation_area = models.CharField(
        "Default image annotation area",
        max_length=50,
        # Whole image is a reasonable non-arbitrary default, and
        # serves to demonstrate what a valid value looks like for
        # this field.
        default=AnnotationArea(
            type=AnnotationArea.TYPE_PERCENTAGES,
            min_x=0, max_x=100, min_y=0, max_y=100).db_value,
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

    trains_own_classifiers = models.BooleanField(
        "Source trains its own classifiers",
        default=True,
    )
    # Classifier belonging to another source which is deployed for
    # classification in this source.
    deployed_classifier = models.ForeignKey(
        Classifier,
        # This field should not place any restrictions on the other source's
        # ability to manage its classifiers. So, for example, this shouldn't
        # be PROTECT.
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='deploying_sources',
    )
    # In case the deployed classifier gets deleted, this is a 'backup' pointer
    # to the source that the classifier was from.
    # This is a BigIntegerField instead of a ForeignKey because:
    # 1) This way we can distinguish between a source which simply does not
    #    use robots vs. a source which had its deployed-source deleted.
    # 2) This way we don't worry about any complexities regarding
    #    self-referential FKs.
    # 3) This is just a backup pointer. Generally,
    #    `deployed_classifier__source` can be used to get the same
    #    relationship.
    #
    # Since this is a redundant field, we automatically set it in save().
    deployed_source_id = models.BigIntegerField(
        null=True, blank=True,
    )

    feature_extractor_setting = models.CharField(
        "Feature extractor",
        max_length=50,
        choices=SourceExtractorChoices.choices,
        default=SourceExtractorChoices.EFFICIENTNET.value)

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
            fullCode = 'sources.' + code
            verbose = 'Admin'

        class EDIT:
            code = 'source_edit'
            fullCode = 'sources.' + code
            verbose = 'Edit'

        class VIEW:
            code = 'source_view'
            fullCode = 'sources.' + code
            verbose = 'View'

    @property
    def feature_extractor(self) -> str | None:
        if not self.trains_own_classifiers and not self.deployed_classifier:
            # We consider this source to have no feature extraction config.
            return None

        if settings.FORCE_DUMMY_EXTRACTOR:
            # Use dummy extractor for tests.
            # The real extractors are relatively slow.
            return 'dummy'

        if self.trains_own_classifiers:
            # Read feature extractor name from this source's field.
            return self.feature_extractor_setting

        # Else, using deployed_classifier.
        # Read feature extractor name from the classifier's source's field.
        return self.deployed_classifier.source.feature_extractor_setting

    ##########
    # Helper methods for sources
    ##########
    @staticmethod
    def get_public_sources():
        return Source.objects.filter(visibility=Source.VisibilityTypes.PUBLIC)\
            .order_by('name')

    @staticmethod
    def get_sources_of_user(user):
        """
        Get all sources that the user is a member of.

        Special cases due to how permissions work: this returns ALL sources
        for 1) superusers, and 2) users granted the global source-view perm.
        """
        if user.is_authenticated:
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
            assign_perm(Source.PermTypes.ADMIN.code, user, self)
            assign_perm(Source.PermTypes.EDIT.code, user, self)
            assign_perm(Source.PermTypes.VIEW.code, user, self)
        elif role == Source.PermTypes.EDIT.code:
            assign_perm(Source.PermTypes.EDIT.code, user, self)
            assign_perm(Source.PermTypes.VIEW.code, user, self)
        elif role == Source.PermTypes.VIEW.code:
            assign_perm(Source.PermTypes.VIEW.code, user, self)
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
        """
        Return True if the user should have permission to see this source;
        False otherwise.
        """
        return (
            # Anyone can see public sources.
            (self.visibility == Source.VisibilityTypes.PUBLIC)

            # Users can see sources that they're a member of.
            #
            # This checks the DB for an object-level permission.
            # Even if `code` was used to assign source membership perms,
            # checking `fullCode` works here too.
            or user.has_perm(Source.PermTypes.VIEW.fullCode, self)

            # Users granted the global source-view perm can see all sources.
            #
            # This checks the DB for a global permission.
            # Only `fullCode` is accepted for checking global permissions,
            # since there are no other args to infer the app from.
            # Note that has_perm(A) does NOT imply has_perm(A, object).
            # has_perm() literally checks if the specified permission object
            # exists in the DB. It doesn't perform any logic beyond that.
            or user.has_perm(Source.PermTypes.VIEW.fullCode)
        )

    def get_all_images(self):
        # Avoid circular dependency between modules
        from images.models import Image

        return Image.objects.filter(source=self)

    @property
    def nbr_confirmed_images(self):
        return self.image_set.confirmed().count()

    @property
    def nbr_images(self):
        return self.image_set.count()

    @property
    def nbr_accepted_robots(self):
        return len(self.get_accepted_robots())

    @property
    def best_robot_accuracy(self):
        robot = self.get_current_classifier()
        if robot is None:
            return None
        else:
            return robot.accuracy

    def point_gen_method_display(self):
        """
        Display the point generation method in templates.
        Usage: {{ mysource.point_gen_method_display }}
        """
        return str(
            PointGen.from_db_value(self.default_point_generation_method))

    def annotation_area_display(self):
        """
        Display the annotation area parameters in templates.
        Usage: {{ mysource.annotation_area_display }}
        """
        return str(AnnotationArea.from_db_value(self.image_annotation_area))

    def get_current_classifier(self):
        """
        Returns the classifier currently used for image classification
        in this source, or None if no such classifier is available.
        """
        try:
            return self.classifier_set.filter(
                status=Classifier.ACCEPTED).latest('pk')
        except Classifier.DoesNotExist:
            return None

    def get_accepted_robots(self):
        """
        Returns a list of all robots that have been accepted for use in the
        source
        """
        return self.classifier_set.filter(
            status=Classifier.ACCEPTED).order_by('pk')

    def need_new_robot(self) -> Tuple[bool, str]:
        """
        Returns:
        1) True if the source needs to train a new robot, False otherwise.
        2) The reason why it needs a new robot or not.
        """
        if not self.trains_own_classifiers:
            return False, "Source has training disabled"

        nbr_confirmed_images_with_features = (
            self.image_set.confirmed().with_features().count()
        )
        if (nbr_confirmed_images_with_features
                < settings.TRAINING_MIN_IMAGES):
            return False, "Not enough annotated images for initial training"

        try:
            latest_classifier_attempt = self.classifier_set.exclude(
                status=Classifier.TRAIN_PENDING).latest('pk')
        except Classifier.DoesNotExist:
            return True, "No classifier yet"

        if latest_classifier_attempt.status == Classifier.TRAIN_ERROR:
            return True, "Last training resulted in an error"

        # Check whether there are enough newly annotated images
        # since the time the previous classifier was submitted.
        #
        # The threshold should be calculated in such a way that, as long as
        # the threshold multiplier > 1, the threshold is strictly greater
        # than the latest robot's image count. This way we don't infinitely
        # retrain when there are no new images.
        threshold_for_new = math.ceil(
            settings.NEW_CLASSIFIER_TRAIN_TH
            * latest_classifier_attempt.nbr_train_images
        )
        has_enough = nbr_confirmed_images_with_features >= threshold_for_new
        message = (
            f"Need {threshold_for_new} annotated images for next training,"
            f" and currently have {nbr_confirmed_images_with_features}")
        return has_enough, message

    def has_robot(self):
        """
        Returns True if source has an accepted robot.
        """
        return self.get_current_classifier() is not None

    def all_image_names_are_unique(self):
        """
        Return true if all images in the source have unique names.
        NOTE: this will be enforced during import moving forward, but it
        wasn't originally.
        """
        # Avoid circular dependency between modules
        from images.models import Image

        images = Image.objects.filter(source=self)
        nunique = len(set([i.metadata.name for i in images]))
        return nunique == images.count()

    def get_nonunique_image_names(self):
        """
        returns a list of image names which occur for multiple images in the
        source.
        NOTE: there is probably a fancy SQL way to do this, but I found it
        cleaner with a python solution. It's not time critical.
        """
        # Avoid circular dependency between modules
        from images.models import Image

        imnames = [i.metadata.name for i in Image.objects.filter(source=self)]
        return list(set([name for name in imnames if imnames.count(name) > 1]))

    def to_dict(self):
        """
        Returns the model as python dict of the form:
            {field_name: field_value}
        Both field name and values are strings.
        """
        field_names = ['pk', 'name', 'longitude', 'latitude', 'create_date',
                       'nbr_confirmed_images', 'nbr_images', 'description',
                       'affiliation', 'nbr_accepted_robots',
                       'best_robot_accuracy']

        return {field: str(getattr(self, field)) for
                field in field_names}

    def __str__(self):
        """
        To-string method.
        """
        return self.name


class SourceInvite(models.Model):
    """
    An invite for a user to join a source.
    Invites will be deleted once they're accepted/declined.
    """
    # Will change this to a BigAutoField later.
    id = models.AutoField(primary_key=True)

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
