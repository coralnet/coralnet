from django.conf import settings
from django.urls import include, path, re_path
from django.views.generic.base import TemplateView
from . import views
from .forms import AuthenticationForm


urlpatterns = [
    # Customizations of django-registration and django.contrib.auth views.
    # These come before the django-registration URL include, because
    # in urlpatterns, URLs that come first take precedence.
    path('login/',
         views.LoginView.as_view(
             template_name='registration/login.html',
             authentication_form=AuthenticationForm),
         name='login'),
    path('password_reset/',
         views.PasswordResetView.as_view(
             extra_email_context=dict(
                account_questions_link=settings.ACCOUNT_QUESTIONS_LINK)),
         name='password_reset'),
    path('register/',
         views.register,
         name='django_registration_register'),

    # django-registration URLs, such as account activation.
    path('', include('django_registration.backends.activation.urls')),

    # django.contrib.auth URLs, such as login and password reset.
    path('', include('django.contrib.auth.urls')),

    # Views for re-sending an activation email, in case it expired or got lost.
    path('activation/resend/',
         views.ActivationResendView.as_view(),
         name='activation_resend'),
    path('activation/resend/complete/',
         TemplateView.as_view(
             template_name='django_registration/activation_resend_complete.html'
         ),
         name='activation_resend_complete'),

    # Email-change views.
    path('email/change/',
         views.EmailChangeView.as_view(),
         name='email_change'),
    path('email/change/done/',
         TemplateView.as_view(
             template_name='accounts/email_change_done.html'),
         name='email_change_done'),
    re_path(r'^email/change/confirm/(?P<confirmation_key>[-:\w]+)/$',
            views.EmailChangeConfirmView.as_view(),
            name='email_change_confirm'),
    path('email/change/complete/',
         TemplateView.as_view(
             template_name='accounts/email_change_complete.html'
         ),
         name='email_change_complete'),

    # Profile views.
    path('profile/list/',
         views.profile_list,
         name='profile_list'),
    path('profile/detail/<int:user_id>/',
         views.profile_detail,
         name='profile_detail'),
    path('profile/edit/',
         views.ProfileEditView.as_view(),
         name='profile_edit'),
    path('profile/edit/cancel/',
         views.profile_edit_cancel,
         name='profile_edit_cancel'),

    # Other accounts related views.
    path('emailall/',
         views.email_all,
         name='emailall'),
]
