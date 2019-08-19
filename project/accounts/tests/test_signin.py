from __future__ import unicode_literals

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import (
    make_password, PBKDF2PasswordHasher, SHA1PasswordHasher)
from django.urls import reverse
from django_migration_testcase import MigrationTest

from lib.test_utils import BrowserTest
from ..hashers import PBKDF2WrappedSHA1PasswordHasher
from .utils import BaseAccountsTest

User = get_user_model()


class SignInTest(BaseAccountsTest):

    @classmethod
    def setUpTestData(cls):
        # Call the parent's setup (while still using this class as cls)
        super(SignInTest, cls).setUpTestData()

        cls.user = cls.create_user(
            username='testUsername', password='testPassword',
            email='tester@example.org')

    def test_load_page(self):
        response = self.client.get(reverse('login'))
        self.assertTemplateUsed(response, 'registration/login.html')

    def test_load_page_when_signed_in(self):
        """
        Can still reach the sign-in page as a signed in user. There's not
        a major use case, but nothing inherently wrong with it either.
        """
        self.client.force_login(self.user)
        response = self.client.get(reverse('login'))
        self.assertTemplateUsed(response, 'registration/login.html')

    def test_sign_in_by_username(self):
        response = self.client.post(reverse('login'), dict(
            username='testUsername', password='testPassword',
        ))

        self.assert_sign_in_success(response, self.user)

    def test_sign_in_by_email(self):
        response = self.client.post(reverse('login'), dict(
            username='tester@example.org', password='testPassword',
        ))

        self.assert_sign_in_success(response, self.user)

    def test_nonexistent_username(self):
        response = self.client.post(reverse('login'), dict(
            username='notAUsername', password='testPassword',
        ))
        self.assertTemplateUsed(response, 'registration/login.html')
        self.assertContains(
            response,
            "The credentials you entered did not match our records."
            " Note that both fields may be case-sensitive.")

    def test_username_case_insensitive(self):
        # Different case on username = still succeeds.
        response = self.client.post(reverse('login'), dict(
            username='TESTUSERNAME', password='testPassword',
        ))

        self.assert_sign_in_success(response, self.user)

    def test_nonexistent_email(self):
        response = self.client.post(reverse('login'), dict(
            username='notanemail@example.org', password='testPassword',
        ))
        self.assertTemplateUsed(response, 'registration/login.html')
        self.assertContains(
            response,
            "The credentials you entered did not match our records."
            " Note that both fields may be case-sensitive.")

    def test_email_case_sensitive(self):
        # Different case on email = failure.
        response = self.client.post(reverse('login'), dict(
            username='TESTER@example.org', password='testPassword',
        ))
        self.assertTemplateUsed(response, 'registration/login.html')
        self.assertContains(
            response,
            "The credentials you entered did not match our records."
            " Note that both fields may be case-sensitive.")

    def test_wrong_password(self):
        response = self.client.post(reverse('login'), dict(
            username='testUsername', password='testPassWORD',
        ))
        self.assertTemplateUsed(response, 'registration/login.html')
        self.assertContains(
            response,
            "The credentials you entered did not match our records."
            " Note that both fields may be case-sensitive.")

    def test_sign_in_fail_if_user_inactive(self):
        # Register but don't activate.
        self.register(
            username='alice',
            email='alice123@example.com',
            password1='GreatBarrier',
            password2='GreatBarrier',
        )

        # Attempt to sign in as the new user.
        response = self.client.post(reverse('login'), dict(
            username='alice',
            password='GreatBarrier',
        ))
        # Should not work (we should still be at the login page with an error).
        self.assertTemplateUsed(response, 'registration/login.html')
        self.assertContains(response, "This account is inactive.")


class StaySignedInTest(BrowserTest):

    @classmethod
    def setUpTestData(cls):
        # Call the parent's setup (while still using this class as cls)
        super(StaySignedInTest, cls).setUpTestData()

        cls.user = cls.create_user(
            username='testUsername', password='testPassword',
            email='tester@example.org')

    def test_stay_signed_in_true(self):
        self.login('testUsername', 'testPassword', stay_signed_in=True)
        session_cookie = self.selenium.get_cookie('sessionid')
        self.assertIn(
            'expiry', session_cookie, "Session cookie has an expiry time")

    def test_stay_signed_in_false(self):
        self.login('testUsername', 'testPassword', stay_signed_in=False)
        session_cookie = self.selenium.get_cookie('sessionid')
        self.assertNotIn(
            'expiry', session_cookie,
            "Session cookie doesn't have an expiry time,"
            " so the session will expire on browser close")


class SignInRedirectTest(BaseAccountsTest):

    @classmethod
    def setUpTestData(cls):
        # Call the parent's setup (while still using this class as cls)
        super(SignInRedirectTest, cls).setUpTestData()

        cls.user = cls.create_user(
            username='testUsername', password='testPassword',
            email='tester@example.org')

    def test_sign_in_no_sources(self):
        response = self.client.post(
            reverse('login'),
            dict(username='testUsername', password='testPassword'),
            follow=True)

        self.assert_sign_in_success(response, self.user)
        self.assertTemplateUsed(
            response, 'images/source_about.html',
            "Redirected to the About Sources page")

    def test_sign_in_with_sources(self):
        # Ensure the user is a member of at least one source
        self.create_source(self.user)
        # Sign in
        response = self.client.post(
            reverse('login'),
            dict(username='testUsername', password='testPassword'),
            follow=True)

        self.assert_sign_in_success(response, self.user)
        self.assertTemplateUsed(
            response, 'images/source_list.html',
            "Redirected to the page that lists your sources")

    def test_sign_in_with_redirect_in_url(self):
        response = self.client.post(
            reverse('login') + '?next=' + reverse('profile_edit'),
            dict(username='testUsername', password='testPassword'),
            follow=True)

        self.assert_sign_in_success(response, self.user)
        self.assertTemplateUsed(
            response, 'profiles/profile_form.html',
            "Redirected to the location specified in the URL")


class PasswordTest(BaseAccountsTest):

    @classmethod
    def setUpTestData(cls):
        # Call the parent's setup (while still using this class as cls)
        super(PasswordTest, cls).setUpTestData()

        cls.user = cls.create_user(
            username='testUsername', password='testPassword',
            email='tester@example.org')

    def test_pbkdf2_is_default_hasher(self):
        self.assertTrue(self.user.password.startswith('pbkdf2_sha256$'))

    def test_pbkdf2_password(self):
        self.user.password = make_password(
            'testPassword', hasher='pbkdf2_sha256')
        self.user.save()

        # Sign in.
        response = self.client.post(
            reverse('login'),
            dict(username='testUsername', password='testPassword'))

        self.assert_sign_in_success(response, self.user)

    def test_sha1_password_fail(self):
        """SHA1 is too weak, so it's unsupported, as per Django 1.10+
        defaults."""
        # Hashers not specified in the settings have to be passed by class
        # instance, rather than by algorithm string.
        self.user.password = make_password(
            'testPassword', hasher=SHA1PasswordHasher())
        self.user.save()

        # Sign in.
        response = self.client.post(
            reverse('login'),
            dict(username='testUsername', password='testPassword'))

        self.assertTemplateUsed(response, 'registration/login.html')
        self.assertContains(
            response,
            "The credentials you entered did not match our records."
            " Note that both fields may be case-sensitive.")

    def test_pbkdf2_wrapped_sha1_password(self):
        self.user.password = make_password(
            'testPassword', hasher='pbkdf2_wrapped_sha1')
        self.user.save()

        # Sign in.
        response = self.client.post(
            reverse('login'),
            dict(username='testUsername', password='testPassword'))

        self.assert_sign_in_success(response, self.user)


class WrapSHA1PasswordsMigrationTest(MigrationTest):

    app_name = 'accounts'
    before = '0010_make_distinct_gravatar_hashes'
    after = '0011_wrap_sha1_passwords'

    def test_sha1_password_migration_to_pbkdf2_wrapped_sha1(self):
        sha1_hasher = SHA1PasswordHasher()
        pbkdf2_hasher = PBKDF2PasswordHasher()
        wrapped_hasher = PBKDF2WrappedSHA1PasswordHasher()

        # SHA1 algorithm for user1
        user1 = User(
            username='user1',
            password=make_password(
                'testPassword1', hasher=sha1_hasher),
            email='user1@example.org')
        user1.save()

        # Default PBKDF2 algorithm for user2
        user2 = User(
            username='user2',
            password=make_password(
                'testPassword2', hasher=pbkdf2_hasher),
            email='user2@example.org')
        user2.save()

        user2_original_hash = user2.password

        # Convert SHA1 to PBKDF2 with migration
        self.run_migration()

        user1 = User.objects.get(username='user1')
        user2 = User.objects.get(username='user2')

        # user1 should now have a wrapped password
        self.assertTrue(user1.password.startswith('pbkdf2_wrapped_sha1$'))
        # user2's password should be the same
        self.assertTrue(user2.password.startswith('pbkdf2_sha256$'))
        self.assertEqual(user2.password, user2_original_hash)

        # user1's password should work with the wrapped hasher
        self.assertTrue(wrapped_hasher.verify('testPassword1', user1.password))
        # user2's password should work with the default hasher
        self.assertTrue(pbkdf2_hasher.verify('testPassword2', user2.password))