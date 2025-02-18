import copy
import json

from django.conf import settings
from django.contrib.auth.models import User
from django.test import override_settings
from django.urls import reverse
from rest_framework import status

from lib.tests.utils import ClientTest
from vision_backend.tests.tasks.utils import do_collect_spacer_jobs
from vision_backend_api.tests.utils import DeployBaseTest
from ..models import ApiJob, UserApiLimits
from .utils import APITestMixin, BaseAPIPermissionTest


class BaseAPITest(ClientTest, APITestMixin):
    pass


class AuthTest(BaseAPITest):
    """
    Test API authentication.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user(
            username='testuser', password='SamplePassword')
        cls.source = cls.create_source(cls.user)
        cls.classifier = cls.create_robot(cls.source)

    def test_no_auth(self):
        # Don't log in or anything
        url = reverse('api:deploy', args=[self.classifier.pk])
        response = self.client.post(url)

        # Endpoints unrelated to getting API tokens should require auth
        self.assertForbiddenResponse(response)

    def test_session_auth(self):
        # Log in like we would for non-API requests
        self.client.force_login(self.user)

        url = reverse('api:deploy', args=[self.classifier.pk])
        response = self.client.post(url)
        self.assertNotEqual(
            response.status_code, status.HTTP_403_FORBIDDEN,
            "Session auth should work")

    def test_token_auth(self):
        # Get a token
        response = self.client.post(
            reverse('api:token_auth'),
            data='{"username": "testuser", "password": "SamplePassword"}',
            content_type='application/vnd.api+json',
        )
        token = response.json()['token']

        url = reverse('api:deploy', args=[self.classifier.pk])
        response = self.client.post(
            url, HTTP_AUTHORIZATION='Token {token}'.format(token=token))
        self.assertNotEqual(
            response.status_code, status.HTTP_403_FORBIDDEN,
            "Token auth should work")

    def test_token_response(self):
        response = self.client.post(
            reverse('api:token_auth'),
            data='{"username": "testuser", "password": "SamplePassword"}',
            content_type='application/vnd.api+json',
        )
        response_json = response.json()
        self.assertIn(
            'token', response_json, "Response should have a token member")
        self.assertEqual(
            len(response_json), 1,
            "Response should have no other top-level members")
        self.assertEqual(
            'application/vnd.api+json', response.get('content-type'),
            "Content type should be as expected")


class ContentTypeTest(BaseAPITest):
    """
    Test API content type checks.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user(
            username='testuser', password='SamplePassword')
        cls.source = cls.create_source(cls.user)
        cls.classifier = cls.create_robot(cls.source)

        # Get a token
        response = cls.client.post(
            reverse('api:token_auth'),
            data='{"username": "testuser", "password": "SamplePassword"}',
            content_type='application/vnd.api+json',
        )
        cls.token = response.json()['token']

    def test_token_auth_wrong_content_type(self):
        response = self.client.post(
            reverse('api:token_auth'),
            data='{"username": "testuser", "password": "SamplePassword"}',
            content_type='application/json',
        )

        self.assertEqual(
            response.status_code, status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Should get 415")
        detail = (
            "Content type should be application/vnd.api+json,"
            " not application/json")
        self.assertDictEqual(
            response.json(), dict(errors=[dict(detail=detail)]),
            "Response JSON should be as expected")

    def test_get_wrong_content_type(self):
        """
        Test content-type checking for GET requests.
        """
        job = ApiJob(type='test', user=self.user)
        job.save()
        status_url = reverse('api:deploy_status', args=[job.pk])
        response = self.client.get(
            status_url,
            HTTP_AUTHORIZATION='Token {token}'.format(token=self.token),
            content_type='multipart/form-data',
        )

        self.assertNotEqual(
            response.status_code, status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            msg="Should not be strict about content types for GET requests")

    def test_post_wrong_content_type(self):
        """
        Test content-type checking for POST requests (other than token auth).
        """
        deploy_url = reverse('api:deploy', args=[self.classifier.pk])
        response = self.client.post(
            deploy_url,
            HTTP_AUTHORIZATION='Token {token}'.format(token=self.token),
            content_type='multipart/form-data',
        )

        self.assertEqual(
            response.status_code, status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Should get 415")
        detail = (
            "Content type should be application/vnd.api+json,"
            " not multipart/form-data")
        self.assertDictEqual(
            response.json(), dict(errors=[dict(detail=detail)]),
            "Response JSON should be as expected")


class ThrottleTest(BaseAPITest):
    """
    Test API throttling.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user(
            username='testuser', password='SamplePassword')
        cls.user2 = cls.create_user(
            username='testuser2', password='SamplePassword')
        cls.source = cls.create_source(cls.user)
        cls.classifier = cls.create_robot(cls.source)

    def request_token(self, username='testuser'):
        response = self.client.post(
            reverse('api:token_auth'),
            data=json.dumps(
                dict(username=username, password='SamplePassword')),
            content_type='application/vnd.api+json',
        )
        return response

    # Alter throttle rates for the following test. Use deepcopy to avoid
    # altering the original setting, since it's a nested data structure.
    throttle_test_settings = copy.deepcopy(settings.REST_FRAMEWORK)
    throttle_test_settings['DEFAULT_THROTTLE_RATES']['burst'] = '3/min'
    throttle_test_settings['DEFAULT_THROTTLE_RATES']['sustained'] = '100/hour'

    @override_settings(REST_FRAMEWORK=throttle_test_settings)
    def test_burst_throttling(self):
        """Test that we get throttled if we hit the burst rate but not the
        sustained rate."""
        for _ in range(3):
            response = self.request_token()
            self.assertStatusOK(
                response, "1st-3rd requests should be permitted")

        response = self.request_token()
        self.assertThrottleResponse(
            response, msg="4th request should be denied by throttling")

    throttle_test_settings = copy.deepcopy(settings.REST_FRAMEWORK)
    throttle_test_settings['DEFAULT_THROTTLE_RATES']['burst'] = '100/min'
    throttle_test_settings['DEFAULT_THROTTLE_RATES']['sustained'] = '3/hour'

    @override_settings(REST_FRAMEWORK=throttle_test_settings)
    def test_sustained_throttling(self):
        """Test that we get throttled if we hit the sustained rate but not the
        burst rate."""
        for _ in range(3):
            response = self.request_token()
            self.assertStatusOK(
                response, "1st-3rd requests should be permitted")

        response = self.request_token()
        self.assertThrottleResponse(
            response, msg="4th request should be denied by throttling")

    throttle_test_settings = copy.deepcopy(settings.REST_FRAMEWORK)
    throttle_test_settings['DEFAULT_THROTTLE_RATES']['burst'] = '3/min'

    @override_settings(REST_FRAMEWORK=throttle_test_settings)
    def test_throttling_tracked_per_registered_user(self):
        response = self.request_token(username='testuser')
        token = response.json()['token']

        for _ in range(3):
            response = self.client.post(
                reverse('api:deploy', args=[self.classifier.pk]),
                HTTP_AUTHORIZATION='Token {token}'.format(token=token))
            self.assertNotEqual(
                response.status_code, status.HTTP_429_TOO_MANY_REQUESTS,
                "1st-3rd testuser requests should not be throttled")

        response = self.client.post(
            reverse('api:deploy', args=[self.classifier.pk]),
            HTTP_AUTHORIZATION='Token {token}'.format(token=token))
        self.assertThrottleResponse(
            response, msg="4th testuser request should be throttled")

        response = self.request_token(username='testuser2')
        token_2 = response.json()['token']

        for _ in range(3):
            response = self.client.post(
                reverse('api:deploy', args=[self.classifier.pk]),
                HTTP_AUTHORIZATION='Token {token}'.format(token=token_2))
            self.assertNotEqual(
                response.status_code, status.HTTP_429_TOO_MANY_REQUESTS,
                "testuser2 should not be affected by testuser's requests")

    throttle_test_settings = copy.deepcopy(settings.REST_FRAMEWORK)
    throttle_test_settings['DEFAULT_THROTTLE_RATES']['burst'] = '3/min'

    @override_settings(REST_FRAMEWORK=throttle_test_settings)
    def test_throttling_tracked_per_anonymous_ip(self):
        for _ in range(3):
            response = self.request_token()
            self.assertStatusOK(
                response, "1st-3rd anon-1 requests should be permitted")

        response = self.request_token()
        self.assertThrottleResponse(
            response, msg="4th anon-1 request should be denied by throttling")

        # When anonymous users are making API requests, DRF distinguishes
        # those users by IP address for rate limiting purposes. So we simulate
        # 'another user' by changing the REMOTE_ADDR.
        kwargs = dict(
            path=reverse('api:token_auth'),
            data='{"username": "testuser", "password": "SamplePassword"}',
            content_type='application/vnd.api+json',
            REMOTE_ADDR='1.2.3.4',
        )
        for _ in range(3):
            response = self.client.post(**kwargs)
            self.assertStatusOK(
                response,
                "Different anon IP should not be affected by the"
                " first anon IP's requests")


class UserShowAccessTest(BaseAPIPermissionTest):

    def assertNotFound(self, url, request_kwargs):
        response = self.client.get(url, **request_kwargs)
        self.assertEqual(
            response.status_code, status.HTTP_404_NOT_FOUND,
            "Should get 404")
        detail = "You can only see details for the user you're logged in as"
        self.assertDictEqual(
            response.json(),
            dict(errors=[dict(detail=detail)]),
            "Response JSON should be as expected")

    def assertPermissionGranted(self, url, request_kwargs):
        response = self.client.get(url, **request_kwargs)
        self.assertNotEqual(
            response.status_code, status.HTTP_404_NOT_FOUND,
            "Should not get 404")
        self.assertNotEqual(
            response.status_code, status.HTTP_403_FORBIDDEN,
            "Should not get 403")

    def test_nonexistent_user(self):
        # To secure an ID which corresponds to no user, we
        # delete a previously existing user.
        user = User(username='to_delete')
        user.save()
        url = reverse('api:user_show', args=['to_delete'])
        user.delete()

        self.assertNotFound(url, self.user_request_kwargs)

    def test_needs_auth(self):
        url = reverse('api:user_show', args=[self.user.username])
        response = self.client.get(url)
        self.assertForbiddenResponse(response)

    def test_post_method_not_allowed(self):
        url = reverse('api:user_show', args=[self.user.username])
        response = self.client.post(url, **self.user_request_kwargs)
        self.assertMethodNotAllowedResponse(response)

    def test_same_user(self):
        url = reverse('api:user_show', args=[self.user.username])
        self.assertPermissionGranted(url, self.user_request_kwargs)

    def test_other_user(self):
        url = reverse('api:user_show', args=[self.user.username])
        self.assertNotFound(url, self.user_admin_request_kwargs)


class UserShowContentTest(DeployBaseTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.other_user = cls.create_user(username='other', password='SamplePass')
        cls.other_user_request_kwargs = cls.get_request_kwargs_for_user(
            'other', 'SamplePass')
        cls.set_up_classifier(cls.user)

    def get_endpoint_content(self):
        url = reverse('api:user_show', args=[self.user.username])
        response = self.client.get(url, **self.request_kwargs)
        self.assertStatusOK(response)
        return response.json()

    def schedule_deploy(self):
        self.client.post(
            self.deploy_url, self.deploy_data, **self.request_kwargs)

        job = ApiJob.objects.latest('pk')
        return job

    def complete_api_jobs(self):
        self.run_scheduled_jobs_including_deploy()
        do_collect_spacer_jobs()

    def test_no_jobs(self):
        self.assertDictEqual(
            self.get_endpoint_content()['data'],
            dict(active_jobs=[], recently_completed_jobs=[]),
        )

    @override_settings(USER_DEFAULT_MAX_ACTIVE_API_JOBS=3)
    def test_active_jobs(self):
        job_ids = [
            self.schedule_deploy().pk,
            self.schedule_deploy().pk,
            self.schedule_deploy().pk,
        ]
        self.assertDictEqual(
            self.get_endpoint_content()['data'],
            dict(
                active_jobs=[
                    dict(id=str(job_ids[0]), type='jobs'),
                    dict(id=str(job_ids[1]), type='jobs'),
                    dict(id=str(job_ids[2]), type='jobs'),
                ],
                recently_completed_jobs=[],
            ),
        )

    @override_settings(USER_DEFAULT_MAX_ACTIVE_API_JOBS=3)
    def test_completed_jobs(self):
        jobs = []
        jobs.append(self.schedule_deploy())
        self.complete_api_jobs()
        jobs.append(self.schedule_deploy())
        self.complete_api_jobs()
        jobs.append(self.schedule_deploy())

        self.assertDictEqual(
            self.get_endpoint_content()['data'],
            dict(
                active_jobs=[
                    dict(id=str(jobs[2].pk), type='jobs'),
                ],
                recently_completed_jobs=[
                    dict(id=str(jobs[1].pk), type='jobs'),
                    dict(id=str(jobs[0].pk), type='jobs'),
                ],
            ),
        )

    @override_settings(USER_DEFAULT_MAX_ACTIVE_API_JOBS=3)
    def test_completed_jobs_over_max_shown(self):
        jobs = []
        for _ in range(8):
            jobs.append(self.schedule_deploy())
            # Running this after each added job, instead of once after
            # adding all jobs, ensures a consistent completion order.
            self.complete_api_jobs()

        # Only the most recent max-active*2 = 6
        self.assertDictEqual(
            self.get_endpoint_content()['data'],
            dict(
                active_jobs=[],
                recently_completed_jobs=[
                    dict(id=str(jobs[7].pk), type='jobs'),
                    dict(id=str(jobs[6].pk), type='jobs'),
                    dict(id=str(jobs[5].pk), type='jobs'),
                    dict(id=str(jobs[4].pk), type='jobs'),
                    dict(id=str(jobs[3].pk), type='jobs'),
                    dict(id=str(jobs[2].pk), type='jobs'),
                ],
            ),
        )

    @override_settings(USER_DEFAULT_MAX_ACTIVE_API_JOBS=3)
    def test_default_active_job_limit(self):
        self.assertDictEqual(
            self.get_endpoint_content()['meta'],
            dict(max_active_jobs=3),
        )

    @override_settings(USER_DEFAULT_MAX_ACTIVE_API_JOBS=3)
    def test_custom_active_job_limit(self):
        # Define limits for self.user as well as other users.
        user2 = self.create_user('user2')
        user3 = self.create_user('user3')
        UserApiLimits(user=user2, max_active_jobs=2).save()
        UserApiLimits(user=self.user, max_active_jobs=7).save()
        UserApiLimits(user=user3, max_active_jobs=20).save()

        self.assertDictEqual(
            self.get_endpoint_content()['meta'],
            dict(max_active_jobs=7),
        )


class UserShowQueriesTest(DeployBaseTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.set_up_classifier(cls.user)

    def get_endpoint_content(self):
        url = reverse('api:user_show', args=[self.user.username])
        response = self.client.get(url, **self.request_kwargs)
        self.assertStatusOK(response)
        return response.json()

    def schedule_deploy(self):
        self.client.post(
            self.deploy_url, self.deploy_data, **self.request_kwargs)

        job = ApiJob.objects.latest('pk')
        return job

    # 3 units per ApiJob
    deploy_data = json.dumps(dict(
        data=3*[
            dict(
                type='image',
                attributes=dict(
                    url='URL 1',
                    points=[
                        dict(row=10, column=10),
                        dict(row=20, column=5),
                    ]))
        ]
    ))

    def complete_api_jobs(self):
        self.run_scheduled_jobs_including_deploy()
        do_collect_spacer_jobs()

    @override_settings(USER_DEFAULT_MAX_ACTIVE_API_JOBS=5)
    def test_completed_jobs_over_max_shown(self):
        jobs = []
        for _ in range(4):
            for __ in range(5):
                jobs.append(self.schedule_deploy())
            self.complete_api_jobs()
        for _ in range(5):
            jobs.append(self.schedule_deploy())

        # 25 ApiJobs of 3 ApiJobUnits each.
        # user_show should run less than 1 query per ApiJob.
        with self.assert_queries_less_than(4*5 + 5):
            data = self.get_endpoint_content()['data']
        self.assertEqual(len(data['active_jobs']), 5)
        self.assertEqual(len(data['recently_completed_jobs']), 5*2)
