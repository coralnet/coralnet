import re

from bs4 import BeautifulSoup
from django.conf import settings
from django.contrib.flatpages.models import FlatPage
from django.contrib.sites.models import Site
from django.urls import reverse
from django_migration_testcase import MigrationTest
from reversion.models import Version

from lib.tests.utils import BasePermissionTest, ClientTest


class PermissionTest(BasePermissionTest):
    """
    Test permission to a flatpage.
    """
    def test_flatpage_help(self):
        url = reverse('pages:help')
        template = 'flatpages/default.html'

        self.assertPermissionLevel(url, self.SIGNED_OUT, template=template)


class FlatpagesTest(ClientTest):
    """
    Test flatpages in general.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

    def test_new_flatpage(self):
        """Create a flatpage and view it at its URL."""
        page = FlatPage(
            url='/help/faq/', title="FAQ", content="FAQ contents go here.")
        page.save()
        page.sites.add(Site.objects.get(pk=settings.SITE_ID))
        page.save()

        response = self.client.get('/pages/help/faq/')
        self.assertTemplateUsed(response, 'flatpages/default.html')

    def test_404(self):
        """URL is in the flatpages directory, but the page name doesn't exist.
        Should 404."""
        response = self.client.get('/pages/nonexistent-page/')
        self.assertTemplateUsed(response, '404.html')

    def test_markdown_to_html(self):
        """Markdown in the content field should be rendered as HTML when
        displaying the flatpage."""
        page = FlatPage(
            url='/help/faq/', title="FAQ",
            content="**FAQ contents** go *here.*")
        page.save()
        page.sites.add(Site.objects.get(pk=settings.SITE_ID))
        page.save()

        response = self.client.get('/pages/help/faq/')
        response_soup = BeautifulSoup(response.content, 'html.parser')
        container_soup = response_soup.find(
            'div', dict(id='content-container'))

        self.assertHTMLEqual(
            str(container_soup),
            '<div id="content-container">'
            '<div class="article-body">'
            '<p><strong>FAQ contents</strong> go <em>here.</em></p>'
            '</div>'
            '</div>')

    def test_versioning(self):
        """django-reversion should create versions of flatpages when saving
        via the admin interface."""
        self.client.force_login(self.superuser)
        data = dict(
            url='/help/faq/', title="FAQ", content="FAQ contents go here.",
            sites=str(settings.SITE_ID))
        self.client.post('/admin/flatpages/flatpage/add/', data, follow=True)

        version = Version.objects.get_for_model(FlatPage).latest('id')
        self.assertEqual(version.field_dict['title'], "FAQ", "Title matches")
        self.assertEqual(
            version.field_dict['content'], "FAQ contents go here.",
            "Content matches")

    def test_help_page(self):
        """Help flatpage should exist."""
        response = self.client.get(reverse('pages:help'))
        self.assertTemplateUsed(response, 'flatpages/default.html')


class FlatpageEditTest(ClientTest):
    """
    Test aspects of editing flatpages.
    """
    def test_flatpage_editor_has_markdownx_widget(self):
        self.client.force_login(self.superuser)
        response = self.client.get('/admin/flatpages/flatpage/add/')
        self.assertContains(
            response, 'class="markdownx-preview"',
            msg_prefix="markdownx preview element should be present")

    def test_markdownx_image_upload(self):
        """Simple check that the image upload view works."""
        data = dict(image=self.sample_image_as_file('sample.png'))
        response = self.client.post(
            reverse('markdownx_upload'), data,
            # The view's response type varies depending on what
            # request.is_ajax() returns. This ensures it returns True.
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        image_code = response.json()['image_code']

        image_code_regex = re.compile(
            # ![](
            r'!\[\]\('
            # One or more of anything except )
            r'([^)]+)'
            # )
            r'\)'
        )
        self.assertRegex(
            image_code, image_code_regex,
            "markdownx should return a valid image code")


class HardcodedFlatpagesMigrationTest(MigrationTest):

    before = [('flatpages', '0001_initial'), ('sites', '0001_initial')]
    after = [('flatpages_custom', '0001_add_help_page_if_not_present')]
    # app_name = 'flatpages_custom'
    # before = 'zero'
    # after = '0001'

    def test_migration_when_help_flatpage_already_exists(self):
        FlatPage = self.get_model_before('flatpages.FlatPage')
        Site = self.get_model_before('sites.Site')

        # This here is a little confusing - although flatpages_custom's
        # migration state should be zero, it's possible that 0001 was already
        # run and then rolled back so that we're back in the zero state.
        # However, 0001's reverse operation doesn't do anything, so in this
        # case we'd still have the effects of 0001: a help flatpage was already
        # created.
        # In any case, our goal before run_migration() is to ensure we have
        # a help page with a known content string.
        try:
            page = FlatPage.objects.get(url='/help/')
        except FlatPage.DoesNotExist:
            page = FlatPage(url='/help/')
        page.title = "Help"
        page.content = "Old help contents go here."
        page.save()
        page.sites.add(Site.objects.get(pk=settings.SITE_ID))
        page.save()

        old_flatpage_count = FlatPage.objects.all().count()
        self.run_migration()

        FlatPage = self.get_model_after('flatpages.FlatPage')
        self.assertEqual(
            FlatPage.objects.all().count(), old_flatpage_count,
            "No new FlatPage was created")
        page = FlatPage.objects.get(url='/help/')
        self.assertEqual(
            page.content, "Old help contents go here.",
            "Old FlatPage was not modified")
