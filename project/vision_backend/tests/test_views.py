from django.urls import reverse

from lib.tests.utils import ClientTest

from images.models import Source

class MainPageViewPermissions(ClientTest):
    """
    Test the annotation area edit page.
    """
    @classmethod
    def setUpTestData(cls):
        super(MainPageViewPermissions, cls).setUpTestData()

        cls.user = cls.create_user()

        cls.source = cls.create_source(
            cls.user, visibility=Source.VisibilityTypes.PRIVATE)

        cls.user_outsider = cls.create_user()
        
        cls.user_viewer = cls.create_user()
        cls.add_source_member(
            cls.user, cls.source, cls.user_viewer, Source.PermTypes.VIEW.code)
        
        cls.user_editor = cls.create_user()
        cls.add_source_member(
            cls.user, cls.source, cls.user_editor, Source.PermTypes.EDIT.code)

        cls.url = reverse('backend_main', args=[cls.source.pk])

    def test_load_page_anonymous(self):
        """
        Load the page while logged out ->
        sorry, don't have permission.
        """
        response = self.client.get(self.url)
        self.assertStatusOK(response)
        self.assertTemplateUsed(response, self.PERMISSION_DENIED_TEMPLATE)

    def test_load_page_as_source_outsider(self):
        """
        Load the page as a user outside the source ->
        sorry, don't have permission.
        """
        self.client.force_login(self.user_outsider)
        response = self.client.get(self.url)
        self.assertStatusOK(response)
        self.assertTemplateUsed(response, self.PERMISSION_DENIED_TEMPLATE)

    def test_load_page_as_source_viewer(self):
        """
        Load the page as a source viewer ->
        sorry, don't have permission.
        """
        self.client.force_login(self.user_viewer)
        response = self.client.get(self.url)
        self.assertStatusOK(response)
        self.assertTemplateUsed(
            response, 'vision_backend/backend_main.html')

    def test_load_page_as_source_editor(self):
        """
        Load the page as a source viewer ->
        sorry, don't have permission.
        """
        self.client.force_login(self.user_viewer)
        response = self.client.get(self.url)
        self.assertStatusOK(response)
        self.assertTemplateUsed(
            response, 'vision_backend/backend_main.html')
