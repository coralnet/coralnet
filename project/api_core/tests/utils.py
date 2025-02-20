import json

from django.test.client import Client
from django.urls import reverse
from rest_framework import status

from lib.tests.utils import ClientTest
from sources.models import Source


class APITestMixin:

    client: Client

    @classmethod
    def get_request_kwargs_for_user(cls, username, password):
        """
        Get request kwargs required for the given user to make API requests.
        These kwargs go in a test client's post() or get() methods.

        For the purposes of most tests that might use this, this
        should be called during the test class's setUpTestData(),
        so that it doesn't count toward DRF throttling during the test
        (we do a cache.clear(), which resets the throttle tracking, in the
        setUp() of every test, which runs after setUpTestData()).
        """
        response = cls.client.post(
            reverse('api:token_auth'),
            data=json.dumps(dict(username=username, password=password)),
            content_type='application/vnd.api+json',
        )
        token = response.json()['token']
        return dict(
            # Authorization header.
            HTTP_AUTHORIZATION='Token {token}'.format(token=token),
            # Content type. Particularly needed for POST requests,
            # but doesn't hurt for other requests either.
            content_type='application/vnd.api+json',
        )

    def assertForbiddenResponse(
            self, response,
            error_detail="Authentication credentials were not provided.",
            msg="Should get 403"):
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, msg)

        response_json = response.json()
        self.assertDictEqual(
            response_json,
            dict(errors=[dict(detail=error_detail)]),
            "Error response's body should be as expected")

    def assertMethodNotAllowedResponse(self, response, msg="Should get 405"):
        self.assertEqual(
            response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED, msg)

        response_json = response.json()
        self.assertIn(
            'errors', response_json,
            "Response should have top-level member 'errors'")
        error_detail = response_json['errors'][0]['detail']
        self.assertTrue(
            error_detail.startswith("Method ")
            and error_detail.endswith(" not allowed."),
            "Response error detail should be as expected")

    def assertThrottleResponse(
            self, response,
            detail_substring="Request was throttled. Expected available in",
            msg="Should get 429"):

        self.assertEqual(
            response.status_code, status.HTTP_429_TOO_MANY_REQUESTS, msg)

        response_json = response.json()
        self.assertIn(
            'errors', response_json,
            "Response should have top-level member 'errors'")
        self.assertIn(
            detail_substring, response_json['errors'][0]['detail'],
            "Response error detail should be as expected")


class BaseAPIPermissionTest(ClientTest, APITestMixin):
    """
    Test view permissions.

    To generalize this class to test any view, we might want to add some
    flexibility on what is created with each source (or just create the minimum
    and leave further customization to subclasses).
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user(username='user', password='SamplePass')
        cls.user_request_kwargs = cls.get_request_kwargs_for_user(
            'user', 'SamplePass')

        labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')

        cls.public_source = cls.create_source(
            cls.user, visibility=Source.VisibilityTypes.PUBLIC)
        cls.create_labelset(cls.user, cls.public_source, labels)

        cls.private_source = cls.create_source(
            cls.user, visibility=Source.VisibilityTypes.PRIVATE)
        cls.create_labelset(cls.user, cls.private_source, labels)

        # Not a source member
        cls.user_outsider = cls.create_user(
            username='user_outsider', password='SamplePass')
        cls.user_outsider_request_kwargs = cls.get_request_kwargs_for_user(
            'user_outsider', 'SamplePass')

        # View permissions
        cls.user_viewer = cls.create_user(
            username='user_viewer', password='SamplePass')
        cls.user_viewer_request_kwargs = cls.get_request_kwargs_for_user(
            'user_viewer', 'SamplePass')
        cls.add_source_member(
            cls.user, cls.public_source,
            cls.user_viewer, Source.PermTypes.VIEW.code)
        cls.add_source_member(
            cls.user, cls.private_source,
            cls.user_viewer, Source.PermTypes.VIEW.code)

        # Edit permissions
        cls.user_editor = cls.create_user(
            username='user_editor', password='SamplePass')
        cls.user_editor_request_kwargs = cls.get_request_kwargs_for_user(
            'user_editor', 'SamplePass')
        cls.add_source_member(
            cls.user, cls.public_source,
            cls.user_editor, Source.PermTypes.EDIT.code)
        cls.add_source_member(
            cls.user, cls.private_source,
            cls.user_editor, Source.PermTypes.EDIT.code)

        # Admin permissions
        cls.user_admin = cls.create_user(
            username='user_admin', password='SamplePass')
        cls.user_admin_request_kwargs = cls.get_request_kwargs_for_user(
            'user_admin', 'SamplePass')
        cls.add_source_member(
            cls.user, cls.public_source,
            cls.user_admin, Source.PermTypes.ADMIN.code)
        cls.add_source_member(
            cls.user, cls.private_source,
            cls.user_admin, Source.PermTypes.ADMIN.code)
