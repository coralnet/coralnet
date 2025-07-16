from django.core import mail
from django.urls import reverse

from lib.tests.utils import ClientTest


class BaseAccountsTest(ClientTest):

    @classmethod
    def setUpTestData(cls):
        # Call the parent's setup (while still using this class as cls)
        super().setUpTestData()

        cls.user = cls.create_user()

    def register(self, username='alice', email='alice123@example.com',
                 password1='GreatBarrier', password2='GreatBarrier',
                 first_name="Alice", last_name="Baker",
                 affiliation="Testing Society",
                 reason_for_registering="Trying labeling tools",
                 project_description="Labeling corals",
                 how_did_you_hear_about_us="Colleagues",
                 agree_to_privacy_policy=True,
                 username2=''):
        data = dict(
            username=username, email=email,
            password1=password1, password2=password2,
            first_name=first_name, last_name=last_name,
            affiliation=affiliation,
            reason_for_registering=reason_for_registering,
            project_description=project_description,
            how_did_you_hear_about_us=how_did_you_hear_about_us,
            agree_to_privacy_policy=agree_to_privacy_policy,
            username2=username2)
        response = self.client.post(
            reverse('django_registration_register'), data, follow=True)
        return response

    def register_and_get_activation_link(self):
        """Shortcut function for tests focusing on the activation step."""
        self.register()

        activation_email = mail.outbox[-1]
        # Activation link: should be the first link (first "word" with '://')
        # in the activation email.
        activation_link = None
        for word in activation_email.body.split():
            if '://' in word:
                activation_link = word
                break
        self.assertIsNotNone(activation_link)

        return activation_link

    def assert_sign_in_success(self, response, user):
        # We should be past the sign-in page now.
        self.assertTemplateNotUsed(response, 'registration/login.html')

        # Check that we're signed in as the expected user.
        # From http://stackoverflow.com/a/6013115
        self.assertIn('_auth_user_id', self.client.session)
        self.assertEqual(
            int(self.client.session['_auth_user_id']), user.pk)
