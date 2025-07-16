from django.contrib.auth import get_user_model
from django.contrib.auth.forms import (
    AuthenticationForm as DefaultAuthenticationForm)
from django.contrib.auth.validators import ASCIIUsernameValidator
from django.core.validators import (
    MaxLengthValidator, validate_email, ValidationError)
from django.forms import Form, ModelForm
from django.forms.fields import BooleanField, CharField, EmailField
from django.forms.widgets import Textarea, TextInput
from django_registration.forms import (
    RegistrationForm as DefaultRegistrationForm)

from .models import Profile

User = get_user_model()


class AuthenticationForm(DefaultAuthenticationForm):
    """
    Django's default authentication form pretty much does what we want,
    since we've set our own auth backend in the Django settings.
    However, our auth backend accepts username OR email in the first field,
    so we need to change some text accordingly.

    Also, we'll add a stay_signed_in field which is handled in our
    custom sign-in view.
    """
    stay_signed_in = BooleanField(required=False, label="Stay signed in")

    error_messages = dict(
        invalid_login="The credentials you entered did not match our records."
                      " Note that both fields may be case-sensitive.",
        inactive="This account is inactive.",
    )

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request=request, *args, **kwargs)

        # Set the label for the username field.
        # Although it's slightly inaccurate now, we'll keep the field name
        # as 'username' so we don't have to override too much code.
        self.fields['username'].label = "Username or Email"


class RegistrationForm(DefaultRegistrationForm):

    agree_to_privacy_policy = BooleanField(
        required=True, label="I agree to the privacy policy")

    class Meta(DefaultRegistrationForm.Meta):
        # Include first_name and last_name.
        fields = [
            User.USERNAME_FIELD,
            'email',
            'password1',
            'password2',
            'first_name',
            'last_name',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # The default help text has a few minor issues:
        # - The word "Required" which seems redundant considering everything
        # in the form is required.
        # - Mentioning the (quite generous) max length is not necessary, and
        # might encourage users into making usernames that are longer than
        # needed.
        # - The way they enumerate the special characters is not the clearest.
        self.fields[User.USERNAME_FIELD].help_text = (
            "Allowed characters: Letters, numbers, _ - . + @")
        # The User model restricts the username length to 150 chars as of
        # Django 1.10. If we want a stricter limit, we have to enforce at Form
        # level.
        self.fields[User.USERNAME_FIELD].validators = [
            ASCIIUsernameValidator(), MaxLengthValidator(30)]

        # django-registration's email field has the un-helpful help text
        # 'email address' (in lowercase) - looks like it should've been
        # the label instead.
        self.fields['email'].required = True
        self.fields['email'].label = "Email address"
        self.fields['email'].help_text = (
            "For account activation, password recovery, site announcements,"
            " and correspondence about any labels you create")

        # These aren't required on the User model, but we want them to be
        # required on the form.
        self.fields['first_name'].required = True
        self.fields['last_name'].required = True

    def clean_username(self):
        username = self.cleaned_data.get('username')

        # Ensure the username is unique case-insensitively.
        # Django model-fields specified as unique can only do this
        # case-sensitively, so we need to check on our own.
        try:
            # Is there a case-insensitive match?
            User.objects.get(username__iexact=username)
            # Raise the same error that the original form would've raised
            # if there were a case-sensitive match.
            raise ValidationError(
                User._meta.get_field('username').error_messages['unique'],
                code='unique')
        except User.DoesNotExist:
            # Username is not taken; no error
            pass

        # Ensure the username doesn't validate as an email address.
        # Since we allow sign-in with username or email, having a username
        # match an email can create ambiguity at sign-in.
        try:
            validate_email(username)
        except ValidationError:
            # Not a valid email address string. Carry on.
            pass
        else:
            # Valid email address string.
            raise ValidationError(
                "Your username can't be an email address."
                " Note that once you've registered, you'll be able to"
                " sign in with your username or your email address.",
                code='username_is_an_email')
        return username


class RegistrationProfileForm(ModelForm):
    """Profile model fields on the user registration page."""
    class Meta:
        model = Profile
        fields = ['affiliation', 'reason_for_registering',
                  'project_description', 'how_did_you_hear_about_us']
        widgets = {
            'reason_for_registering': Textarea(),
            'project_description': Textarea(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # These aren't required on the Profile model so that old profiles
        # aren't broken, but we want it to be required for new profiles.
        self.fields['affiliation'].required = True
        self.fields['reason_for_registering'].required = True
        self.fields['project_description'].required = True
        self.fields['how_did_you_hear_about_us'].required = True


class HoneypotForm(Form):
    """
    Form to trick robots that try to fill in all fields, even ones hidden
    from view.
    If the field is filled, the form is invalid.
    """
    # We name this 'username2' so it looks similar to an actual field.
    username2 = CharField(
        label="If you're human, don't fill in this field.", required=False)

    def clean(self):
        value = self.cleaned_data.get('username2')
        if value:
            raise ValidationError(
                "If you're human, don't fill in the hidden trap field.",
                code='robot_trap')
        return value


class ActivationResendForm(Form):
    email = EmailField(
        label="Email address",
        required=True,
    )


class EmailChangeForm(Form):
    email = EmailField(
        label="New email address",
        required=True,
    )


class ProfileEditForm(ModelForm):
    class Meta:
        model = Profile
        fields = ['privacy',
                  'affiliation',
                  'website', 'location', 'about_me',
                  'avatar_file', 'use_email_gravatar']
        widgets = {
            'about_me': Textarea(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # This isn't required on the Profile model so that old profiles aren't
        # broken, but we want it to be required for new/updated profiles.
        self.fields['affiliation'].required = True


class ProfileUserEditForm(ModelForm):
    """User model fields on the profile edit page."""
    class Meta:
        model = User
        fields = ['first_name', 'last_name']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # These aren't required on the User model, but we want them to be
        # required on the form.
        self.fields['first_name'].required = True
        self.fields['last_name'].required = True


class EmailAllForm(Form):
    subject = CharField(
        label="Subject",
        widget=TextInput(attrs=dict(size=50)),
    )
    body = CharField(
        label="Body",
        widget=Textarea(attrs=dict(rows=20, cols=50)),
    )
