import time

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import override_settings
from django.urls import reverse
from django.utils.html import escape

from lib.tests.utils import BasePermissionTest
from .utils import BaseAccountsTest

User = get_user_model()


class PermissionTest(BasePermissionTest):
    """Test permissions for registration and activation views."""

    def test_register(self):
        url = reverse('django_registration_register')
        template = 'django_registration/registration_form.html'

        self.assertPermissionLevel(
            url, self.SIGNED_OUT, template=template)

    def test_registration_complete(self):
        url = reverse('django_registration_complete')
        template = 'django_registration/registration_complete.html'

        self.assertPermissionLevel(
            url, self.SIGNED_OUT, template=template)

    def test_activate(self):
        url = reverse('django_registration_activate', args=['a'])
        template = 'django_registration/activation_failed.html'

        self.assertPermissionLevel(
            url, self.SIGNED_OUT, template=template)

    def test_activation_complete(self):
        url = reverse('django_registration_activation_complete')
        template = 'django_registration/activation_complete.html'

        self.assertPermissionLevel(
            url, self.SIGNED_OUT, template=template)

    def test_activation_resend(self):
        url = reverse('activation_resend')
        template = 'django_registration/activation_resend_form.html'

        self.assertPermissionLevel(
            url, self.SIGNED_OUT, template=template)

    def test_activation_resend_complete(self):
        url = reverse('activation_resend_complete')
        template = 'django_registration/activation_resend_complete.html'

        self.assertPermissionLevel(
            url, self.SIGNED_OUT, template=template)


class RegisterTest(BaseAccountsTest):

    def test_load_page(self):
        response = self.client.get(reverse('django_registration_register'))
        self.assertContains(
            response, settings.ACCOUNT_QUESTIONS_LINK,
            msg_prefix="Account questions link should be on the page")

    def test_success(self):
        response = self.register()
        self.assertTemplateUsed(
            response, 'django_registration/registration_complete.html')

        # Check that an activation email was sent.
        self.assertEqual(len(mail.outbox), 1)

        # Check that the new user exists, but is inactive.
        user = User.objects.get(username='alice', email='alice123@example.com')
        self.assertFalse(user.is_active)

    @override_settings(DEFAULT_FROM_EMAIL="default_from_name@domain.edu")
    def test_email_details(self):
        self.register()

        activation_email = mail.outbox[-1]
        self.assertListEqual(
            activation_email.to, ['alice123@example.com'],
            "Recipients should be correct")
        self.assertListEqual(activation_email.cc, [], "cc should be empty")
        self.assertListEqual(activation_email.bcc, [], "bcc should be empty")
        self.assertIn(
            "Activate your new CoralNet account", activation_email.subject,
            "Subject template should be correct, based on subject text")
        self.assertIn(
            "Please activate your new account using this link",
            activation_email.body,
            "Email body template should be correct, based on body text")
        self.assertIn(
            'alice', activation_email.body,
            "Newly registered username should be in the email body")
        self.assertIn(
            "valid for {days} days".format(
                days=settings.ACCOUNT_ACTIVATION_DAYS),
            activation_email.body,
            "Link validity period should be in the email body")
        self.assertIn(
            settings.ACCOUNT_QUESTIONS_LINK, activation_email.body,
            "Account questions link should be in the email body")
        self.assertIn(
            settings.FORUM_LINK, activation_email.body,
            "Forum link should be in the email body")
        self.assertIn(
            reverse('privacy_policy'), activation_email.body,
            "Privacy policy link should be in the email body")
        self.assertIn(
            reverse('about'), activation_email.body,
            "About link should be in the email body")
        self.assertIn(
            'default_from_name@domain.edu', activation_email.body,
            "DEFAULT_FROM_EMAIL should be in the email body")
        # Other tests should already test activation via the email's activation
        # link, so we won't check for the activation link here.

    def test_username_already_exists(self):
        # Register once.
        self.register()
        # Register again with the same username, but different other fields.
        response = self.register(
            username='alice',
            email='alice456@example.com',
            password1='GBRAustralia',
            password2='GBRAustralia',
        )

        # We should still be at the registration page with an error.
        self.assertTemplateUsed(
            response, 'django_registration/registration_form.html')
        self.assertContains(
            response, "A user with that username already exists.")

    def test_username_existence_case_insensitive(self):
        self.register()
        # 'Alice' still matches 'alice'.
        response = self.register(
            username='Alice',
            email='alice456@example.com',
        )

        # We should still be at the registration page with an error.
        self.assertTemplateUsed(
            response, 'django_registration/registration_form.html')
        self.assertContains(
            response, "A user with that username already exists.")

    def test_username_must_not_validate_as_email_address(self):
        response = self.register(
            username='alice@ucsd.edu',
        )

        # We should still be at the registration page with an error.
        self.assertTemplateUsed(
            response, 'django_registration/registration_form.html')
        self.assertContains(
            response, escape(
                "Your username can't be an email address."
                " Note that once you've registered, you'll be able to"
                " sign in with your username or your email address."))

    def test_username_reject_too_long(self):
        """
        Reject usernames longer than 30 characters.
        """
        response = self.register(
            username='alice67890123456789012345678901',
            email='alice67890123456789012345678901@example.com',
        )

        # We should still be at the registration page with an error.
        self.assertTemplateUsed(
            response, 'django_registration/registration_form.html')
        self.assertContains(
            response,
            escape(
                "Ensure this value has at most 30 characters (it has 31)."))

    def test_username_reject_unicode(self):
        """
        Reject non-ASCII Unicode characters in usernames. First/last name
        fields can be more flexible, but usernames should be simple and easy
        to read/type/differentiate for everyone.
        """
        response = self.register(
            username='Béatrice',
            email='beatrice123@example.com',
        )

        # We should still be at the registration page with an error.
        self.assertTemplateUsed(
            response, 'django_registration/registration_form.html')
        self.assertContains(
            response, escape("Enter a valid username."))

    def test_username_reject_unicode_confusables(self):
        """
        Reject Unicode characters which are 'confusable', i.e. often look
        the same as other characters.
        This should be default behavior in django-registration 2.3+, even if
        Unicode characters were generally allowed.
        """
        response = self.register(
            # The 'a' in 'alice' here is a CYRILLIC SMALL LETTER A
            username='аlice123',
            email='alice123@example.com',
        )

        # We should still be at the registration page with an error.
        self.assertTemplateUsed(
            response, 'django_registration/registration_form.html')
        self.assertContains(
            response, escape("Enter a valid username."))

    def test_email_already_exists(self):
        # Register once.
        self.register()
        # Register again with the same email, but different other fields.
        response = self.register(
            username='alice123',
            email='alice123@example.com',
            password1='GBRAustralia',
            password2='GBRAustralia',
        )
        # Should not get an error.
        self.assertTemplateUsed(
            response, 'django_registration/registration_complete.html')

        # 2 emails should've been sent: 1 for first registration and
        # 1 for second registration attempt.
        self.assertEqual(len(mail.outbox), 2)

        # Check that no new user exists.
        self.assertFalse(User.objects.filter(username='alice123').exists())

    def test_email_existence_case_sensitive(self):
        self.register()
        # Capitalizing the A in the email makes it register as different.
        # There do exist email systems that register accounts differing only
        # by capitalization (unfortunately).
        response = self.register(
            username='alice123',
            email='Alice123@example.com',
        )
        # Should not get an error.
        self.assertTemplateUsed(
            response, 'django_registration/registration_complete.html')

        # 2 emails, 1 for each registration (notably, the 2nd registration
        # went through).
        self.assertEqual(len(mail.outbox), 2)
        # For the latest registration, check that the intended recipient
        # is the only recipient.
        activation_email = mail.outbox[-1]
        self.assertEqual(len(activation_email.to), 1)
        self.assertEqual(activation_email.to[0], 'Alice123@example.com')

        # Check that the new user exists, but is inactive.
        user = User.objects.get(
            username='alice123', email='Alice123@example.com')
        self.assertFalse(user.is_active)

    def test_email_already_exists_email_details(self):
        self.register()
        self.register(
            username='alice123',
            email='alice123@example.com',
        )

        exists_email = mail.outbox[-1]

        self.assertListEqual(
            exists_email.to, ['alice123@example.com'],
            "Recipients should be correct")
        self.assertListEqual(exists_email.cc, [], "cc should be empty")
        self.assertListEqual(exists_email.bcc, [], "bcc should be empty")
        self.assertIn(
            "About your CoralNet account request", exists_email.subject,
            "Subject template should be correct, based on subject text")
        self.assertIn(
            "tried to register a CoralNet account with this email address."
            " However, there is already",
            exists_email.body,
            "Email body template should be correct, based on body text")
        existing_user = User.objects.get(email='alice123@example.com')
        self.assertIn(
            existing_user.username, exists_email.body,
            "Username should be in the email body")
        self.assertIn(
            settings.ACCOUNT_QUESTIONS_LINK, exists_email.body,
            "Account questions link should be in the email body")

    def test_email_reject_unicode(self):
        """
        Generally reject non-ASCII Unicode characters in email addresses.
        This may change in the future depending on this ticket:
        https://code.djangoproject.com/ticket/27029
        """
        response = self.register(
            username='alice123',
            email='アリス@example.com',
        )

        self.assertTemplateUsed(
            response, 'django_registration/registration_form.html')
        self.assertContains(
            response, escape("Enter a valid email address."))

    def test_email_reject_unicode_confusables(self):
        """
        Reject Unicode characters which are 'confusable', i.e. look
        the same as other common characters in most fonts.
        This should be default behavior in django-registration 2.3+, even if
        Unicode characters were generally allowed.
        """
        response = self.register(
            username='alice123',
            # The 'a' in 'alice' here is a CYRILLIC SMALL LETTER A
            email='аlice123@example.com',
        )

        # We should still be at the registration page with an error.
        self.assertTemplateUsed(
            response, 'django_registration/registration_form.html')
        self.assertContains(
            response, escape("Enter a valid email address."))

    def test_password_fields_do_not_match(self):
        response = self.register(
            password1='GreatBarrier',
            password2='greatBarrier',
        )

        # We should still be at the registration page with an error.
        self.assertTemplateUsed(
            response, 'django_registration/registration_form.html')
        self.assertContains(
            response, escape("The two password fields didn’t match."))

    def test_password_too_short(self):
        """
        There are other password related errors too. For now we'll just
        check that at least one is working.
        """
        response = self.register(
            password1='GBR',
            password2='GBR',
        )

        # We should still be at the registration page with an error.
        self.assertTemplateUsed(
            response, 'django_registration/registration_form.html')
        self.assertContains(
            response, "This password is too short.")

    def test_first_name_required(self):
        response = self.register(first_name='')

        self.assertTemplateUsed(
            response, 'django_registration/registration_form.html')
        self.assertContains(response, "This field is required.")

    def test_last_name_required(self):
        response = self.register(last_name='')

        self.assertTemplateUsed(
            response, 'django_registration/registration_form.html')
        self.assertContains(response, "This field is required.")

    def test_affiliation_required(self):
        response = self.register(affiliation='')

        self.assertTemplateUsed(
            response, 'django_registration/registration_form.html')
        self.assertContains(response, "This field is required.")

    def test_reason_for_registering_required(self):
        response = self.register(reason_for_registering='')

        self.assertTemplateUsed(
            response, 'django_registration/registration_form.html')
        self.assertContains(response, "This field is required.")

    def test_project_description_required(self):
        response = self.register(project_description='')

        self.assertTemplateUsed(
            response, 'django_registration/registration_form.html')
        self.assertContains(response, "This field is required.")

    def test_how_did_you_hear_about_us_required(self):
        response = self.register(how_did_you_hear_about_us='')

        self.assertTemplateUsed(
            response, 'django_registration/registration_form.html')
        self.assertContains(response, "This field is required.")

    def test_did_not_agree_to_policy(self):
        response = self.register(agree_to_privacy_policy=False)

        self.assertTemplateUsed(
            response, 'django_registration/registration_form.html')
        self.assertContains(response, "This field is required.")

    def test_honeypot(self):
        response = self.register(username2='a')

        self.assertTemplateUsed(
            response, 'django_registration/registration_form.html')
        self.assertContains(
            response,
            escape("If you're human, don't fill in the hidden trap field."))

    def test_provided_fields_saved_to_database(self):
        self.register()
        user = User.objects.get(username='alice')
        self.assertEqual(user.first_name, "Alice")
        self.assertEqual(user.last_name, "Baker")
        self.assertEqual(user.profile.affiliation, "Testing Society")
        self.assertEqual(
            user.profile.reason_for_registering, "Trying labeling tools")
        self.assertEqual(user.profile.project_description, "Labeling corals")
        self.assertEqual(user.profile.how_did_you_hear_about_us, "Colleagues")

    def test_email_based_gravatar_defaults_to_false(self):
        self.register()
        user = User.objects.get(username='alice')
        self.assertFalse(user.profile.use_email_gravatar)


class ActivateTest(BaseAccountsTest):

    def test_success(self):
        activation_link = self.register_and_get_activation_link()

        # Navigate to the activation link.
        response = self.client.get(activation_link, follow=True)
        self.assertTemplateUsed(
            response, 'django_registration/activation_complete.html')

        # The user should be active.
        user = User.objects.get(username='alice')
        self.assertTrue(user.is_active)

    def test_bad_key(self):
        activation_link = self.register_and_get_activation_link()

        # Chop characters off of the end of the URL to get an invalid key.
        # (Note that the last char is a slash, so must chop at least 2.)
        response = self.client.get(activation_link[:-3], follow=True)

        self.assertTemplateUsed(
            response, 'django_registration/activation_failed.html',
            msg_prefix="Should get the activation failure template"
        )
        self.assertEqual(
            response.context['activation_error']['code'], 'invalid_key')
        self.assertContains(
            response, "Sorry, this activation link doesn't seem to be valid.")

        # The user should still be inactive.
        user = User.objects.get(username='alice')
        self.assertFalse(user.is_active)

    def test_expired_key(self):
        # Have an activation-key expiration time of 0.5 seconds
        with self.settings(ACCOUNT_ACTIVATION_DAYS=(0.5 / 86400.0)):
            activation_link = self.register_and_get_activation_link()

            # Wait 1 second before using the confirmation link
            time.sleep(1)
            response = self.client.get(activation_link, follow=True)

        self.assertTemplateUsed(
            response, 'django_registration/activation_failed.html')
        self.assertEqual(
            response.context['activation_error']['code'], 'expired')
        self.assertContains(response, "Sorry, this activation link expired.")

        # The user should still be inactive.
        user = User.objects.get(username='alice')
        self.assertFalse(user.is_active)

    def test_already_activated(self):
        activation_link = self.register_and_get_activation_link()

        # Activate.
        self.client.get(activation_link, follow=True)

        # The user should now be active.
        user = User.objects.get(username='alice')
        self.assertTrue(user.is_active)

        # Attempt to activate again. Should get the failure template because
        # the user is already active.
        response = self.client.get(activation_link, follow=True)
        self.assertTemplateUsed(
            response, 'django_registration/activation_failed.html')
        self.assertEqual(
            response.context['activation_error']['code'], 'already_activated')
        self.assertContains(response, "Your account's already active!")


class ActivationResendTest(BaseAccountsTest):

    def test_success(self):
        # Register. This sends an email.
        self.register(email='alice123@example.com')

        # Re-send activation email.
        response = self.client.post(
            reverse('activation_resend'),
            dict(email='alice123@example.com'), follow=True)
        self.assertTemplateUsed(
            response, 'django_registration/activation_resend_complete.html')

        # Should have 2 emails now.
        self.assertEqual(len(mail.outbox), 2)
        # Check the latest email.
        latest_activation_email = mail.outbox[-1]
        # Check that the intended recipient is the only recipient.
        self.assertEqual(len(latest_activation_email.to), 1)
        self.assertEqual(latest_activation_email.to[0], 'alice123@example.com')

        # Activate with this email's activation link.
        activation_link = None
        for word in latest_activation_email.body.split():
            if '://' in word:
                activation_link = word
                break
        self.assertIsNotNone(activation_link)
        self.client.get(activation_link)
        # The user should be active.
        user = User.objects.get(username='alice')
        self.assertTrue(user.is_active)
