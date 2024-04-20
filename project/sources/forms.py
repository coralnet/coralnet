from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.forms import Form, ModelForm
from django.forms.fields import CharField, ChoiceField
from django.forms.widgets import NumberInput, TextInput

from images.utils import get_aux_label_field_names
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


class ImageSourceForm(ModelForm):

    class Media:
        js = (
            "js/SourceFormHelper.js",
        )

    class Meta:
        model = Source
        # Some of the fields are handled by separate forms, so this form
        # doesn't have all of the Source model's fields.
        fields = [
            'name', 'visibility', 'description', 'affiliation',
            'key1', 'key2', 'key3', 'key4', 'key5',
            'confidence_threshold',
            'feature_extractor_setting',
            'longitude', 'latitude',
        ]
        widgets = {
            'confidence_threshold': NumberInput(
                attrs={'min': 0, 'max': 100, 'size': 3}),
            'longitude': TextInput(attrs={'size': 10}),
            'latitude': TextInput(attrs={'size': 10}),
        }

    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)

        if self.instance.pk:
            # Edit source form should have a way to detect and indicate (via
            # Javascript) that the feature extractor setting has changed.
            self.fields['feature_extractor_setting'].widget.attrs.update({
                'data-original-value': self.instance.feature_extractor_setting,
                'onchange': 'SourceFormHelper.updateVisibilityOfExtractorChangeWarning()',
            })
        else:
            # New source form shouldn't have this field.
            del self.fields['confidence_threshold']

        # These aren't required by the model (probably to support old sources)
        # but should be required in the form.
        self.fields['longitude'].required = True
        self.fields['latitude'].required = True

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
        except:
            raise ValidationError("Latitude is not a number.")
        if latitude < -90 or latitude > 90:
            raise ValidationError("Latitude is out of range.")
        return data

    def clean_longitude(self):
        data = self.cleaned_data['longitude']
        try:
            longitude = float(data)
        except:
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
