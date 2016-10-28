import time
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.urlresolvers import reverse
from lib.test_utils import ClientTest

User = get_user_model()


class SignInTest(ClientTest):

    @classmethod
    def setUpTestData(cls):
        # Call the parent's setup (while still using this class as cls)
        super(SignInTest, cls).setUpTestData()

        cls.user = cls.create_user(
            username='testUsername', password='testPassword',
            email='tester@example.org')

    def test_load_page(self):
        response = self.client.get(reverse('auth_login'))
        self.assertTemplateUsed(response, 'registration/login.html')

    def test_load_page_when_signed_in(self):
        """
        Can still reach the sign-in page as a signed in user. There's not
        a major use case, but nothing inherently wrong with it either.
        """
        self.client.force_login(self.user)
        response = self.client.get(reverse('auth_login'))
        self.assertTemplateUsed(response, 'registration/login.html')

    def test_sign_in_by_username(self):
        response = self.client.post(reverse('auth_login'), dict(
            username='testUsername', password='testPassword',
        ))

        # We should be past the sign-in page now.
        self.assertTemplateNotUsed(response, 'registration/login.html')

        # Check that we're signed in as the expected user.
        # From http://stackoverflow.com/a/6013115
        self.assertIn('_auth_user_id', self.client.session)
        self.assertEqual(
            int(self.client.session['_auth_user_id']), self.user.pk)

    # TODO: Add tests for getting redirected to the expected page
    # (about sources, source list, or whatever was in the 'next' URL
    # parameter).
    # TODO: Add tests that submit the sign-in form with errors.


class RegisterTest(ClientTest):

    @classmethod
    def setUpTestData(cls):
        # Call the parent's setup (while still using this class as cls)
        super(RegisterTest, cls).setUpTestData()

        cls.user = cls.create_user()

    def test_load_page(self):
        response = self.client.get(reverse('registration_register'))
        self.assertTemplateUsed(response, 'registration/registration_form.html')

    def test_load_page_when_signed_in(self):
        """
        Can still reach the register page as a signed in user. There's not
        a major use case, but nothing inherently wrong with it either.
        """
        self.client.force_login(self.user)
        response = self.client.get(reverse('registration_register'))
        self.assertTemplateUsed(response, 'registration/registration_form.html')

    # TODO: Test registration form errors.

    def test_register_success(self):
        username = 'alice'
        email_address = 'alice123@example.com'
        response = self.client.post(reverse('registration_register'), dict(
            username=username,
            email=email_address,
            password1='GreatBarrier',
            password2='GreatBarrier',
        ))

        self.assertRedirects(response, reverse('registration_complete'))

        # Check that an activation email was sent.
        self.assertEqual(len(mail.outbox), 1)
        # Check that the intended recipient is the only recipient.
        activation_email = mail.outbox[-1]
        self.assertEqual(len(activation_email.to), 1)
        self.assertEqual(activation_email.to[0], email_address)

        # Check that the new user exists, but is inactive.
        user = User.objects.get(username=username, email=email_address)
        self.assertFalse(user.is_active)

    def test_sign_in_fail_before_activation(self):
        username = 'alice'
        email_address = 'alice123@example.com'
        password = 'GreatBarrier'
        self.client.post(reverse('registration_register'), dict(
            username=username,
            email=email_address,
            password1=password,
            password2=password,
        ))

        # Check that the new user exists, but is inactive.
        user = User.objects.get(username=username, email=email_address)
        self.assertFalse(user.is_active)

        # Attempt to sign in as the new user.
        response = self.client.post(reverse('auth_login'), dict(
            username=username,
            password=password,
        ))
        # Should not work (we should still be at the login page with an error).
        self.assertTemplateUsed(response, 'registration/login.html')
        self.assertContains(response, "This account is inactive.")

    def test_activate_success(self):
        username = 'alice'
        email_address = 'alice123@example.com'
        password = 'GreatBarrier'
        self.client.post(reverse('registration_register'), dict(
            username=username,
            email=email_address,
            password1=password,
            password2=password,
        ))

        activation_email = mail.outbox[-1]
        # Activation link: should be the first link (first "word" with '://')
        # in the activation email.
        activation_link = None
        for word in activation_email.body.split():
            if '://' in word:
                activation_link = word
                break
        self.assertIsNotNone(activation_link)

        # Navigate to the activation link.
        response = self.client.get(activation_link)
        self.assertRedirects(
            response, reverse('registration_activation_complete'))

        # Attempt to sign in as the new user.
        response = self.client.post(reverse('auth_login'), dict(
            username=username,
            password=password,
        ))
        # Should work (we should be past the login page now).
        self.assertTemplateNotUsed(response, 'registration/login.html')


class EmailChangeTest(ClientTest):

    @classmethod
    def setUpTestData(cls):
        # Call the parent's setup (while still using this class as cls)
        super(EmailChangeTest, cls).setUpTestData()

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

    def test_load_submit_page_signed_out(self):
        """Load page while logged out -> login page."""
        response = self.client.get(reverse('email_change'))
        self.assertRedirects(
            response,
            reverse(settings.LOGIN_URL)+'?next='+reverse('email_change'),
        )

    def test_load_submit_page(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('email_change'))
        self.assertTemplateUsed(response, 'accounts/email_change_form.html')

    def test_submit(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('email_change'),
            dict(email='new.email.address@example.com'), follow=True)
        self.assertTemplateUsed(response, 'accounts/email_change_done.html')

    def test_submit_confirmation_email_details(self):
        self.client.force_login(self.user)
        self.client.post(reverse('email_change'), dict(
            email='new.email.address@example.com'))

        confirmation_email = mail.outbox[-2]
        self.assertListEqual(
            confirmation_email.to, ['new.email.address@example.com'])
        self.assertIn(self.user.username, confirmation_email.body)
        self.assertIn(
            "{h} hours".format(h=settings.EMAIL_CHANGE_CONFIRMATION_HOURS),
            confirmation_email.body)

    def test_submit_notice_email_details(self):
        self.client.force_login(self.user)
        self.client.post(reverse('email_change'), dict(
            email='new.email.address@example.com'))

        notice_email = mail.outbox[-1]
        self.assertListEqual(
            notice_email.to, ['old.email.address@example.com'])
        self.assertIn(self.user.username, notice_email.body)
        self.assertIn('new.email.address@example.com', notice_email.body)
        self.assertIn(
            "{h} hours".format(h=settings.EMAIL_CHANGE_CONFIRMATION_HOURS),
            notice_email.body)

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

    def test_confirm_signed_out(self):
        confirmation_link = self.submit_and_get_confirmation_link()
        # We'll assume the key is between the last two slashes
        # of the confirm URL.
        confirmation_key = confirmation_link.split('/')[-2]

        # Navigate to the confirmation link while signed out.
        # Should show sign-in page.
        self.client.logout()
        sign_in_url = (
            reverse(settings.LOGIN_URL) + '?next='
            + reverse('email_change_confirm', args=[confirmation_key])
                .replace(':', '%3A'))
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
        with self.settings(EMAIL_CHANGE_CONFIRMATION_HOURS=(1.0 / 7200.0)):
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


class EmailAllTest(ClientTest):

    @classmethod
    def setUpTestData(cls):
        # Call the parent's setup (while still using this class as cls)
        super(EmailAllTest, cls).setUpTestData()

        cls.user = cls.create_user()

    def test_load_page_anonymous(self):
        """Load page while logged out -> login page."""
        response = self.client.get(reverse('emailall'))
        self.assertRedirects(
            response,
            reverse(settings.LOGIN_URL)+'?next='+reverse('emailall'),
        )

    def test_load_page_normal_user(self):
        """Load page as normal user -> login page."""
        self.client.force_login(self.user)
        response = self.client.get(reverse('emailall'))
        self.assertRedirects(
            response,
            reverse(settings.LOGIN_URL)+'?next='+reverse('emailall'),
        )

    def test_load_page_superuser(self):
        """Load page as superuser -> page loads normally."""
        self.client.force_login(self.superuser)
        response = self.client.get(reverse('emailall'))
        self.assertTemplateUsed(response, 'accounts/email_all_form.html')

    def test_submit(self):
        """Test submitting the form."""
        self.client.force_login(self.superuser)
        self.client.post(reverse('emailall'), data=dict(
            subject="Subject goes here",
            body="Body\ngoes here.",
        ))

        # Check that an email was sent.
        self.assertEqual(len(mail.outbox), 1)
        # Check that the email has the expected number of recipients:
        # the number of users with an email address.
        # (Special users like 'robot' don't have emails.)
        num_of_users = User.objects.all().exclude(email='').count()
        self.assertEqual(len(mail.outbox[-1].bcc), num_of_users)

        # TODO: Check the emails in more detail: subject, message, and
        # possibly checking at least some of the bcc addresses.
