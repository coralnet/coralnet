from django.conf import settings
from django.core import mail
from django.urls import reverse
from django.utils.html import escape

from lib.tests.utils import BasePermissionTest, CnStandardTest


class PermissionTest(BasePermissionTest):

    def test_password_reset(self):
        url = reverse('password_reset')
        template = 'registration/password_reset_form.html'

        # Page should be usable while signed out, since the point of the page
        # is to help people trying to sign in. Also usable while signed in;
        # not a big use case, but doesn't hurt.
        self.assertPermissionLevel(
            url, self.SIGNED_OUT, template=template)

    def test_password_reset_done(self):
        url = reverse('password_reset_done')
        template = 'registration/password_reset_done.html'

        self.assertPermissionLevel(
            url, self.SIGNED_OUT, template=template)

    def test_password_reset_confirm(self):
        url = reverse('password_reset_confirm', args=['a', 'a-a'])
        template = 'registration/password_reset_confirm.html'

        self.assertPermissionLevel(
            url, self.SIGNED_OUT, template=template)

    def test_password_reset_complete(self):
        url = reverse('password_reset_complete')
        template = 'registration/password_reset_complete.html'

        self.assertPermissionLevel(
            url, self.SIGNED_OUT, template=template)


class PasswordResetTest(CnStandardTest):

    @classmethod
    def setUpTestData(cls):
        # Call the parent's setup (while still using this class as cls)
        super().setUpTestData()

        cls.user = cls.create_user(
            username='sampleUsername', password='oldPassword',
            email='email.address@example.com')

    def submit_and_get_reset_link(self):
        """Shortcut function for tests focusing on the final reset step."""
        self.client.post(reverse('password_reset'), dict(
            email='email.address@example.com'))

        instructions_email = mail.outbox[-1]
        # Reset link: should be the first link (first "word" with '://')
        # in the email.
        reset_link = None
        for word in instructions_email.body.split():
            if '://' in word:
                reset_link = word
                break
        self.assertIsNotNone(reset_link)
        return reset_link

    def test_submit(self):
        response = self.client.post(
            reverse('password_reset'),
            dict(email='email.address@example.com'), follow=True)
        self.assertTemplateUsed(
            response, 'registration/password_reset_done.html')

        # Email should've been sent.
        self.assertEqual(len(mail.outbox), 1)

    def test_submit_with_nonexistent_email(self):
        """Even if the email address is not in CoralNet's database, this form
        should still submit successfully - with the usual wording to the effect
        of 'we've sent an email, if our DB has this address'. This way,
        snoopers can't check if an arbitrary email address (which they
        don't own) is in the database or not."""
        response = self.client.post(
            reverse('password_reset'),
            dict(email='notacoralnetemail@example.com'), follow=True)
        self.assertTemplateUsed(
            response, 'registration/password_reset_done.html')

        # Since our DB does not have this address, we won't actually send an
        # email.
        self.assertEqual(len(mail.outbox), 0)

    def test_submit_with_empty_email(self):
        response = self.client.post(
            reverse('password_reset'),
            dict(), follow=True)
        self.assertTemplateUsed(
            response, 'registration/password_reset_form.html')
        self.assertContains(
            response,
            "This field is required.")

    def test_submit_instructions_email_details(self):
        self.client.post(reverse('password_reset'), dict(
            email='email.address@example.com'))

        instructions_email = mail.outbox[-1]
        self.assertListEqual(
            instructions_email.to, ['email.address@example.com'],
            "Recipients should be correct")
        self.assertListEqual(instructions_email.cc, [], "cc should be empty")
        self.assertListEqual(instructions_email.bcc, [], "bcc should be empty")
        self.assertIn(
            "Reset your password", instructions_email.subject,
            "Subject template should be correct, based on subject text")
        self.assertIn(
            "you requested a password reset",
            instructions_email.body,
            "Email body template should be correct, based on body text")
        self.assertIn(
            self.user.username, instructions_email.body,
            "Username should be in the email body")
        self.assertIn(
            settings.ACCOUNT_QUESTIONS_LINK, instructions_email.body,
            "Account questions link should be in the email body")

    def test_reset(self):
        reset_link = self.submit_and_get_reset_link()

        # Navigate to the reset link.
        response = self.client.get(reset_link, follow=True)
        self.assertTemplateUsed(
            response, 'registration/password_reset_confirm.html')

        # We actually got redirected to a different URL without the pass-reset
        # token (for security purposes), so we need to get that URL for the
        # next step.
        reset_redirect_url = response.wsgi_request.path

        # Complete the password reset.
        response = self.client.post(
            reset_redirect_url,
            dict(
                new_password1='shinyNewPassword',
                new_password2='shinyNewPassword',
            ),
            follow=True,
        )
        self.assertTemplateUsed(
            response, 'registration/password_reset_complete.html')

        # Check that the password has changed: attempt to log in with the
        # new password, and check that we're signed in as the expected user.
        self.client.logout()
        self.client.login(
            username='sampleUsername', password='shinyNewPassword')
        self.assertIn('_auth_user_id', self.client.session)
        self.assertEqual(
            int(self.client.session['_auth_user_id']), self.user.pk)

    def test_reset_with_password_mismatch(self):
        reset_link = self.submit_and_get_reset_link()

        # Navigate to the reset link.
        response = self.client.get(reset_link, follow=True)
        self.assertTemplateUsed(
            response, 'registration/password_reset_confirm.html')
        reset_redirect_url = response.wsgi_request.path

        # Submit the password reset form with a password mismatch.
        response = self.client.post(
            reset_redirect_url,
            dict(
                new_password1='shinyNewPassword',
                new_password2='shinyNewPassWORD',
            ),
            follow=True,
        )
        self.assertTemplateUsed(
            response, 'registration/password_reset_confirm.html')
        self.assertContains(
            response,
            escape("The two password fields didn’t match."))

        # Check that the password has not changed.
        self.client.logout()
        self.client.login(username='sampleUsername', password='oldPassword')
        self.assertIn('_auth_user_id', self.client.session)
        self.assertEqual(
            int(self.client.session['_auth_user_id']), self.user.pk)

    def test_reset_with_invalid_password(self):
        reset_link = self.submit_and_get_reset_link()

        # Navigate to the reset link.
        response = self.client.get(reset_link, follow=True)
        self.assertTemplateUsed(
            response, 'registration/password_reset_confirm.html')
        reset_redirect_url = response.wsgi_request.path

        # Submit the password reset form with an invalid password.
        response = self.client.post(
            reset_redirect_url,
            dict(
                new_password1='newPass',
                new_password2='newPass',
            ),
            follow=True,
        )
        self.assertTemplateUsed(
            response, 'registration/password_reset_confirm.html')
        self.assertContains(
            response,
            "This password is too short. It must contain at least"
            " 10 characters.")

        # Check that the password has not changed.
        self.client.logout()
        self.client.login(username='sampleUsername', password='oldPassword')
        self.assertIn('_auth_user_id', self.client.session)
        self.assertEqual(
            int(self.client.session['_auth_user_id']), self.user.pk)
