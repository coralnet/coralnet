# Lib tests and non-app-specific tests.
from email.utils import parseaddr
from unittest import skip, skipIf

from django.conf import settings
from django.core.files.storage import DefaultStorage
from django.core.mail import mail_admins
from django import forms
from django.shortcuts import resolve_url
from django.urls import reverse
from django.test.client import Client
from django.test.utils import override_settings

from ..forms import get_one_form_error, get_one_formset_error
from .utils import (
    BasePermissionTest,
    BaseTest,
    ClientTest,
    EmailAssertionsMixin,
    sample_image_as_file,
)


class PermissionTest(BasePermissionTest):
    """
    Test permission to misc. pages.
    """
    def test_index(self):
        url = reverse('index')

        # Index redirects if you're logged in.
        self.assertPermissionGranted(url, None, template='lib/index.html')
        self.assertPermissionGranted(
            url, self.user_outsider, template='images/source_about.html')
        self.assertPermissionGranted(
            url, self.superuser, template='images/source_list.html')

    def test_about(self):
        url = reverse('about')
        template = 'lib/about.html'

        self.assertPermissionLevel(url, self.SIGNED_OUT, template=template)

    def test_release(self):
        url = reverse('release')
        template = 'lib/release_notes.html'

        self.assertPermissionLevel(url, self.SIGNED_OUT, template=template)

    def test_admin_tools(self):
        url = reverse('admin_tools')
        template = 'lib/admin_tools.html'

        self.assertPermissionLevel(
            url, self.SUPERUSER, template=template,
            deny_type=self.REQUIRE_LOGIN)

    def test_nav_test(self):
        url = reverse('nav_test', args=[self.source.pk])
        template = 'lib/nav_test.html'

        self.assertPermissionLevel(
            url, self.SUPERUSER, template=template,
            deny_type=self.REQUIRE_LOGIN)

    def test_admin(self):
        """Only staff users can access the admin site."""
        url = reverse('admin:index')

        response = self.client.get(url, follow=True)
        self.assertTemplateUsed(response, 'admin/login.html')

        self.client.force_login(self.user_outsider)
        response = self.client.get(url, follow=True)
        self.assertTemplateUsed(response, 'admin/login.html')

        self.client.force_login(self.superuser)
        response = self.client.get(url, follow=True)
        self.assertTemplateUsed(response, 'admin/index.html')

    @skip("Not working on Travis yet. Might just need to install docutils.")
    def test_admin_doc(self):
        """Only staff users can access the admin docs."""
        url = reverse('django-admindocs-docroot')

        self.client.logout()
        response = self.client.get(url, follow=True)
        self.assertTemplateUsed(response, 'admin/login.html')

        self.client.force_login(self.user_outsider)
        response = self.client.get(url, follow=True)
        self.assertTemplateUsed(response, 'admin/login.html')

        self.client.force_login(self.superuser)
        response = self.client.get(url, follow=True)
        self.assertTemplateUsed(response, 'admin_doc/index.html')


class IndexTest(ClientTest):
    """
    Test the site index page.
    """
    def test_load_with_carousel(self):
        user = self.create_user()
        source = self.create_source(user)

        # Upload 4 images.
        for _ in range(4):
            self.upload_image(user, source)
        # Get the IDs of the uploaded images.
        uploaded_image_ids = list(source.image_set.values_list('pk', flat=True))

        # Override carousel settings.
        with self.settings(
                CAROUSEL_IMAGE_COUNT=3, CAROUSEL_IMAGE_POOL=uploaded_image_ids):
            response = self.client.get(reverse('index'))
            # Check for correct carousel image count.
            self.assertEqual(
                len(list(response.context['carousel_images'])), 3)


class GoogleAnalyticsTest(ClientTest):
    """
    Testing the google analytics java script plugin.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)
    
    @override_settings(GOOGLE_ANALYTICS_CODE = 'dummy-gacode')
    def test_simple(self):
        """
        Test that ga code is being generated. And that it contains the GOOGLE_ANALYTICS_CODE.
        """
        response = self.client.get(reverse('about'))
        self.assertEqual(response.status_code, 200)

        self.assertContains(response, 'google-analytics.com/ga.js')
        self.assertContains(response, settings.GOOGLE_ANALYTICS_CODE)

    @override_settings(GOOGLE_ANALYTICS_CODE = '')
    def test_missing(self):
        """
        Test what happens if the GOOGLE_ANALYTICS_CODE is not set
        """
        del settings.GOOGLE_ANALYTICS_CODE
        response = self.client.get(reverse('about'))
        self.assertContains(response, "Goggle Analytics not included because you haven't set the settings.GOOGLE_ANALYTICS_CODE variable!")

    @skipIf(settings.GOOGLE_ANALYTICS_CODE=='', reason='Without the code, we get the "havent set the code error"')
    @override_settings(DEBUG=True)
    def test_debug(self):
        """
        Do not include google analytics if in DEBUG mode.
        """
        response = self.client.get(reverse('about'))
        self.assertContains(response, 'Goggle Analytics not included because you are in Debug mode!')

    @skipIf(settings.GOOGLE_ANALYTICS_CODE == '', reason='Without the code, we get the "havent set the code error"')
    def test_staffuser(self):
        """
        Do not inlude google analytics if in superuser mode.
        """
        self.client.force_login(self.superuser)
        response = self.client.get(reverse('about'))
        self.assertContains(response, 'Goggle Analytics not included because you are a staff user!')

    @override_settings(GOOGLE_ANALYTICS_CODE = 'dummy-gacode')
    def test_in_source(self):
        """
        Make sure the ga plugin renders on a source page
        """
        self.client.force_login(self.user)
        response = self.client.get(resolve_url('browse_images', self.source.pk))
        self.assertContains(response, 'google-analytics.com/ga.js')


class FormUtilsTest(ClientTest):
    """
    Test the utility functions in forms.py.
    """
    class MyForm(forms.Form):
        my_field = forms.CharField(
            required=True,
            label="My Field",
            error_messages=dict(
                # Custom message for the 'field is required' error
                required="あいうえお",
            ),
        )
    MyFormSet = forms.formset_factory(MyForm)

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)

    def test_get_one_form_error_with_unicode(self):
        # Instantiate the form with no fields filled in (i.e. a blank dict in
        # place of request.POST), thus triggering a 'field is required' error
        my_form = self.MyForm(dict())
        self.assertFalse(my_form.is_valid())
        self.assertEqual(get_one_form_error(my_form), "My Field: あいうえお")

    def test_get_one_formset_error_with_unicode(self):
        # We need to at least pass in valid formset-management values so that
        # our actual form field can be validated
        my_formset = self.MyFormSet({
            'form-TOTAL_FORMS': 1,
            'form-INITIAL_FORMS': 1,
            'form-MAX_NUM_FORMS': '',
        })
        self.assertFalse(my_formset.is_valid())
        self.assertEqual(
            get_one_formset_error(
                formset=my_formset, get_form_name=lambda _: "My Form"),
            "My Form: My Field: あいうえお")


class InternationalizationTest(ClientTest):
    """
    Test internationalization in general.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)

    def setUp(self):
        # Set the web client's preferred language to Japanese.
        # We do this with an Accept-Language HTTP header value of 'ja'.
        # https://docs.djangoproject.com/en/dev/topics/testing/tools/#django.test.Client
        self.client = Client(HTTP_ACCEPT_LANGUAGE='ja')

    def test_builtin_form_error(self):
        """
        Test one of the Django built-in form errors, in this case 'This field
        is required.'
        Common errors like these should have translations
        available out of the box (these translations can be found at
        django/conf/locale). However, it's more confusing than useful when
        these are the only translated strings in the entire site, as is the
        case for us since we haven't had the resources for fuller translation.
        So, here we check that the message is NOT translated according to the
        client's preferred non-English language, i.e. it stays as English.
        """
        # Submit empty form fields on the Login page
        response = self.client.post(
            reverse('login'), dict(username='', password=''))
        required_error = response.context['form'].errors['username'][0]
        self.assertEqual(required_error, "This field is required.")


class TestSettingsStorageTest(BaseTest):
    """
    Test the file storage settings logic used during unit tests.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        storage = DefaultStorage()
        storage.save('1.png', sample_image_as_file('1.png'))
        storage.save('2.png', sample_image_as_file('2.png'))

    def test_storage_location_is_temporary(self):
        storage = DefaultStorage()

        # Should be using a temporary directory.
        self.assertTrue('tmp' in storage.location or 'temp' in storage.location)

    def test_add_file(self):
        storage = DefaultStorage()
        storage.save('3.png', sample_image_as_file('3.png'))

        # Files added from setUpTestData(), plus the file added just now,
        # should all be present.
        # And if test_delete_file() ran before this, that shouldn't affect
        # the result.
        self.assertTrue(storage.exists('1.png'))
        self.assertTrue(storage.exists('2.png'))
        self.assertTrue(storage.exists('3.png'))

    def test_delete_file(self):
        storage = DefaultStorage()
        storage.delete('1.png')

        # Files added from setUpTestData(), except the file deleted just now,
        # should be present.
        # And if test_add_file() ran before this, that shouldn't affect
        # the result.
        self.assertFalse(storage.exists('1.png'))
        self.assertTrue(storage.exists('2.png'))
        self.assertFalse(storage.exists('3.png'))


@override_settings(IMPORTED_USERNAME='class_override')
class TestSettingsDecoratorTest(BaseTest):
    """
    Test that we can successfully use settings decorators on test classes
    and test methods.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

    def test_class_override(self):
        # Class decorator should work.
        self.assertEqual(settings.IMPORTED_USERNAME, 'class_override')

    @override_settings(ROBOT_USERNAME='method_override_1')
    def test_method_override_1(self):
        # Class and method decorators should work.
        # Regardless of whether _1 or _2 runs first, both tests should not be
        # affected by the other test method's override.
        self.assertEqual(settings.IMPORTED_USERNAME, 'class_override')
        self.assertEqual(settings.ROBOT_USERNAME, 'method_override_1')
        self.assertNotEqual(settings.ALLEVIATE_USERNAME, 'method_override_2')

    @override_settings(ALLEVIATE_USERNAME='method_override_2')
    def test_method_override_2(self):
        # Class and method decorators should work.
        self.assertEqual(settings.IMPORTED_USERNAME, 'class_override')
        self.assertNotEqual(settings.ROBOT_USERNAME, 'method_override_1')
        self.assertEqual(settings.ALLEVIATE_USERNAME, 'method_override_2')

    @override_settings(IMPORTED_USERNAME='method_over_class_override')
    def test_method_over_class_override(self):
        # Method decorator should take precedence over class decorator.
        self.assertEqual(
            settings.IMPORTED_USERNAME, 'method_over_class_override')


class AdminsSettingTest(BaseTest, EmailAssertionsMixin):
    """
    Demonstrate the way settings.py sets the ADMINS setting.
    """
    def test(self):
        admins_setting = \
            'Alice <alice@example.org>,Jane Doe <jdoe@example.com>'
        admins = [
            parseaddr(addr.strip())
            for addr in admins_setting.split(',')
        ]

        self.assertListEqual(
            admins,
            [
                ('Alice', 'alice@example.org'),
                ('Jane Doe', 'jdoe@example.com'),
            ],
        )

        with override_settings(ADMINS=admins):
            mail_admins("Test subject", "Test body")
        self.assert_latest_email(
            "Test subject",
            ["Test body"],
            to=['alice@example.org', 'jdoe@example.com'],
        )
