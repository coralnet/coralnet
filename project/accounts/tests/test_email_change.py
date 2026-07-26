import time

from django.conf import settings
from django.core import mail
from django.urls import reverse

from lib.tests.utils import BasePermissionTest, CnStandardTest


class PermissionTest(BasePermissionTest):

    def test_email_change(self):
        url = reverse('email_change')
        template = 'accounts/email_change_form.html'

        self.assertPermissionLevel(
            url, self.SIGNED_IN, template=template,
            deny_type=self.REQUIRE_LOGIN)

    def test_email_change_done(self):
        url = reverse('email_change_done')
        template = 'accounts/email_change_done.html'

        # Signed-out users should never see this in practice, but either way
        # it's a harmless TemplateView.
        self.assertPermissionLevel(
            url, self.SIGNED_OUT, template=template)

    def test_email_change_confirm(self):
        url = reverse('email_change_confirm', args=['a'])
        template = 'accounts/email_change_confirm.html'

        self.assertPermissionLevel(
            url, self.SIGNED_IN, template=template,
            deny_type=self.REQUIRE_LOGIN)

    def test_email_change_complete(self):
        url = reverse('email_change_complete')
        template = 'accounts/email_change_complete.html'

        # Signed-out users should never see this in practice, but either way
        # it's a harmless TemplateView.
        self.assertPermissionLevel(
            url, self.SIGNED_OUT, template=template)


class EmailChangeTest(CnStandardTest):

    @classmethod
    def setUpTestData(cls):
        # Call the parent's setup (while still using this class as cls)
        super().setUpTestData()

        cls.user = cls.create_user(
            username='sampleUsername', password='samplePassword',
            email='old.email.address@example.com')
        cls.user2 = cls.create_user()

    def submit_and_get_confirmation_link(self):
        """Shortcut function for tests focusing on the confirmation step."""
        self.client.force_login(self.user)
        self.client.post(reverse('email_change'), dict(
            email='new.email.address@example.com'))

        confirmation_email = mail.outbox[-2]
        # Confirmation link: should be the first link (first "word" with '://')
        # in the confirmation email.
        confirmation_link = None
        for word in confirmation_email.body.split():
            if '://' in word:
                confirmation_link = word
                break
        self.assertIsNotNone(confirmation_link)
        return confirmation_link

    def test_submit(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('email_change'),
            dict(email='new.email.address@example.com'), follow=True)
        self.assertTemplateUsed(response, 'accounts/email_change_done.html')

        # 2 emails should've been sent: 1 to new address and 1 to old address.
        self.assertEqual(len(mail.outbox), 2)

    def test_submit_confirmation_email_details(self):
        self.client.force_login(self.user)
        self.client.post(reverse('email_change'), dict(
            email='new.email.address@example.com'))

        confirmation_email = mail.outbox[-2]
        self.assertListEqual(
            confirmation_email.to, ['new.email.address@example.com'],
            "Recipients should be correct")
        self.assertListEqual(confirmation_email.cc, [], "cc should be empty")
        self.assertListEqual(confirmation_email.bcc, [], "bcc should be empty")
        self.assertIn(
            "Confirm your email change", confirmation_email.subject,
            "Subject template should be correct, based on subject text")
        self.assertIn(
            "Click this link to confirm usage of this email address",
            confirmation_email.body,
            "Email body template should be correct, based on body text")
        self.assertIn(
            self.user.username, confirmation_email.body,
            "Username should be in the email body")
        self.assertIn(
            "{h} hours".format(h=settings.EMAIL_CHANGE_CONFIRMATION_HOURS),
            confirmation_email.body,
            "Link validity period should be in the email body")
        self.assertIn(
            settings.ACCOUNT_QUESTIONS_LINK, confirmation_email.body,
            "Account questions link should be in the email body")

    def test_submit_notice_email_details(self):
        self.client.force_login(self.user)
        self.client.post(reverse('email_change'), dict(
            email='new.email.address@example.com'))

        notice_email = mail.outbox[-1]
        self.assertListEqual(
            notice_email.to, ['old.email.address@example.com'],
            "Recipients should be correct")
        self.assertListEqual(notice_email.cc, [], "cc should be empty")
        self.assertListEqual(notice_email.bcc, [], "bcc should be empty")
        self.assertIn(
            "Email change requested for your", notice_email.subject,
            "Subject template should be correct, based on subject text")
        self.assertIn(
            "The existing email address is this one, and the pending new email"
            " address is",
            notice_email.body,
            "Email body template should be correct, based on body text")
        self.assertIn(
            self.user.username, notice_email.body,
            "Username should be in the email body")
        self.assertIn(
            'new.email.address@example.com', notice_email.body,
            "New email address should be in the email body")
        self.assertIn(
            "{h} hours".format(h=settings.EMAIL_CHANGE_CONFIRMATION_HOURS),
            notice_email.body,
            "Link validity period should be in the email body")
        self.assertIn(
            settings.ACCOUNT_QUESTIONS_LINK, notice_email.body,
            "Account questions link should be in the email body")

    def test_confirm(self):
        confirmation_link = self.submit_and_get_confirmation_link()

        # Navigate to the confirmation link.
        response = self.client.get(confirmation_link, follow=True)
        self.assertTemplateUsed(response, 'accounts/email_change_complete.html')

        # Check that the email has changed.
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'new.email.address@example.com')

    def test_submit_invalid_email(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('email_change'), dict(
            email='not.an.email.address*AT*example.com'))
        self.assertTemplateUsed(response, 'accounts/email_change_form.html')
        self.assertContains(response, "Enter a valid email address.")

    def test_submit_email_already_exists(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('email_change'),
            dict(email=self.user2.email), follow=True)
        # Should not get an error.
        self.assertTemplateUsed(response, 'accounts/email_change_done.html')

        # Only 1 email should've been sent, to the new address.
        self.assertEqual(len(mail.outbox), 1)

        exists_email = mail.outbox[-1]
        self.assertListEqual(
            exists_email.to, [self.user2.email],
            "Recipients should be correct")
        self.assertListEqual(exists_email.cc, [], "cc should be empty")
        self.assertListEqual(exists_email.bcc, [], "bcc should be empty")
        self.assertIn(
            "About your email change request", exists_email.subject,
            "Subject template should be correct, based on subject text")
        self.assertIn(
            "tried to change a CoralNet account's email address to this"
            " address. However, there is already",
            exists_email.body,
            "Email body template should be correct, based on body text")
        self.assertIn(
            self.user2.username, exists_email.body,
            "Username should be in the email body")
        self.assertIn(
            settings.ACCOUNT_QUESTIONS_LINK, exists_email.body,
            "Account questions link should be in the email body")

    def test_confirm_signed_out(self):
        confirmation_link = self.submit_and_get_confirmation_link()
        # We'll assume the key is between the last two slashes
        # of the confirm URL.
        confirmation_key = confirmation_link.split('/')[-2]

        # Navigate to the confirmation link while signed out.
        # Should show sign-in page.
        email_change_confirm_url = reverse(
            'email_change_confirm', args=[confirmation_key])
        email_change_confirm_url_escaped = \
            email_change_confirm_url.replace(':', '%3A')
        sign_in_url = (
            reverse(settings.LOGIN_URL) + '?next='
            + email_change_confirm_url_escaped)

        self.client.logout()
        response = self.client.get(confirmation_link)
        self.assertRedirects(response, sign_in_url)
        # The email should not have changed.
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'old.email.address@example.com')

        # Now sign in. Should complete the process.
        response = self.client.post(
            sign_in_url,
            dict(username='sampleUsername', password='samplePassword'),
            follow=True,
        )
        self.assertTemplateUsed(response, 'accounts/email_change_complete.html')
        # The email should have changed.
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'new.email.address@example.com')

    def test_confirm_invalid_key(self):
        confirmation_link = self.submit_and_get_confirmation_link()

        # Chop characters off of the end of the URL to get an invalid key.
        # (Note that the last char is a slash, so must chop at least 2.)
        response = self.client.get(confirmation_link[:-3], follow=True)
        self.assertTemplateUsed(response, 'accounts/email_change_confirm.html')
        # The email should not have changed.
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'old.email.address@example.com')

    def test_confirm_expired_key(self):
        # Have a confirmation-key expiration time of 0.5 seconds
        with self.settings(EMAIL_CHANGE_CONFIRMATION_HOURS=(0.5 / 3600.0)):
            confirmation_link = self.submit_and_get_confirmation_link()

            # Wait 1 second before using the confirmation link
            time.sleep(1)
            response = self.client.get(confirmation_link, follow=True)
            self.assertTemplateUsed(
                response, 'accounts/email_change_confirm.html')

        # The email should not have changed.
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'old.email.address@example.com')

    def test_confirm_signed_in_as_other_user(self):
        confirmation_link = self.submit_and_get_confirmation_link()

        # Attempt to confirm as a different user.
        self.client.force_login(self.user2)
        response = self.client.get(confirmation_link)
        self.assertTemplateUsed(response, 'accounts/email_change_confirm.html')
        # The email should not have changed.
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'old.email.address@example.com')
