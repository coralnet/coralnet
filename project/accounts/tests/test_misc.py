from django.core import mail
from django.urls import reverse
from django.utils.html import escape

from lib.tests.utils import BasePermissionTest, CnStandardTest


class PermissionTest(BasePermissionTest):

    def test_password_change(self):
        url = reverse('password_change')
        template = 'registration/password_change_form.html'

        self.assertPermissionLevel(
            url, self.SIGNED_IN, template=template,
            deny_type=self.REQUIRE_LOGIN)

    def test_password_change_done(self):
        url = reverse('password_change_done')
        template = 'registration/password_change_done.html'

        self.assertPermissionLevel(
            url, self.SIGNED_IN, template=template,
            deny_type=self.REQUIRE_LOGIN)

    def test_emailall(self):
        url = reverse('emailall')
        template = 'accounts/email_all_form.html'

        self.assertPermissionLevel(
            url, self.SUPERUSER, template=template,
            deny_type=self.REQUIRE_LOGIN)


class PasswordChangeTest(CnStandardTest):

    @classmethod
    def setUpTestData(cls):
        # Call the parent's setup (while still using this class as cls)
        super().setUpTestData()

        cls.user = cls.create_user('sampleUsername', 'oldPassword')

    def test_change_success(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('password_change'),
            dict(
                old_password='oldPassword',
                new_password1='shinyNewPassword',
                new_password2='shinyNewPassword',
            ),
            follow=True,
        )
        self.assertTemplateUsed(
            response, 'registration/password_change_done.html')

        # Check that the password has changed: attempt to log in with the
        # new password, and check that we're signed in as the expected user.
        self.client.logout()
        self.client.login(
            username='sampleUsername', password='shinyNewPassword')
        self.assertIn('_auth_user_id', self.client.session)
        self.assertEqual(
            int(self.client.session['_auth_user_id']), self.user.pk)

    def test_old_password_incorrect(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('password_change'),
            dict(
                old_password='OLDPASSWORD',
                new_password1='shinyNewPassword',
                new_password2='shinyNewPassword',
            ),
            follow=True,
        )
        self.assertTemplateUsed(
            response, 'registration/password_change_form.html')
        self.assertContains(
            response,
            "Your old password was entered incorrectly."
            " Please enter it again.")

        # Check that the password has not changed: the old password still
        # works.
        self.client.logout()
        self.client.login(username='sampleUsername', password='oldPassword')
        self.assertIn('_auth_user_id', self.client.session)
        self.assertEqual(
            int(self.client.session['_auth_user_id']), self.user.pk)

    def test_new_password_mismatch(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('password_change'),
            dict(
                old_password='oldPassword',
                new_password1='shinyNewPassword',
                new_password2='shinyNewPassWORD',
            ),
            follow=True,
        )
        self.assertTemplateUsed(
            response, 'registration/password_change_form.html')
        self.assertContains(
            response,
            escape("The two password fields didn’t match."))

        # Check that the password has not changed.
        self.client.logout()
        self.client.login(username='sampleUsername', password='oldPassword')
        self.assertIn('_auth_user_id', self.client.session)
        self.assertEqual(
            int(self.client.session['_auth_user_id']), self.user.pk)

    def test_invalid_new_password(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('password_change'),
            dict(
                old_password='oldPassword',
                new_password1='newPass',
                new_password2='newPass',
            ),
            follow=True,
        )
        self.assertTemplateUsed(
            response, 'registration/password_change_form.html')
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


class EmailAllTest(CnStandardTest):

    @classmethod
    def setUpTestData(cls):
        # Call the parent's setup (while still using this class as cls)
        super().setUpTestData()

        cls.superuser = cls.create_superuser()
        cls.user = cls.create_user()
        cls.inactive_user = cls.create_user(activate=False)

    def test_submit(self):
        """Test submitting the form."""
        self.client.force_login(self.superuser)
        self.client.post(reverse('emailall'), data=dict(
            subject="Subject goes here",
            body="Body\ngoes here.",
        ))

        # Check that an email was sent.
        self.assertEqual(len(mail.outbox), 1)
        sent_email = mail.outbox[-1]

        # Check that the email has the expected recipients:
        # the superuser and the active user.
        # The inactive user, and special users like robot, should be excluded.
        self.assertSetEqual(
            set(sent_email.bcc),
            {self.user.email, self.superuser.email})

        # Check subject and message.
        self.assertEqual(sent_email.subject, "Subject goes here")
        self.assertEqual(sent_email.body, "Body\ngoes here.")
