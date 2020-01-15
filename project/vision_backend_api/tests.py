from __future__ import unicode_literals
from abc import ABCMeta
import copy
import json
import six

from django.conf import settings
from django.core.cache import cache
from django.test import override_settings
from django.test.utils import patch_logger
from django.urls import reverse
from mock import patch
from rest_framework import status

from api_core.models import ApiJob, ApiJobUnit
from api_core.tests.utils import BaseAPIPermissionTest
from images.models import Source
from lib.tests.utils import ClientTest
from vision_backend.models import Classifier
from .tasks import deploy_extract_features, deploy_classify


@six.add_metaclass(ABCMeta)
class DeployBaseTest(ClientTest):

    longMessage = True

    def setUp(self):
        super(DeployBaseTest, self).setUp()

        # DRF implements throttling by tracking usage counts in the cache.
        # We don't want usages in one test to trigger throttling in another
        # test. So we clear the cache between tests.
        cache.clear()

    @classmethod
    def setUpTestData(cls):
        super(DeployBaseTest, cls).setUpTestData()

        # Don't want DRF throttling to be a factor during class setup, either.
        cache.clear()

        cls.user = cls.create_user(
            username='testuser', password='SamplePassword')
        cls.source = cls.create_source(
            cls.user, visibility=Source.VisibilityTypes.PUBLIC)
        cls.labels = cls.create_labels(cls.user, ['A'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, cls.labels)
        cls.classifier = cls.create_robot(cls.source)
        cls.deploy_url = reverse('api:deploy', args=[cls.classifier.pk])

        # Get a token
        response = cls.client.post(
            reverse('api:token_auth'),
            dict(
                username='testuser',
                password='SamplePassword',
            ),
        )
        token = response.json()['token']
        cls.token_headers = dict(
            HTTP_AUTHORIZATION='Token {token}'.format(token=token))


class DeployAccessTest(BaseAPIPermissionTest):

    def assertNotFound(self, url, token_headers):
        response = self.client.post(url, **token_headers)
        self.assertEqual(
            response.status_code, status.HTTP_404_NOT_FOUND,
            "Should get 404")
        detail = "This classifier doesn't exist or is not accessible"
        self.assertDictEqual(
            response.json(),
            dict(errors=[dict(detail=detail)]),
            "Response JSON should be as expected")

    def assertPermissionGranted(self, url, token_headers):
        response = self.client.post(url, **token_headers)
        self.assertNotEqual(
            response.status_code, status.HTTP_404_NOT_FOUND,
            "Should not get 404")
        self.assertNotEqual(
            response.status_code, status.HTTP_403_FORBIDDEN,
            "Should not get 403")

    def test_get_method_not_allowed(self):
        classifier = self.create_robot(self.public_source)
        url = reverse('api:deploy', args=[classifier.pk])

        response = self.client.get(url, **self.user_token_headers)
        self.assertEqual(
            response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED,
            "Should get 405")

    def test_nonexistent_classifier(self):
        # To secure an ID which corresponds to no classifier, we
        # delete a previously existing classifier.
        classifier = self.create_robot(self.public_source)
        url = reverse('api:deploy', args=[classifier.pk])
        classifier.delete()

        self.assertNotFound(url, self.user_token_headers)

    def test_private_source(self):
        classifier = self.create_robot(self.private_source)
        url = reverse('api:deploy', args=[classifier.pk])

        self.assertNeedsAuth(url)
        self.assertNotFound(url, self.user_outsider_token_headers)
        self.assertPermissionGranted(url, self.user_viewer_token_headers)
        self.assertPermissionGranted(url, self.user_editor_token_headers)
        self.assertPermissionGranted(url, self.user_admin_token_headers)

    def test_public_source(self):
        classifier = self.create_robot(self.public_source)
        url = reverse('api:deploy', args=[classifier.pk])

        self.assertNeedsAuth(url)
        self.assertPermissionGranted(url, self.user_outsider_token_headers)
        self.assertPermissionGranted(url, self.user_viewer_token_headers)
        self.assertPermissionGranted(url, self.user_editor_token_headers)
        self.assertPermissionGranted(url, self.user_admin_token_headers)

    # Alter throttle rates for the following test. Use deepcopy to avoid
    # altering the original setting, since it's a nested data structure.
    throttle_test_settings = copy.deepcopy(settings.REST_FRAMEWORK)
    throttle_test_settings['DEFAULT_THROTTLE_RATES']['sustained'] = '3/hour'

    @override_settings(REST_FRAMEWORK=throttle_test_settings)
    def test_throttling(self):
        classifier = self.create_robot(self.public_source)
        url = reverse('api:deploy', args=[classifier.pk])

        for _ in range(3):
            response = self.client.post(url, **self.user_token_headers)
            self.assertNotEqual(
                response.status_code, status.HTTP_429_TOO_MANY_REQUESTS,
                "1st-3rd requests should not be throttled")

        response = self.client.post(url, **self.user_token_headers)
        self.assertEqual(
            response.status_code, status.HTTP_429_TOO_MANY_REQUESTS,
            "4th request should be denied by throttling")


class DeployStatusAccessTest(BaseAPIPermissionTest):

    def assertNotFound(self, url, token_headers):
        response = self.client.get(url, **token_headers)
        self.assertEqual(
            response.status_code, status.HTTP_404_NOT_FOUND,
            "Should get 404")
        detail = "This deploy job doesn't exist or is not accessible"
        self.assertDictEqual(
            response.json(),
            dict(errors=[dict(detail=detail)]),
            "Response JSON should be as expected")

    def assertPermissionGranted(self, url, token_headers):
        response = self.client.get(url, **token_headers)
        self.assertNotEqual(
            response.status_code, status.HTTP_404_NOT_FOUND,
            "Should not get 404")
        self.assertNotEqual(
            response.status_code, status.HTTP_403_FORBIDDEN,
            "Should not get 403")

    def test_nonexistent_job(self):
        # To secure an ID which corresponds to no job, we
        # delete a previously existing job.
        job = ApiJob(type='deploy', user=self.user)
        job.save()
        url = reverse('api:deploy_status', args=[job.pk])
        job.delete()

        self.assertNotFound(url, self.user_token_headers)

    def test_needs_auth(self):
        job = ApiJob(type='deploy', user=self.user)
        job.save()
        url = reverse('api:deploy_status', args=[job.pk])
        self.assertNeedsAuth(url)

    def test_post_method_not_allowed(self):
        job = ApiJob(type='deploy', user=self.user)
        job.save()
        url = reverse('api:deploy_status', args=[job.pk])

        response = self.client.post(url, **self.user_token_headers)
        self.assertEqual(
            response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED,
            "Should get 405")

    def test_job_of_same_user(self):
        job = ApiJob(type='deploy', user=self.user)
        job.save()
        url = reverse('api:deploy_status', args=[job.pk])
        self.assertPermissionGranted(url, self.user_token_headers)

    def test_job_of_other_user(self):
        job = ApiJob(type='deploy', user=self.user)
        job.save()
        url = reverse('api:deploy_status', args=[job.pk])
        self.assertNotFound(url, self.user_admin_token_headers)

    throttle_test_settings = copy.deepcopy(settings.REST_FRAMEWORK)
    throttle_test_settings['DEFAULT_THROTTLE_RATES']['sustained'] = '3/hour'

    @override_settings(REST_FRAMEWORK=throttle_test_settings)
    def test_throttling(self):
        job = ApiJob(type='deploy', user=self.user)
        job.save()
        url = reverse('api:deploy_status', args=[job.pk])

        for _ in range(3):
            response = self.client.get(url, **self.user_token_headers)
            self.assertNotEqual(
                response.status_code, status.HTTP_429_TOO_MANY_REQUESTS,
                "1st-3rd requests should not be throttled")

        response = self.client.get(url, **self.user_token_headers)
        self.assertEqual(
            response.status_code, status.HTTP_429_TOO_MANY_REQUESTS,
            "4th request should be denied by throttling")


class DeployResultAccessTest(BaseAPIPermissionTest):

    def assertNotFound(self, url, token_headers):
        response = self.client.get(url, **token_headers)
        self.assertEqual(
            response.status_code, status.HTTP_404_NOT_FOUND,
            "Should get 404")
        detail = "This deploy job doesn't exist or is not accessible"
        self.assertDictEqual(
            response.json(),
            dict(errors=[dict(detail=detail)]),
            "Response JSON should be as expected")

    def assertPermissionGranted(self, url, token_headers):
        response = self.client.get(url, **token_headers)
        self.assertNotEqual(
            response.status_code, status.HTTP_404_NOT_FOUND,
            "Should not get 404")
        self.assertNotEqual(
            response.status_code, status.HTTP_403_FORBIDDEN,
            "Should not get 403")

    def test_nonexistent_job(self):
        # To secure an ID which corresponds to no job, we
        # delete a previously existing job.
        job = ApiJob(type='deploy', user=self.user)
        job.save()
        url = reverse('api:deploy_result', args=[job.pk])
        job.delete()

        self.assertNotFound(url, self.user_token_headers)

    def test_needs_auth(self):
        job = ApiJob(type='deploy', user=self.user)
        job.save()
        url = reverse('api:deploy_result', args=[job.pk])
        self.assertNeedsAuth(url)

    def test_post_method_not_allowed(self):
        job = ApiJob(type='deploy', user=self.user)
        job.save()
        url = reverse('api:deploy_result', args=[job.pk])

        response = self.client.post(url, **self.user_token_headers)
        self.assertEqual(
            response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED,
            "Should get 405")

    def test_job_of_same_user(self):
        job = ApiJob(type='deploy', user=self.user)
        job.save()
        url = reverse('api:deploy_result', args=[job.pk])
        self.assertPermissionGranted(url, self.user_token_headers)

    def test_job_of_other_user(self):
        job = ApiJob(type='deploy', user=self.user)
        job.save()
        url = reverse('api:deploy_result', args=[job.pk])
        self.assertNotFound(url, self.user_admin_token_headers)

    throttle_test_settings = copy.deepcopy(settings.REST_FRAMEWORK)
    throttle_test_settings['DEFAULT_THROTTLE_RATES']['sustained'] = '3/hour'

    @override_settings(REST_FRAMEWORK=throttle_test_settings)
    def test_throttling(self):
        job = ApiJob(type='deploy', user=self.user)
        job.save()
        url = reverse('api:deploy_result', args=[job.pk])

        for _ in range(3):
            response = self.client.get(url, **self.user_token_headers)
            self.assertNotEqual(
                response.status_code, status.HTTP_429_TOO_MANY_REQUESTS,
                "1st-3rd requests should not be throttled")

        response = self.client.get(url, **self.user_token_headers)
        self.assertEqual(
            response.status_code, status.HTTP_429_TOO_MANY_REQUESTS,
            "4th request should be denied by throttling")


class DeployImagesParamErrorTest(DeployBaseTest):

    def assert_expected_400_error(self, response, error_dict):
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST,
            "Should get 400")
        self.assertDictEqual(
            response.json(),
            dict(errors=[error_dict]),
            "Response JSON should be as expected")

    def test_no_images_param(self):
        response = self.client.post(self.deploy_url, **self.token_headers)

        self.assert_expected_400_error(
            response, dict(
                detail="This parameter is required.",
                source=dict(parameter='images')))

    def test_not_valid_json(self):
        data = dict(images='[abc')
        response = self.client.post(
            self.deploy_url, data, **self.token_headers)

        self.assert_expected_400_error(
            response, dict(
                detail="Could not parse as JSON.",
                source=dict(parameter='images')))

    def test_images_not_array(self):
        data = dict(images=json.dumps(dict()))
        response = self.client.post(
            self.deploy_url, data, **self.token_headers)

        self.assert_expected_400_error(
            response, dict(
                detail="Ensure this element is an array.",
                source=dict(pointer='/images')))

    def test_images_empty(self):
        data = dict(images=json.dumps([]))
        response = self.client.post(
            self.deploy_url, data, **self.token_headers)

        self.assert_expected_400_error(
            response, dict(
                detail="Ensure this array is non-empty.",
                source=dict(pointer='/images')))

    def test_too_many_images(self):
        data = dict(images=json.dumps([{}]*101))
        response = self.client.post(
            self.deploy_url, data, **self.token_headers)

        self.assert_expected_400_error(
            response, dict(
                detail="This array exceeds the max length of 100.",
                source=dict(pointer='/images')))

    def test_image_not_hash(self):
        data = dict(images=json.dumps(
            ['abc']
        ))
        response = self.client.post(
            self.deploy_url, data, **self.token_headers)

        self.assert_expected_400_error(
            response, dict(
                detail="Ensure this element is a hash.",
                source=dict(pointer='/images/0')))

    def test_image_missing_url(self):
        data = dict(images=json.dumps(
            [dict(points=[])]
        ))
        response = self.client.post(
            self.deploy_url, data, **self.token_headers)

        self.assert_expected_400_error(
            response, dict(
                detail="Ensure this hash has a 'url' key.",
                source=dict(pointer='/images/0')))

    def test_image_missing_points(self):
        data = dict(images=json.dumps(
            [dict(url='URL 1')]
        ))
        response = self.client.post(
            self.deploy_url, data, **self.token_headers)

        self.assert_expected_400_error(
            response, dict(
                detail="Ensure this hash has a 'points' key.",
                source=dict(pointer='/images/0')))

    def test_url_not_string(self):
        data = dict(images=json.dumps(
            [dict(url=[], points=[])]
        ))
        response = self.client.post(
            self.deploy_url, data, **self.token_headers)

        self.assert_expected_400_error(
            response, dict(
                detail="Ensure this element is a string.",
                source=dict(pointer='/images/0/url')))

    def test_points_not_array(self):
        data = dict(images=json.dumps(
            [dict(url='URL 1', points='abc')]
        ))
        response = self.client.post(
            self.deploy_url, data, **self.token_headers)

        self.assert_expected_400_error(
            response, dict(
                detail="Ensure this element is an array.",
                source=dict(pointer='/images/0/points')))

    def test_points_empty(self):
        data = dict(images=json.dumps(
            [dict(url='URL 1', points=[])]
        ))
        response = self.client.post(
            self.deploy_url, data, **self.token_headers)

        self.assert_expected_400_error(
            response, dict(
                detail="Ensure this array is non-empty.",
                source=dict(pointer='/images/0/points')))

    def test_too_many_points(self):
        data = dict(images=json.dumps(
            [dict(url='URL 1', points=[{}]*1001)]
        ))
        response = self.client.post(
            self.deploy_url, data, **self.token_headers)

        self.assert_expected_400_error(
            response, dict(
                detail="This array exceeds the max length of 1000.",
                source=dict(pointer='/images/0/points')))

    def test_point_not_hash(self):
        data = dict(images=json.dumps(
            [dict(url='URL 1', points=['abc'])]
        ))
        response = self.client.post(
            self.deploy_url, data, **self.token_headers)

        self.assert_expected_400_error(
            response, dict(
                detail="Ensure this element is a hash.",
                source=dict(pointer='/images/0/points/0')))

    def test_point_missing_row(self):
        data = dict(images=json.dumps(
            [dict(url='URL 1', points=[dict(column=10)])]
        ))
        response = self.client.post(
            self.deploy_url, data, **self.token_headers)

        self.assert_expected_400_error(
            response, dict(
                detail="Ensure this hash has a 'row' key.",
                source=dict(pointer='/images/0/points/0')))

    def test_point_missing_column(self):
        data = dict(images=json.dumps(
            [dict(url='URL 1', points=[dict(row=10)])]
        ))
        response = self.client.post(
            self.deploy_url, data, **self.token_headers)

        self.assert_expected_400_error(
            response, dict(
                detail="Ensure this hash has a 'column' key.",
                source=dict(pointer='/images/0/points/0')))

    def test_point_row_below_minimum(self):
        data = dict(images=json.dumps(
            [dict(url='URL 1', points=[dict(row=-1, column=0)])]
        ))
        response = self.client.post(
            self.deploy_url, data, **self.token_headers)

        self.assert_expected_400_error(
            response, dict(
                detail="This element's value is below the minimum of 0.",
                source=dict(pointer='/images/0/points/0/row')))

    def test_point_column_below_minimum(self):
        data = dict(images=json.dumps(
            [dict(url='URL 1', points=[dict(row=0, column=-1)])]
        ))
        response = self.client.post(
            self.deploy_url, data, **self.token_headers)

        self.assert_expected_400_error(
            response, dict(
                detail="This element's value is below the minimum of 0.",
                source=dict(pointer='/images/0/points/0/column')))

    def test_second_image_error(self):
        data = dict(images=json.dumps(
            [dict(url='URL 1', points=[dict(row=10, column=10)]), dict()]
        ))
        response = self.client.post(
            self.deploy_url, data, **self.token_headers)

        self.assert_expected_400_error(
            response, dict(
                detail="Ensure this hash has a 'url' key.",
                source=dict(pointer='/images/1')))

    def test_second_point_error(self):
        data = dict(images=json.dumps(
            [dict(url='URL 1', points=[dict(row=10, column=10), dict(row=10)])]
        ))
        response = self.client.post(
            self.deploy_url, data, **self.token_headers)

        self.assert_expected_400_error(
            response, dict(
                detail="Ensure this hash has a 'column' key.",
                source=dict(pointer='/images/0/points/1')))


# During tests, we use CELERY_ALWAYS_EAGER = True to run tasks synchronously,
# so that we don't have to wait for tasks to finish before checking their
# results. To test state before all tasks finish, we'll mock the task
# functions to disable or change their behavior.
#
# Note: We have to patch the run() method of the task rather than patching
# the task itself. Otherwise, the patched task may end up being
# patched / not patched in tests where it's not supposed to be.
# https://stackoverflow.com/a/29269211/
#
# Note: Yes, patching views.deploy_extract_features.run (views, not tasks) is
# correct if we want to affect usages of deploy_extract_features in the
# views module.
# https://docs.python.org/3/library/unittest.mock.html#where-to-patch


def noop(*args):
    pass


class SuccessTest(DeployBaseTest):
    """
    Test the deploy process's success case from start to finish.
    """

    def test_deploy_response(self):
        """Test the response of a valid deploy request."""
        data = dict(images=json.dumps(
            [dict(url='URL 1', points=[dict(row=10, column=10)])]
        ))
        response = self.client.post(
            self.deploy_url, data, **self.token_headers)

        self.assertEqual(
            response.status_code, status.HTTP_202_ACCEPTED,
            "Should get 202")

        deploy_job = ApiJob.objects.latest('pk')

        self.assertEqual(
            response.content, '',
            "Response content should be empty")

        self.assertEqual(
            response['Location'],
            reverse('api:deploy_status', args=[deploy_job.pk]),
            "Response should contain status endpoint URL")

    @patch('vision_backend_api.views.deploy_extract_features.run', noop)
    def test_pre_extract(self):
        """
        Test pre-extract-features state. To do this, we disable the
        extract-features task by patching it.
        """
        data = dict(images=json.dumps(
            [dict(url='URL 1', points=[dict(row=10, column=10)])]
        ))
        self.client.post(self.deploy_url, data, **self.token_headers)

        try:
            deploy_job = ApiJob.objects.latest('pk')
        except ApiJob.DoesNotExist:
            self.fail("Job should be created")

        self.assertEqual(
            deploy_job.type, 'deploy', "Job type should be correct")
        self.assertEqual(
            deploy_job.user.pk, self.user.pk,
            "Job user (requester) should be correct")

        try:
            # There should be just one job unit: extracting features for the
            # only image
            job_unit = ApiJobUnit.objects.latest('pk')
        except ApiJobUnit.DoesNotExist:
            self.fail("Job unit should be created")

        self.assertEqual(
            job_unit.job.pk, deploy_job.pk, "Unit job should be correct")
        self.assertEqual(
            job_unit.type, 'deploy_extract_features',
            "Unit type should be feature extraction")
        self.assertEqual(
            job_unit.status, ApiJobUnit.PENDING,
            "Unit status should be pending")
        self.assertDictEqual(
            job_unit.request_json,
            dict(
                classifier_id=self.classifier.pk,
                url='URL 1',
                points=[dict(row=10, column=10)],
                image_order=0),
            "Unit's request_json should be correct")

    @patch('vision_backend_api.tasks.deploy_classify.run', noop)
    def test_pre_classify(self):
        """
        Test state after extracting features, but before classifying.
        To do this, we disable the classify task by patching it.
        """
        data = dict(images=json.dumps(
            [dict(url='URL 1', points=[dict(row=10, column=10)])]
        ))
        self.client.post(self.deploy_url, data, **self.token_headers)

        deploy_job = ApiJob.objects.latest('pk')

        # There should be two job units: extracting features, and classify,
        # for the only image
        try:
            extract_unit = ApiJobUnit.objects.filter(
                type='deploy_extract_features').latest('pk')
        except ApiJobUnit.DoesNotExist:
            self.fail("Features job unit should be created")

        self.assertEqual(
            extract_unit.status, ApiJobUnit.SUCCESS,
            "Extract unit status should be success")

        try:
            classify_unit = ApiJobUnit.objects.filter(
                type='deploy_classify').latest('pk')
        except ApiJobUnit.DoesNotExist:
            self.fail("Classify job unit should be created")

        self.assertEqual(
            classify_unit.job.pk, deploy_job.pk,
            "Classify unit job should be correct")
        self.assertEqual(
            classify_unit.status, ApiJobUnit.PENDING,
            "Classify unit status should be pending")
        self.assertDictEqual(
            classify_unit.request_json,
            dict(
                classifier_id=self.classifier.pk,
                url='URL 1',
                points=[dict(row=10, column=10)],
                image_order=0,
                features_path=''),
            "Classify unit's request_json should be correct")

    def test_done(self):
        """
        Test state after both feature extract and classify are done. To do
        this, just don't replace anything and let the tasks run synchronously.
        """
        data = dict(images=json.dumps(
            [dict(url='URL 1', points=[dict(row=10, column=10)])]
        ))
        self.client.post(self.deploy_url, data, **self.token_headers)

        deploy_job = ApiJob.objects.latest('pk')

        try:
            features_unit = ApiJobUnit.objects.filter(
                type='deploy_extract_features', job=deploy_job).latest('pk')
        except ApiJobUnit.DoesNotExist:
            self.fail("Features job unit should be created")

        try:
            classify_unit = ApiJobUnit.objects.filter(
                type='deploy_classify', job=deploy_job).latest('pk')
        except ApiJobUnit.DoesNotExist:
            self.fail("Classify job unit should be created")

        self.assertEqual(
            features_unit.status, ApiJobUnit.SUCCESS,
            "Features unit should be done")
        self.assertEqual(
            classify_unit.status, ApiJobUnit.SUCCESS,
            "Classify unit should be done")

        classifications = [dict(
            label_id=self.labels[0].pk, label_name='A',
            default_code='A', score=1.0)]
        self.assertDictEqual(
            classify_unit.result_json,
            dict(
                url='URL 1',
                points=[dict(
                    row=10, column=10, classifications=classifications)]),
            "Classify unit's result_json should be as expected"
            " (labelset with 1 label makes the scores deterministic)")


class TaskErrorsTest(DeployBaseTest):
    """
    Test error cases of the deploy tasks.
    """
    def test_extract_features_nonexistent_job_unit(self):
        # Create and delete a unit to secure a nonexistent ID.
        job = ApiJob(type='', user=self.user)
        job.save()
        unit = ApiJobUnit(job=job, type='test', request_json=dict())
        unit.save()
        unit_id = ApiJobUnit.objects.get(type='test').pk
        unit.delete()

        # patch_logger is an undocumented Django test utility. It lets us check
        # logged messages.
        # https://stackoverflow.com/a/54055056
        with patch_logger('vision_backend_api.tasks', 'info') as log_messages:
            deploy_extract_features.delay(unit_id)

            error_message = \
                "Job unit of id {pk} does not exist.".format(pk=unit_id)

            self.assertIn(error_message, log_messages)

    def test_classify_nonexistent_job_unit(self):
        # Create and delete a unit to secure a nonexistent ID.
        job = ApiJob(type='', user=self.user)
        job.save()
        unit = ApiJobUnit(job=job, type='test', request_json=dict())
        unit.save()
        unit_id = ApiJobUnit.objects.get(type='test').pk
        unit.delete()

        with patch_logger('vision_backend_api.tasks', 'info') as log_messages:
            deploy_classify.delay(unit_id)

            error_message = \
                "Job unit of id {pk} does not exist.".format(pk=unit_id)

            self.assertIn(error_message, log_messages)

    @patch('vision_backend_api.views.deploy_extract_features.run', noop)
    def test_classify_classifier_deleted(self):
        data = dict(images=json.dumps(
            [dict(url='URL 1', points=[dict(row=10, column=10)])]
        ))

        # Since extract features is a no-op, this won't run extract features
        # or classify. It'll just create the extract features job unit.
        self.client.post(self.deploy_url, data, **self.token_headers)

        features_unit = ApiJobUnit.objects.filter(
            type='deploy_extract_features').latest('pk')

        # Manually create the classify job unit.
        classify_unit = ApiJobUnit(
            job=features_unit.job,
            type='deploy_classify',
            request_json=features_unit.request_json)
        classify_unit.save()

        # Delete the classifier.
        classifier_id = classify_unit.request_json['classifier_id']
        classifier = Classifier.objects.get(pk=classifier_id)
        classifier.delete()

        # Run the classify task.
        deploy_classify.delay(classify_unit.pk)

        classify_unit.refresh_from_db()

        self.assertEqual(
            classify_unit.status, ApiJobUnit.FAILURE,
            "Classify unit should have failed")
        message = "Classifier of id {pk} does not exist.".format(
            pk=classifier_id)
        self.assertDictEqual(
            classify_unit.result_json,
            dict(url='URL 1', errors=[message]))


class DeployStatusEndpointTest(DeployBaseTest):
    """
    Test the deploy status endpoint.
    """
    def setUp(self):
        self.data = dict(images=json.dumps([
            dict(url='URL 1', points=[
                dict(row=10, column=10),
                dict(row=20, column=5),
            ]),
            dict(url='URL 2', points=[
                dict(row=10, column=10),
            ]),
        ]))

    def deploy(self):
        self.client.post(self.deploy_url, self.data, **self.token_headers)

        job = ApiJob.objects.latest('pk')
        return job

    def get_job_status(self, job):
        status_url = reverse('api:deploy_status', args=[job.pk])
        response = self.client.get(status_url, **self.token_headers)
        return response

    @patch('vision_backend_api.views.deploy_extract_features.run', noop)
    def test_no_progress_yet(self):
        job = self.deploy()
        response = self.get_job_status(job)

        self.assertStatusOK(response)

        self.assertDictEqual(
            response.json(),
            dict(
                data=dict(
                    status="Pending",
                    classify_successes=0,
                    classify_failures=0,
                    total=2)),
            "Response JSON should be as expected")

    @patch('vision_backend_api.views.deploy_extract_features.run', noop)
    def test_some_images_working(self):
        job = self.deploy()

        # Mark one feature-extract unit's status as working
        features_job_unit = ApiJobUnit.objects.filter(
            job=job, type='deploy_extract_features').latest('pk')
        features_job_unit.status = ApiJobUnit.IN_PROGRESS
        features_job_unit.save()

        response = self.get_job_status(job)

        self.assertStatusOK(response)

        self.assertDictEqual(
            response.json(),
            dict(
                data=dict(
                    status="In Progress",
                    classify_successes=0,
                    classify_failures=0,
                    total=2)),
            "Response JSON should be as expected")

    @patch('vision_backend_api.tasks.deploy_classify.run', noop)
    def test_features_extracted(self):
        job = self.deploy()
        response = self.get_job_status(job)

        self.assertStatusOK(response)

        self.assertDictEqual(
            response.json(),
            dict(
                data=dict(
                    status="In Progress",
                    classify_successes=0,
                    classify_failures=0,
                    total=2)),
            "Response JSON should be as expected")

    @patch('vision_backend_api.tasks.deploy_classify.run', noop)
    def test_some_images_success(self):
        job = self.deploy()

        # Mark one classify unit's status as success
        classify_job_unit = ApiJobUnit.objects.filter(
            job=job, type='deploy_classify').latest('pk')
        classify_job_unit.status = ApiJobUnit.SUCCESS
        classify_job_unit.save()

        response = self.get_job_status(job)

        self.assertStatusOK(response)

        self.assertDictEqual(
            response.json(),
            dict(
                data=dict(
                    status="In Progress",
                    classify_successes=1,
                    classify_failures=0,
                    total=2)),
            "Response JSON should be as expected")

    @patch('vision_backend_api.tasks.deploy_classify.run', noop)
    def test_some_images_failure(self):
        job = self.deploy()

        # Mark one classify unit's status as failure
        classify_job_unit = ApiJobUnit.objects.filter(
            job=job, type='deploy_classify').latest('pk')
        classify_job_unit.status = ApiJobUnit.FAILURE
        classify_job_unit.save()

        response = self.get_job_status(job)

        self.assertStatusOK(response)

        self.assertDictEqual(
            response.json(),
            dict(
                data=dict(
                    status="In Progress",
                    classify_successes=0,
                    classify_failures=1,
                    total=2)),
            "Response JSON should be as expected")

    def test_success(self):
        job = self.deploy()
        response = self.get_job_status(job)

        self.assertEqual(
            response.status_code, status.HTTP_303_SEE_OTHER,
            "Should get 303")

        self.assertEqual(
            response.content, '',
            "Response content should be empty")

        self.assertEqual(
            response['Location'],
            reverse('api:deploy_result', args=[job.pk]),
            "Location header should be as expected")

    @patch('vision_backend_api.tasks.deploy_classify.run', noop)
    def test_failure(self):
        job = self.deploy()

        # Mark both classify units' status as done: one success, one failure.
        #
        # Note: We must bind the units to separate names, since assigning an
        # attribute using an index access (like units[0].status = 'SC')
        # doesn't seem to work as desired (the attribute doesn't change).
        unit_1, unit_2 = ApiJobUnit.objects.filter(
            job=job, type='deploy_classify')
        unit_1.status = ApiJobUnit.SUCCESS
        unit_1.save()
        unit_2.status = ApiJobUnit.FAILURE
        unit_2.save()

        response = self.get_job_status(job)

        self.assertEqual(
            response.status_code, status.HTTP_303_SEE_OTHER,
            "Should get 303")

        self.assertEqual(
            response.content, '',
            "Response content should be empty")

        self.assertEqual(
            response['Location'],
            reverse('api:deploy_result', args=[job.pk]),
            "Location header should be as expected")


class DeployResultEndpointTest(DeployBaseTest):
    """
    Test the deploy result endpoint.
    """
    def setUp(self):
        self.data = dict(images=json.dumps([
            dict(url='URL 1', points=[
                dict(row=10, column=10),
                dict(row=20, column=5),
            ]),
            dict(url='URL 2', points=[
                dict(row=10, column=10),
            ]),
        ]))

    def deploy(self):
        self.client.post(self.deploy_url, self.data, **self.token_headers)
        job = ApiJob.objects.latest('pk')
        return job

    def get_job_result(self, job):
        result_url = reverse('api:deploy_result', args=[job.pk])
        response = self.client.get(result_url, **self.token_headers)
        return response

    def assert_result_response_not_finished(self, response):
        self.assertEqual(
            response.status_code, status.HTTP_409_CONFLICT,
            "Should get 409")

        self.assertDictEqual(
            response.json(),
            dict(errors=[
                dict(detail="This job isn't finished yet")]),
            "Response JSON should be as expected")

    @patch('vision_backend_api.views.deploy_extract_features.run', noop)
    def test_no_progress_yet(self):
        job = self.deploy()
        response = self.get_job_result(job)

        self.assert_result_response_not_finished(response)

    @patch('vision_backend_api.views.deploy_extract_features.run', noop)
    def test_some_images_working(self):
        job = self.deploy()

        # Mark one feature-extract unit's status as working
        features_job_unit = ApiJobUnit.objects.filter(
            job=job, type='deploy_extract_features').latest('pk')
        features_job_unit.status = ApiJobUnit.IN_PROGRESS
        features_job_unit.save()

        response = self.get_job_result(job)

        self.assert_result_response_not_finished(response)

    @patch('vision_backend_api.tasks.deploy_classify.run', noop)
    def test_features_extracted(self):
        job = self.deploy()
        response = self.get_job_result(job)

        self.assert_result_response_not_finished(response)

    @patch('vision_backend_api.tasks.deploy_classify.run', noop)
    def test_some_images_success(self):
        job = self.deploy()

        # Mark one classify unit's status as success
        classify_job_unit = ApiJobUnit.objects.filter(
            job=job, type='deploy_classify').latest('pk')
        classify_job_unit.status = ApiJobUnit.SUCCESS
        classify_job_unit.save()

        response = self.get_job_result(job)

        self.assert_result_response_not_finished(response)

    @patch('vision_backend_api.tasks.deploy_classify.run', noop)
    def test_some_images_failure(self):
        job = self.deploy()

        # Mark one classify unit's status as failure
        classify_job_unit = ApiJobUnit.objects.filter(
            job=job, type='deploy_classify').latest('pk')
        classify_job_unit.status = ApiJobUnit.FAILURE
        classify_job_unit.save()

        response = self.get_job_result(job)

        self.assert_result_response_not_finished(response)

    def test_success(self):
        job = self.deploy()
        response = self.get_job_result(job)

        self.assertStatusOK(response)

        classifications = [dict(
            label_id=self.labels[0].pk, label_name='A',
            default_code='A', score=1.0)]
        points_1 = [
            dict(
                row=10, column=10,
                classifications=classifications,
            ),
            dict(
                row=20, column=5,
                classifications=classifications,
            ),
        ]
        points_2 = [dict(
            row=10, column=10,
            classifications=classifications,
        )]
        self.assertDictEqual(
            response.json(),
            dict(
                data=dict(
                    images=[
                        dict(url='URL 1', points=points_1),
                        dict(url='URL 2', points=points_2),
                    ])),
            "Response JSON should be as expected")

    @patch('vision_backend_api.tasks.deploy_classify.run', noop)
    def test_failure(self):
        job = self.deploy()

        # Mark both classify units' status as done: one success, one failure.
        unit_1, unit_2 = ApiJobUnit.objects.filter(
            job=job, type='deploy_classify').order_by('pk')

        unit_1.status = ApiJobUnit.SUCCESS
        classifications = [dict(
            label_id=self.labels[0].pk, label_name='A',
            default_code='A', score=1.0)]
        points_1 = [
            dict(
                row=10, column=10,
                classifications=classifications,
            ),
            dict(
                row=20, column=5,
                classifications=classifications,
            ),
        ]
        unit_1.result_json = dict(
            url='URL 1', points=points_1)
        unit_1.save()

        unit_2.status = ApiJobUnit.FAILURE
        url_2_errors = ["Classifier of id 33 does not exist."]
        unit_2.result_json = dict(
            url='URL 2', errors=url_2_errors)
        unit_2.save()

        response = self.get_job_result(job)

        self.assertStatusOK(response)

        self.assertDictEqual(
            response.json(),
            dict(
                data=dict(
                    images=[
                        dict(url='URL 1', points=points_1),
                        dict(url='URL 2', errors=url_2_errors),
                    ])),
            "Response JSON should be as expected")
