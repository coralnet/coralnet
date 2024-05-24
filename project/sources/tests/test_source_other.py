from django.urls import reverse

from lib.tests.utils import BasePermissionTest, ClientTest
from ..models import Source


class PermissionTest(BasePermissionTest):
    """
    Test permissions for source-related views other than source about and
    source list, which are tested in different classes. (Those views have
    specific redirect logic.)
    """
    def test_source_detail_box(self):
        url = reverse('source_detail_box', args=[self.source.pk])

        self.source_to_private()
        self.assertPermissionLevel(url, self.SIGNED_OUT, is_json=True)
        self.source_to_public()
        self.assertPermissionLevel(url, self.SIGNED_OUT, is_json=True)

    def test_source_main(self):
        url = reverse('source_main', args=[self.source.pk])
        template = 'sources/source_main.html'

        self.source_to_private()
        self.assertPermissionLevel(url, self.SOURCE_VIEW, template=template)
        self.source_to_public()
        self.assertPermissionLevel(url, self.SIGNED_OUT, template=template)


class SourceAboutTest(ClientTest):
    """
    Test the About Sources page.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user_with_sources = cls.create_user()
        cls.user_without_sources = cls.create_user()

        cls.private_source = cls.create_source(
            cls.user_with_sources,
            visibility=Source.VisibilityTypes.PRIVATE)
        cls.public_source = cls.create_source(
            cls.user_with_sources,
            visibility=Source.VisibilityTypes.PUBLIC)

    def test_load_page_anonymous(self):
        response = self.client.get(reverse('source_about'))
        self.assertTemplateUsed(response, 'sources/source_about.html')
        self.assertContains(
            response, "You need an account to work with Sources")
        # Source list should just have the public source
        self.assertContains(response, self.public_source.name)
        self.assertNotContains(response, self.private_source.name)

    def test_load_page_without_source_memberships(self):
        self.client.force_login(self.user_without_sources)
        response = self.client.get(reverse('source_about'))
        self.assertTemplateUsed(response, 'sources/source_about.html')
        self.assertContains(
            response, "You're not part of any Sources")
        # Source list should just have the public source
        self.assertContains(response, self.public_source.name)
        self.assertNotContains(response, self.private_source.name)

    def test_load_page_with_source_memberships(self):
        self.client.force_login(self.user_with_sources)
        response = self.client.get(reverse('source_about'))
        self.assertTemplateUsed(response, 'sources/source_about.html')
        self.assertContains(
            response, "See your Sources")
        # Source list should just have the public source
        self.assertContains(response, self.public_source.name)
        self.assertNotContains(response, self.private_source.name)


class SourceListTest(ClientTest):
    """
    Test the source list page (except the map).
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.admin = cls.create_user()

        # Create sources with names to ensure a certain source list order
        cls.private_source = cls.create_source(
            cls.admin, name="Source 1",
            visibility=Source.VisibilityTypes.PRIVATE)
        cls.public_source = cls.create_source(
            cls.admin, name="Source 2",
            visibility=Source.VisibilityTypes.PUBLIC)

    def test_anonymous(self):
        response = self.client.get(reverse('source_list'), follow=True)
        # Should redirect to source_about
        self.assertTemplateUsed(response, 'sources/source_about.html')

    def test_member_of_none(self):
        user = self.create_user()
        self.client.force_login(user)

        response = self.client.get(reverse('source_list'), follow=True)
        # Should redirect to source_about
        self.assertTemplateUsed(response, 'sources/source_about.html')

    def test_member_of_public(self):
        user = self.create_user()
        self.add_source_member(
            self.admin, self.public_source, user, Source.PermTypes.VIEW.code)
        self.client.force_login(user)

        response = self.client.get(reverse('source_list'))
        self.assertTemplateUsed(response, 'sources/source_list.html')
        self.assertListEqual(
            list(response.context['your_sources']),
            [dict(
                id=self.public_source.pk, name=self.public_source.name,
                your_role="View")]
        )
        self.assertListEqual(
            list(response.context['other_public_sources']),
            []
        )

    def test_member_of_private(self):
        user = self.create_user()
        self.add_source_member(
            self.admin, self.private_source, user, Source.PermTypes.VIEW.code)
        self.client.force_login(user)

        response = self.client.get(reverse('source_list'))
        self.assertTemplateUsed(response, 'sources/source_list.html')
        self.assertListEqual(
            list(response.context['your_sources']),
            [
                dict(
                    id=self.private_source.pk, name=self.private_source.name,
                    your_role="View"
                ),
            ]
        )
        self.assertListEqual(
            list(response.context['other_public_sources']),
            [self.public_source]
        )

    def test_member_of_public_and_private(self):
        user = self.create_user()
        self.add_source_member(
            self.admin, self.private_source, user, Source.PermTypes.EDIT.code)
        self.add_source_member(
            self.admin, self.public_source, user, Source.PermTypes.ADMIN.code)
        self.client.force_login(user)

        response = self.client.get(reverse('source_list'))
        self.assertTemplateUsed(response, 'sources/source_list.html')
        # Sources should be in name-alphabetical order
        self.assertListEqual(
            list(response.context['your_sources']),
            [
                dict(
                    id=self.private_source.pk, name=self.private_source.name,
                    your_role="Edit"
                ),
                dict(
                    id=self.public_source.pk, name=self.public_source.name,
                    your_role="Admin"
                ),
            ]
        )
        self.assertListEqual(
            list(response.context['other_public_sources']),
            []
        )


class SourceDetailBoxTest(ClientTest):
    """
    Test the map's source detail popup box.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()

    def test_private_source(self):
        source = self.create_source(
            self.user, visibility=Source.VisibilityTypes.PRIVATE,
            affiliation="My Affiliation",
            description="My Description",
        )
        for _ in range(3):
            self.upload_image(self.user, source)

        response = self.client.get(
            reverse('source_detail_box', args=[source.pk]))
        detail_html = response.json()['detailBoxHtml']

        self.assertIn(source.name, detail_html)
        self.assertNotIn(reverse('source_main', args=[source.pk]), detail_html)

        self.assertIn("My Affiliation", detail_html)
        self.assertIn("My Description", detail_html)
        self.assertIn("Number of images: 3", detail_html)
        self.assertNotIn('class="source-example-image"', detail_html)

    def test_public_source(self):
        source = self.create_source(
            self.user, visibility=Source.VisibilityTypes.PUBLIC,
            affiliation="My Affiliation",
            description="My Description",
        )
        for _ in range(3):
            self.upload_image(self.user, source)

        response = self.client.get(
            reverse('source_detail_box', args=[source.pk]))
        detail_html = response.json()['detailBoxHtml']

        self.assertIn(source.name, detail_html)
        self.assertIn(reverse('source_main', args=[source.pk]), detail_html)

        self.assertIn("My Affiliation", detail_html)
        self.assertIn("My Description", detail_html)
        self.assertIn("Number of images: 3", detail_html)
        self.assertIn('class="source-example-image"', detail_html)
