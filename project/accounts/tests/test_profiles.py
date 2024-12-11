import hashlib

from bs4 import BeautifulSoup
from django.shortcuts import resolve_url
from django.urls import reverse

from lib.tests.utils import BasePermissionTest, ClientTest
from ..models import Profile


class ProfilePermissionTest(BasePermissionTest):

    @classmethod
    def setUpTestData(cls):
        # Call the parent's setup (while still using this class as cls)
        super().setUpTestData()

        # Profile is open to everyone
        cls.user_open = cls.create_user_with_privacy('open')
        # Profile is open to registered users only
        cls.user_registered = cls.create_user_with_privacy('registered')
        # Profile is private (though admins can still see it)
        cls.user_closed = cls.create_user_with_privacy('closed')

    @classmethod
    def create_user_with_privacy(cls, privacy_value):
        """Create a user and set their profile privacy to a specific value."""
        user = cls.create_user()
        user.profile.privacy = privacy_value
        user.profile.save()
        return user


class ProfileListPermissionTest(ProfilePermissionTest):

    def assertProfileNameOnList(self, visiting_user, profile_name):
        if visiting_user:
            self.client.force_login(visiting_user)
        else:
            self.client.logout()
        response = self.client.get(resolve_url('profile_list'))
        response_soup = BeautifulSoup(response.content, 'html.parser')
        # We make sure to exclude the page header, which has the current
        # user's username.
        main_content_soup = response_soup.find('div', id='content-container')
        self.assertIn(
            profile_name, str(main_content_soup),
            "{name} should be in the profile list".format(name=profile_name))

    def assertProfileNameNotOnList(self, visiting_user, profile_name):
        if visiting_user:
            self.client.force_login(visiting_user)
        else:
            self.client.logout()
        response = self.client.get(resolve_url('profile_list'))
        response_soup = BeautifulSoup(response.content, 'html.parser')
        main_content_soup = response_soup.find('div', id='content-container')
        self.assertNotIn(
            profile_name, str(main_content_soup),
            "{name} shouldn't be in the profile list".format(
                name=profile_name))

    def test_profile_list_access(self):
        """Everyone can access the profile list."""
        url = resolve_url('profile_list')
        template = 'profiles/profile_list.html'

        self.assertPermissionLevel(
            url, self.SIGNED_OUT, template=template)

    def test_profile_list_visibility_of_open_profile(self):
        """Everyone can see an open profile."""
        self.assertProfileNameOnList(None, self.user_open.username)
        self.assertProfileNameOnList(self.user, self.user_open.username)
        self.assertProfileNameOnList(self.user_open, self.user_open.username)
        self.assertProfileNameOnList(self.superuser, self.user_open.username)

    def test_profile_list_visibility_of_registered_only_profile(self):
        """Only registered users can see this profile."""
        self.assertProfileNameNotOnList(None, self.user_registered.username)
        self.assertProfileNameOnList(self.user, self.user_registered.username)
        self.assertProfileNameOnList(
            self.user_registered, self.user_registered.username)
        self.assertProfileNameOnList(
            self.superuser, self.user_registered.username)

    def test_profile_list_visibility_of_closed_profile(self):
        """Only superusers and the profile owner can see a closed profile."""
        self.assertProfileNameNotOnList(None, self.user_closed.username)
        self.assertProfileNameNotOnList(self.user, self.user_closed.username)
        self.assertProfileNameOnList(
            self.user_closed, self.user_closed.username)
        self.assertProfileNameOnList(self.superuser, self.user_closed.username)


class ProfileListItemCountsTest(ClientTest):

    @classmethod
    def setUpTestData(cls):
        # Call the parent's setup (while still using this class as cls)
        super().setUpTestData()

        cls.url = resolve_url('profile_list')

    def test_no_visible_profiles(self):
        """There's at least one profile, but zero are visible."""
        # Create one user just to make sure there's at least one profile.
        self.create_user()
        # Iterate over all profiles and make them all closed.
        for profile in Profile.objects.all():
            profile.privacy = 'closed'
            profile.save()

        # While logged out, visit the profiles page. All profiles are closed,
        # so none should be visible.
        self.client.logout()
        response = self.client.get(self.url)
        self.assertTemplateUsed(response, 'profiles/profile_list.html')
        self.assertContains(response, "No profiles to display.")

    def test_multiple_pages(self):
        # However many profiles there are currently, we'll add enough profiles
        # to get to <per_page> + 1.
        per_page = 50
        current_profile_count = Profile.objects.all().count()
        for _ in range(per_page + 1 - current_profile_count):
            self.create_user()

        # View the profile list as a superuser to ensure we see all profiles.
        self.client.force_login(self.superuser)

        response = self.client.get(self.url)
        response_soup = BeautifulSoup(response.content, 'html.parser')
        account_list_soup = response_soup.find('ul', id='account_list')
        self.assertEqual(
            len(account_list_soup.find_all('li')), 50,
            "Page 1 has 50 profiles")

        response = self.client.get(self.url + '?page=2')
        response_soup = BeautifulSoup(response.content, 'html.parser')
        account_list_soup = response_soup.find('ul', id='account_list')
        self.assertEqual(
            len(account_list_soup.find_all('li')), 1,
            "Page 2 has 1 profile")


class ProfileDetailPermissionTest(ProfilePermissionTest):

    def test_profile_detail_open_profile(self):
        """Everyone can see an open profile."""
        url = resolve_url('profile_detail', self.user_open.pk)
        self.assertPermissionGranted(url, None)
        self.assertPermissionGranted(url, self.user)
        self.assertPermissionGranted(url, self.user_open)
        self.assertPermissionGranted(url, self.superuser)

    def test_profile_detail_registered_profile(self):
        """Only registered users can see this profile."""
        url = resolve_url('profile_detail', self.user_registered.pk)
        self.assertPermissionDenied(
            url, None,
            deny_wording="You don't have permission to view this profile.")
        self.assertPermissionGranted(url, self.user)
        self.assertPermissionGranted(url, self.user_registered)
        self.assertPermissionGranted(url, self.superuser)

    def test_profile_detail_closed_profile(self):
        """Only superusers and the profile owner can see a closed profile."""
        url = resolve_url('profile_detail', self.user_closed.pk)
        self.assertPermissionDenied(
            url, None,
            deny_wording="You don't have permission to view this profile.")
        self.assertPermissionDenied(
            url, self.user,
            deny_wording="You don't have permission to view this profile.")
        self.assertPermissionGranted(url, self.user_closed)
        self.assertPermissionGranted(url, self.superuser)

    def test_profile_detail_edit_link(self):
        """Only the profile owner sees the edit link on the detail page.
        (The link just takes you to a URL like /profile/edit, which does not
        identify a particular user; it's ONLY for editing your own profile."""
        url = resolve_url('profile_detail', self.user_open.pk)

        self.client.logout()
        response = self.client.get(url)
        self.assertNotContains(response, "Edit your profile")

        self.client.force_login(self.user)
        response = self.client.get(url)
        self.assertNotContains(response, "Edit your profile")

        self.client.force_login(self.user_open)
        response = self.client.get(url)
        self.assertContains(response, "Edit your profile")

        self.client.force_login(self.superuser)
        response = self.client.get(url)
        self.assertNotContains(response, "Edit your profile")


class ProfileEditPermissionTest(BasePermissionTest):

    def test_profile_edit(self):
        url = reverse('profile_edit')
        template = 'profiles/profile_form.html'

        # The view only makes sense for registered users. It's for editing
        # your own profile.
        self.assertPermissionLevel(
            url, self.SIGNED_IN, template=template,
            deny_type=self.REQUIRE_LOGIN)

    def test_profile_edit_cancel(self):
        url = reverse('profile_edit_cancel')
        template = 'profiles/profile_detail.html'

        self.assertPermissionLevel(
            url, self.SIGNED_IN, template=template,
            deny_type=self.REQUIRE_LOGIN)


class ProfileEditTest(ClientTest):

    @classmethod
    def setUpTestData(cls):
        # Call the parent's setup (while still using this class as cls)
        super().setUpTestData()

        cls.url = resolve_url('profile_edit')

    def edit_submit(self, privacy='closed',
                    first_name="Alice", last_name="Baker",
                    affiliation="Testing Society",
                    website="https://www.testingsociety.org/",
                    location="Seoul, South Korea",
                    about_me="I'm a tester.\nI test things for a living.",
                    avatar_file='', use_email_gravatar=True):
        data = dict(
            privacy=privacy,
            first_name=first_name, last_name=last_name,
            affiliation=affiliation,
            website=website, location=location, about_me=about_me,
            avatar_file=avatar_file, use_email_gravatar=use_email_gravatar)
        response = self.client.post(self.url, data, follow=True)
        return response

    @staticmethod
    def user_email_hexdigest(user):
        return hashlib.md5(user.email.lower().encode()).hexdigest()

    def test_submit(self):
        user = self.create_user()
        self.client.force_login(user)
        response = self.edit_submit(
            avatar_file=self.sample_image_as_file('_.png'))
        self.assertTemplateUsed(response, 'profiles/profile_detail.html')

        user.refresh_from_db()
        user.profile.refresh_from_db()
        self.assertEqual(user.first_name, "Alice")
        self.assertEqual(user.last_name, "Baker")
        self.assertEqual(user.profile.affiliation, "Testing Society")
        self.assertEqual(
            user.profile.website, "https://www.testingsociety.org/")
        self.assertEqual(user.profile.location, "Seoul, South Korea")
        self.assertEqual(
            user.profile.about_me,
            "I'm a tester.\nI test things for a living.")
        self.assertNotEqual(user.profile.avatar_file.name, '')
        self.assertEqual(user.profile.use_email_gravatar, True)

    def test_cancel(self):
        user = self.create_user()
        self.client.force_login(user)
        response = self.client.get(
            resolve_url('profile_edit_cancel'), follow=True)
        # Should redirect to the profile detail page
        self.assertTemplateUsed(response, 'profiles/profile_detail.html')
        self.assertContains(response, "Edit cancelled.")

    def test_first_name_required(self):
        user = self.create_user()
        self.client.force_login(user)
        response = self.edit_submit(first_name="")
        self.assertTemplateUsed(response, 'profiles/profile_form.html')
        self.assertContains(response, "This field is required.")

    def test_last_name_required(self):
        user = self.create_user()
        self.client.force_login(user)
        response = self.edit_submit(last_name="")
        self.assertTemplateUsed(response, 'profiles/profile_form.html')
        self.assertContains(response, "This field is required.")

    def test_affiliation_required(self):
        user = self.create_user()
        self.client.force_login(user)
        response = self.edit_submit(affiliation="")
        self.assertTemplateUsed(response, 'profiles/profile_form.html')
        self.assertContains(response, "This field is required.")

    def test_website_optional(self):
        user = self.create_user()
        self.client.force_login(user)
        response = self.edit_submit(website="")
        self.assertTemplateUsed(response, 'profiles/profile_detail.html')
        user.profile.refresh_from_db()
        self.assertEqual(user.profile.website, "")

    def test_location_optional(self):
        user = self.create_user()
        self.client.force_login(user)
        response = self.edit_submit(location="")
        self.assertTemplateUsed(response, 'profiles/profile_detail.html')
        user.profile.refresh_from_db()
        self.assertEqual(user.profile.location, "")

    def test_about_me_optional(self):
        user = self.create_user()
        self.client.force_login(user)
        response = self.edit_submit(about_me="")
        self.assertTemplateUsed(response, 'profiles/profile_detail.html')
        user.profile.refresh_from_db()
        self.assertEqual(user.profile.about_me, "")

    def test_avatar_file_plus_use_email_gravatar_equals_email_gravatar(self):
        user = self.create_user()
        self.client.force_login(user)
        response = self.edit_submit(
            avatar_file=self.sample_image_as_file('_.png'),
            use_email_gravatar=True)

        self.assertTemplateUsed(response, 'profiles/profile_detail.html')
        self.assertContains(response, 'gravatar.com/avatar')
        self.assertContains(response, self.user_email_hexdigest(user))

        user.profile.refresh_from_db()
        self.assertNotEqual(user.profile.avatar_file.name, '')
        self.assertEqual(user.profile.use_email_gravatar, True)

    def test_avatar_file_plus_no_email_gravatar_equals_avatar_file(self):
        user = self.create_user()
        self.client.force_login(user)
        response = self.edit_submit(
            avatar_file=self.sample_image_as_file('_.png'),
            use_email_gravatar=False)

        self.assertTemplateUsed(response, 'profiles/profile_detail.html')
        self.assertNotContains(response, 'gravatar.com/avatar')
        self.assertNotContains(response, self.user_email_hexdigest(user))

        user.profile.refresh_from_db()
        self.assertNotEqual(user.profile.avatar_file.name, '')
        self.assertEqual(user.profile.use_email_gravatar, False)

    def test_no_file_plus_use_email_gravatar_equals_email_gravatar(self):
        user = self.create_user()
        self.client.force_login(user)
        response = self.edit_submit(
            avatar_file='',
            use_email_gravatar=True)

        self.assertTemplateUsed(response, 'profiles/profile_detail.html')
        self.assertContains(response, 'gravatar.com/avatar')
        self.assertContains(response, self.user_email_hexdigest(user))

        user.profile.refresh_from_db()
        self.assertEqual(user.profile.avatar_file.name, '')
        self.assertEqual(user.profile.use_email_gravatar, True)

    def test_no_file_plus_no_email_gravatar_equals_random_gravatar(self):
        user = self.create_user()
        self.client.force_login(user)
        response = self.edit_submit(
            avatar_file='',
            use_email_gravatar=False)

        self.assertTemplateUsed(response, 'profiles/profile_detail.html')
        self.assertContains(response, 'gravatar.com/avatar')
        self.assertNotContains(response, self.user_email_hexdigest(user))

        user.profile.refresh_from_db()
        self.assertEqual(user.profile.avatar_file.name, '')
        self.assertEqual(user.profile.use_email_gravatar, False)
