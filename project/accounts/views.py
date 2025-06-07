from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView as DefaultLoginView
from django.core import signing
from django.core.mail import EmailMessage
from django.shortcuts import redirect, render, get_object_or_404
from django.template.loader import render_to_string
from django.views.decorators.debug import sensitive_post_parameters
from django.views.generic.base import TemplateView
from django.views.generic.edit import FormView

from django_registration.backends.activation.views \
    import RegistrationView as ThirdPartyRegistrationView

from lib.utils import paginate
from .forms import (
    ActivationResendForm, EmailAllForm, EmailChangeForm,
    HoneypotForm, ProfileEditForm, ProfileUserEditForm,
    RegistrationForm, RegistrationProfileForm)
from .models import Profile
from .utils import can_view_profile

User = get_user_model()


class LoginView(DefaultLoginView):

    def form_valid(self, form):
        """Action to take when the form is valid."""
        # Log in and create a redirect response.
        response = super().form_valid(form)

        if not form.cleaned_data.get('stay_signed_in'):
            # stay_signed_in checkbox is NOT checked, so make the session
            # expire on browser close. Otherwise, the session's
            # duration is defined by SESSION_COOKIE_AGE.
            # https://docs.djangoproject.com/en/dev/topics/http/sessions/#django.contrib.sessions.backends.base.SessionBase.set_expiry
            # http://stackoverflow.com/questions/15100400/
            self.request.session.set_expiry(0)

        return response


class BaseRegistrationView(ThirdPartyRegistrationView):
    def get_email_context(self, activation_key):
        """
        Build the template context used for the activation email.
        """
        context = super().get_email_context(activation_key)
        context['account_questions_link'] = settings.ACCOUNT_QUESTIONS_LINK
        context['forum_link'] = settings.FORUM_LINK
        return context


@sensitive_post_parameters()
def register(request, *args, **kwargs):
    return RegistrationView.as_view()(request, *args, **kwargs)


class RegistrationView(BaseRegistrationView):
    success_url = 'django_registration_complete'

    def get_context_data(self, **kwargs):
        if 'main_form' not in kwargs:
            kwargs['main_form'] = RegistrationForm()
        if 'profile_form' not in kwargs:
            kwargs['profile_form'] = RegistrationProfileForm()
        if 'honeypot_form' not in kwargs:
            kwargs['honeypot_form'] = HoneypotForm()
        return kwargs

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, self.get_context_data())

    def post(self, request, *args, **kwargs):
        main_form = RegistrationForm(request.POST)
        profile_form = RegistrationProfileForm(request.POST)
        honeypot_form = HoneypotForm(request.POST)

        if main_form.is_valid() and profile_form.is_valid()\
           and honeypot_form.is_valid():

            # Check for unique email. This doesn't invalidate the form
            # because we don't want to make it obvious on-site that the
            # email is taken. We'll only tell the email owner.
            #
            # Our registration allows case-sensitive email distinction
            # because some email domains support that (unfortunately).
            # http://stackoverflow.com/questions/9807909/
            email = main_form.cleaned_data['email']

            if User.objects.filter(email=email).exists():
                existing_user = User.objects.get(email=email)
                self.send_already_exists_email(existing_user, email)
            else:
                # Clear to create a user and profile.
                new_user = self.register(main_form)

                profile = profile_form.instance
                profile.user = new_user
                profile.save()

            return redirect(self.success_url)

        messages.error(request, 'Please correct the errors below.')
        return render(request, self.template_name, self.get_context_data(
            main_form=main_form,
            profile_form=profile_form,
            honeypot_form=honeypot_form,
        ))

    def send_already_exists_email(self, existing_user, email_address):
        context = dict(username=existing_user.username)

        subject = render_to_string(
            'django_registration/registration_email_exists_subject.txt',
            context)
        # Force subject to a single line to avoid header-injection issues.
        subject = ''.join(subject.splitlines())
        message = render_to_string(
            'django_registration/registration_email_exists_email.txt',
            context, request=self.request)

        already_exists_email = EmailMessage(
            subject=subject,
            body=message,
            to=[email_address],
        )
        already_exists_email.send()


class ActivationResendView(BaseRegistrationView):
    """
    Activation-email sending functionality is defined in the registration view
    class, so this view class inherits from that class to re-use that
    functionality.
    However, since the view itself does activation resending, not registration,
    we obviously have to override some parts.
    """
    form_class = ActivationResendForm
    success_url = 'activation_resend_complete'
    template_name = 'django_registration/activation_resend_form.html'

    def form_valid(self, form):
        email = form.cleaned_data['email']
        if User.objects.filter(email=email).exists():
            user = User.objects.get(email=email)
            self.send_activation_email(user)

        # TODO: Send a different email if the email address doesn't have
        # a corresponding user.
        # This shouldn't be common, so it's not urgent, but would be nice.
        # There is potential for bot abuse, as it's a form accessible when
        # logged out; so ideally add a honeypot field to ActivationResendForm
        # when doing this.

        return redirect(self.success_url)

    def get_form(self, form_class=None):
        """
        django-registration implements a get_form() method in its registration
        view, but we don't want that implementation, because that assumes a
        form class which is a user ModelForm. We just want the plain old
        FormView get_form() implementation.
        """
        return FormView.get_form(self, form_class=form_class)


class EmailChangeView(LoginRequiredMixin, FormView):
    form_class = EmailChangeForm
    success_url = 'email_change_done'
    template_name = 'accounts/email_change_form.html'

    def form_valid(self, form):
        email = form.cleaned_data['email']
        if User.objects.filter(email=email).exists():
            existing_user = User.objects.get(email=email)
            self.send_already_exists_email(existing_user, email)
        else:
            self.send_confirmation_email(email)
            self.send_notice_email_to_old_address(email)
        return redirect(self.success_url)

    def send_confirmation_email(self, pending_email_address):
        confirmation_key = self.get_confirmation_key(
            self.request.user, pending_email_address)
        context = dict(
            username=self.request.user.username,
            confirmation_key=confirmation_key,
            expiration_hours=settings.EMAIL_CHANGE_CONFIRMATION_HOURS,
        )

        subject = render_to_string(
            'accounts/email_change_confirmation_subject.txt', context)
        # Force subject to a single line to avoid header-injection issues.
        subject = ''.join(subject.splitlines())

        message = render_to_string(
            'accounts/email_change_confirmation_email.txt',
            context, request=self.request)

        confirmation_email = EmailMessage(
            subject=subject,
            body=message,
            to=[pending_email_address],
        )
        confirmation_email.send()

    @staticmethod
    def get_confirmation_key(user, pending_email_address):
        return signing.dumps(obj=dict(
            pk=user.pk,
            email=pending_email_address,
        ))

    def send_notice_email_to_old_address(self, pending_email_address):
        context = dict(
            username=self.request.user.username,
            pending_email_address=pending_email_address,
            expiration_hours=settings.EMAIL_CHANGE_CONFIRMATION_HOURS,
        )

        subject = render_to_string(
            'accounts/email_change_notice_subject.txt', context)
        # Force subject to a single line to avoid header-injection issues.
        subject = ''.join(subject.splitlines())

        message = render_to_string(
            'accounts/email_change_notice_email.txt',
            context, request=self.request)

        confirmation_email = EmailMessage(
            subject=subject,
            body=message,
            to=[self.request.user.email],
        )
        confirmation_email.send()

    def send_already_exists_email(self, existing_user, email_address):
        context = dict(other_username=existing_user.username)

        subject = render_to_string(
            'accounts/email_change_exists_subject.txt', context)
        # Force subject to a single line to avoid header-injection issues.
        subject = ''.join(subject.splitlines())
        message = render_to_string(
            'accounts/email_change_exists_email.txt',
            context, request=self.request)

        already_exists_email = EmailMessage(
            subject=subject,
            body=message,
            to=[email_address],
        )
        already_exists_email.send()


class EmailChangeConfirmView(LoginRequiredMixin, TemplateView):
    template_name = 'accounts/email_change_confirm.html'
    success_url = 'email_change_complete'

    def get(self, *args, **kwargs):
        confirmed = self.confirm_email_change(*args, **kwargs)
        if confirmed:
            return redirect(self.success_url)
        return super().get(*args, **kwargs)

    def confirm_email_change(self, *args, **kwargs):
        new_email_address = self.validate_key(kwargs.get('confirmation_key'))
        if new_email_address is not None:
            user = self.request.user
            user.email = new_email_address
            user.save()
            return True
        return False

    def validate_key(self, confirmation_key):
        try:
            obj = signing.loads(
                confirmation_key,
                max_age=settings.EMAIL_CHANGE_CONFIRMATION_HOURS * 60 * 60,
            )
        # SignatureExpired is a subclass of BadSignature, so this will
        # catch either one.
        except signing.BadSignature:
            return None

        # Check that the signed-in user is the same as the user who sent
        # the email change request.
        if self.request.user.pk != obj['pk']:
            return None

        # Return the new email address (which we got by un-signing the
        # confirmation key).
        return obj['email']


def profile_list(request):
    all_profiles = Profile.objects.all().order_by('user__date_joined')
    all_results = [p for p in all_profiles if can_view_profile(request, p)]
    page_results = paginate(
        results=all_results,
        items_per_page=50,
        request_args=request.GET,
    )

    return render(request, 'profiles/profile_list.html', {
        'page_results': page_results,
    })


def profile_detail(request, user_id):
    profile_user = get_object_or_404(User, pk=user_id)
    profile = profile_user.profile

    can_view = can_view_profile(request, profile)

    if can_view:
        return render(request, 'profiles/profile_detail.html', {
            'profile': profile,
        })
    else:
        return render(request, 'permission_denied.html', {
            'message': "You don't have permission to view this profile.",
        })


class ProfileEditView(LoginRequiredMixin, FormView):
    template_name = 'profiles/profile_form.html'

    def get_context_data(self, **kwargs):
        if 'main_form' not in kwargs:
            kwargs['main_form'] = ProfileEditForm(
                instance=self.request.user.profile)
        if 'user_form' not in kwargs:
            kwargs['user_form'] = ProfileUserEditForm(
                instance=self.request.user)
        return kwargs

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, self.get_context_data())

    def post(self, request, *args, **kwargs):
        main_form = ProfileEditForm(
            request.POST, request.FILES, instance=request.user.profile)
        user_form = ProfileUserEditForm(request.POST, instance=request.user)

        if main_form.is_valid() and user_form.is_valid():
            main_form.save()
            user_form.save()
            messages.success(request, "Profile edited successfully.")
            return redirect('profile_detail', request.user.pk)

        messages.error(request, 'Please correct the errors below.')
        return render(request, self.template_name, self.get_context_data(
            main_form=main_form,
            user_form=user_form,
        ))


@login_required
def profile_edit_cancel(request):
    messages.success(request, "Edit cancelled.")
    return redirect('profile_detail', request.user.pk)


@permission_required('is_superuser')
def email_all(request):
    """View for sending an email to all registered users."""
    if request.method == 'POST':
        form = EmailAllForm(request.POST)

        if form.is_valid():
            active_users = User.objects.filter(is_active=True)
            email_list = []
            for u in active_users:
                if u.email:
                    email_list.append(u.email)

            email = EmailMessage(
                subject=form.cleaned_data['subject'],
                body=form.cleaned_data['body'],
                # BLIND-cc the users to not reveal
                # everyone's emails to everyone else.
                bcc=email_list,
            )
            email.send()

            messages.success(request, "Successfully sent emails.")
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = EmailAllForm()

    return render(request, 'accounts/email_all_form.html', {
        'form': form,
    })
