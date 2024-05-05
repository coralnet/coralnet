from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.forms import Form, ModelForm
from django.forms.fields import CharField, ChoiceField
from django.forms.widgets import NumberInput, TextInput
from django.urls import reverse

from annotations.forms import AnnotationAreaPercentsField
from images.forms import PointGenField
from images.utils import get_aux_label_field_names
from lib.forms import FieldsetsFormComponent, GridFormRenderer
from .models import Source, SourceInvite
from .utils import aux_label_name_collisions


def validate_aux_meta_field_name(field_name):
    """
    Check if an aux. field is used to denote date, year or similar.
    :return: The passed field name.
    :raise: ValidationError if the name isn't valid.
    """
    date_strings = {'date', 'year', 'time', 'month', 'day'}
    if field_name.lower() in date_strings:
        raise ValidationError(
            "Date of image acquisition is already a default metadata field."
            " Do not use auxiliary metadata fields"
            " to encode temporal information."
        )
    return field_name


# This probably would go better in a '?' button's help text,
# which is generally defined in an HTML template.
confidence_threshold_help_text = \
"""The CoralNet alleviate feature offers a trade-off between fully automated and fully manual annotation. This is done by auto-accepting machine annotations when they are sufficiently confident.

This auto-acceptance happens when you enter the annotation tool for an image. Effectively, the machine's most confident points are "alleviated" from your annotation workload (for that image). Alleviated annotation decisions are treated as 'Confirmed', and are included when you export your annotations.

Users control this functionality by specifying the classifier confidence threshold. For example, with 90% confidence threshold all point annotation for which the classifier is more than 90% confident will be done automatically.

When the first robot version is trained for your source, you can see the trade-off between confidence threshold, the fraction of points above each threshold, and the annotation accuracy. We recommend that you set the confidence threshold to 100% until you have seen this trade-off curve.

<a href="https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0130312">This study</a> suggests that a 5% drop is annotation accuracy has marginal (if any) impact on derived cover estimates. We therefore suggest that you set the level of confidence threshold corresponding to a 5% drop in accuracy.
"""


class SourceForm(FieldsetsFormComponent, ModelForm):

    class Meta:
        model = Source
        fields = [
            'name', 'visibility', 'description', 'affiliation',
            'key1', 'key2', 'key3', 'key4', 'key5',
            'default_point_generation_method',
            'image_annotation_area',
            'confidence_threshold',
            'feature_extractor_setting',
            'longitude', 'latitude',
        ]
        field_classes = {
            'default_point_generation_method': PointGenField,
            'image_annotation_area': AnnotationAreaPercentsField,
        }
        widgets = {
            'confidence_threshold': NumberInput(
                attrs={'min': 0, 'max': 100, 'size': 3}),
            'longitude': TextInput(attrs={'size': 10}),
            'latitude': TextInput(attrs={'size': 10}),
        }

    default_renderer = GridFormRenderer

    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)

        is_edit_form = self.instance.pk is not None

        if is_edit_form:
            # Edit source form should have a way to detect and indicate (via
            # Javascript) that the feature extractor setting has changed.
            self.fields['feature_extractor_setting'].widget.attrs.update({
                'data-original-value': self.instance.feature_extractor_setting,
            })

        if not is_edit_form or not self.instance.enable_robot_classifier:
            # This field should not be in the new source form, or in the
            # edit source form when classifiers are disabled.
            del self.fields['confidence_threshold']

        if is_edit_form and not self.instance.enable_robot_classifier:
            # This field should not be in the edit form when classifiers are
            # disabled.
            del self.fields['feature_extractor_setting']

        # These aren't required by the model (probably to support old sources)
        # but should be required in the form.
        self.fields['longitude'].required = True
        self.fields['latitude'].required = True

        # This fieldsets definition uses stuff that can't be evaluated
        # at import time, such as reverse(), so we define it
        # in __init__() here.
        self.fieldsets = [
            dict(
                header="General Information",
                help_text=f"""To learn about the differences between public and private sources, please read our <a href="{reverse('about')}#datapolicy">data policy</a>.""",
                fields=[
                    'name', 'visibility', 'affiliation', 'description',
                ],
            ),

            dict(
                header="Names for Auxiliary Metadata Fields",
                help_text="""We provide several standard metadata fields for your images such as Date, Camera, Photographer, etc. These 5 auxiliary metadata fields, on the other hand, can be named anything you like.
                
                    We encourage using these auxiliary metadata fields to guide how your images are organized. For example, if your coral images are taken at 5 different sites, then you can name one of these metadata fields Site, and then specify a site for each image: North Point, East Shore, etc. You will then be able to do things such as browse through all unannotated images from North Point, or aggregate coral coverage statistics over the images from East Shore.
                 
                    You can use as few or as many of these 5 metadata fields as you like.""",
                fields=[
                    'key1', 'key2', 'key3', 'key4', 'key5',
                ],
            ),

            dict(
                header="Image Annotation",
                subfieldsets=[
                    dict(
                        header="Default image annotation area",
                        help_text="""This defines a rectangle of the image where annotation points are allowed to be generated.
                            For example, X boundaries of 10% and 95% mean that the leftmost 10% and the rightmost 5% of the image will not have any points. Decimals like 95.6% are allowed.
                            Later, you can also set these boundaries as pixel counts on a per-image basis; for images that don't have a specific value set, these percentages will be used.""",
                        fields=[
                            'image_annotation_area',
                        ],
                        template_name='annotations/annotation_area_percents_fieldset.html',
                    ),

                    dict(
                        header="Point generation method",
                        help_text="""When we create annotation points for uploaded images, this is how we'll generate the point locations within each image.
                        
                            Simple Random: For every point, we randomly pick a pixel location from the image's entire annotation area.
                            Stratified Random: We consider the annotation area to be divided into a grid of cells; for example, 3 rows and 4 columns of cells, for a total of 12 cells. Then, within each cell, we generate a certain number of random points.
                            Uniform Grid: Again, we divide the annotation area into a grid of cells. Then, within each cell, we place 1 point at the center of that cell.
                            
                            Note that if you change this setting later on, it will NOT apply to images that are already uploaded.""",
                        fields=[
                            'default_point_generation_method',
                        ],
                    ),

                    dict(
                        header="Level of alleviation",
                        help_text=confidence_threshold_help_text,
                        fields=['confidence_threshold'],
                    ),

                    dict(
                        header="Feature extractor",
                        help_text="""We recommend the EfficientNet extractor for all use-cases. It is faster and 2-3% more accurate on average. It is a more modern neural network architecture and trained on more data. The legacy VGG16 extractor is provided only for sources that want to retain their old classifiers, for example, if they are already deployed in a survey.""",
                        fields=['feature_extractor_setting'],
                    ),
                ],
            ),

            dict(
                header="World Location",
                help_text=f"""We'll use this to mark your source on our front-page map. Your source will be shown on the map if it contains at least {settings.MAP_IMAGE_COUNT_TIERS[0]} images, and the source name doesn't include words like "test". To get your source's coordinates, try <a href="https://www.latlong.net/" target="_blank">latlong.net</a>.""",
                fields=[
                    'latitude', 'longitude',
                ],
            ),
        ]

    def clean_key1(self):
        return validate_aux_meta_field_name(self.cleaned_data['key1'])
    def clean_key2(self):
        return validate_aux_meta_field_name(self.cleaned_data['key2'])
    def clean_key3(self):
        return validate_aux_meta_field_name(self.cleaned_data['key3'])
    def clean_key4(self):
        return validate_aux_meta_field_name(self.cleaned_data['key4'])
    def clean_key5(self):
        return validate_aux_meta_field_name(self.cleaned_data['key5'])

    def clean_latitude(self):
        data = self.cleaned_data['latitude']
        try:
            latitude = float(data)
        except ValueError:
            raise ValidationError("Latitude is not a number.")
        if latitude < -90 or latitude > 90:
            raise ValidationError("Latitude is out of range.")
        return data

    def clean_longitude(self):
        data = self.cleaned_data['longitude']
        try:
            longitude = float(data)
        except ValueError:
            raise ValidationError("Longitude is not a number.")
        if longitude < -180 or longitude > 180:
            raise ValidationError("Longitude is out of range.")
        return data

    def clean(self):
        """
        Check for aux label name collisions with other aux fields or built-in
        metadata fields.
        Since this involves comparing the aux labels with each other,
        it has to be implemented in the form-wide clean function.
        """
        cleaned_data = super().clean()

        aux_label_kwargs = dict(
            (n, cleaned_data.get(n))
            for n in get_aux_label_field_names()
            if n in cleaned_data
        )

        # Initialize a dummy Source (which we won't actually save) with the
        # aux label values. We'll just use this to call our function which
        # checks for name collisions.
        dummy_source = Source(**aux_label_kwargs)
        dupe_labels = aux_label_name_collisions(dummy_source)
        if dupe_labels:
            # Add an error to any field which has one of the dupe labels.
            for field_name, field_label in aux_label_kwargs.items():
                if field_label.lower() in dupe_labels:
                    self.add_error(
                        field_name,
                        ValidationError(
                            "This conflicts with either a built-in metadata"
                            " field or another auxiliary field.",
                            code='dupe_label',
                        ))


class SourceChangePermissionForm(Form):

    perm_change = ChoiceField(
        label='Permission Level', choices=Source._meta.permissions)

    def __init__(self, *args, **kwargs):
        self.source_id = kwargs.pop('source_id')
        user = kwargs.pop('user')
        super().__init__(*args, **kwargs)
        source = Source.objects.get(pk=self.source_id)
        members = source.get_members_ordered_by_role()
        member_list = [(member.id, member.username) for member in members]

        # This removes the current user from users that can have their
        # permission changed
        if (user.id, user.username) in member_list:
            member_list.remove((user.id, user.username))
        self.fields['user'] = ChoiceField(
            label='User', choices=[member for member in member_list],
            required=True)


class SourceRemoveUserForm(Form):

    def __init__(self, *args, **kwargs):
        self.source_id = kwargs.pop('source_id')
        self.user = kwargs.pop('user')
        super().__init__(*args, **kwargs)
        source = Source.objects.get(pk=self.source_id)
        members = source.get_members_ordered_by_role()
        member_list = [(member.id, member.username) for member in members]

        # This removes the current user from users that can have their
        # permission changed
        if (self.user.id, self.user.username) in member_list:
            member_list.remove((self.user.id, self.user.username))
        self.fields['user'] = ChoiceField(
            label='User', choices=[member for member in member_list],
            required=True)


class SourceInviteForm(Form):
    # This is not a ModelForm, because a ModelForm would by default
    # make us use a dropdown/radiobutton for the recipient field,
    # and it would validate that the recipient field's value is a
    # foreign key id.  This is a slight pain to work around if we
    # want a text box for the recipient field, so it's easier
    # to just use a Form.

    recipient = CharField(
        max_length=User._meta.get_field('username').max_length,
        help_text="The recipient's username.")
    source_perm = ChoiceField(
        label='Permission level',
        choices=SourceInvite._meta.get_field('source_perm').choices)

    def __init__(self, *args, **kwargs):
        self.source_id = kwargs.pop('source_id')
        super().__init__(*args, **kwargs)

    def clean_recipient(self):
        """
        This method cleans the recipient field of a submitted form.
        It is automatically called during form validation.

        1. Strip spaces.
        2. Check that we have a valid recipient username.
        If so, replace the username with the recipient user's id.
        If not, throw an error.
        """

        recipient_username = self.cleaned_data['recipient']
        recipient_username = recipient_username.strip()

        try:
            User.objects.get(username=recipient_username)
        except User.DoesNotExist:
            raise ValidationError("There is no user with this username.")

        return recipient_username

    def clean(self):
        """
        Looking at both the recipient and the source, see if we have an
        error case:
        (1) The recipient is already a member of the source.
        (2) The recipient has already been invited to the source.
        """

        if 'recipient' not in self.cleaned_data:
            return super().clean()

        recipient_user = User.objects.get(
            username=self.cleaned_data['recipient'])
        source = Source.objects.get(pk=self.source_id)

        if source.has_member(recipient_user):
            msg = "{username} is already in this Source.".format(
                username=recipient_user.username)
            self.add_error('recipient', msg)
            return super().clean()

        try:
            SourceInvite.objects.get(recipient=recipient_user, source=source)
        except SourceInvite.DoesNotExist:
            pass
        else:
            msg = "{username} has already been invited to this Source.".format(
                username=recipient_user.username)
            self.add_error('recipient', msg)

        super().clean()
