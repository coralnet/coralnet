from __future__ import unicode_literals
import copy
import json

from django.conf import settings
from django.test import override_settings
from django.test.utils import patch_logger
from django.urls import reverse
from mock import patch
from rest_framework import status
from unittest import skip

from api_core.models import ApiJob, ApiJobUnit
from api_core.tests.utils import BaseAPIPermissionTest
from vision_backend.models import Classifier
from vision_backend.tasks import deploy
from .utils import DeployBaseTest, noop_task


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

    @skip("Deprecated since deploy now a single call.")
    @patch('vision_backend_api.views.deploy.run', noop_task)
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

    @skip("Deprecated since deploy now a single call.")
    @patch('vision_backend_api.tasks.deploy.run', noop_task)
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

    @skip("We need to have a mock backend before we can test this.")
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
            deploy_unit = ApiJobUnit.objects.filter(
                type='deploy', job=deploy_job).latest('pk')
        except ApiJobUnit.DoesNotExist:
            self.fail("Deploy job unit should be created")

        self.assertEqual(deploy_unit.status, ApiJobUnit.SUCCESS,
            "Features unit should be done")

        classifications = [dict(
            label_id=self.labels[0].pk, label_name='A',
            default_code='A', score=1.0)]
        self.assertDictEqual(
            deploy_unit.result_json,
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
        with patch_logger('vision_backend.tasks', 'info') as log_messages:
            deploy.delay(unit_id)

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

        with patch_logger('vision_backend.tasks', 'info') as log_messages:
            deploy.delay(unit_id)

            error_message = \
                "Job unit of id {pk} does not exist.".format(pk=unit_id)

            self.assertIn(error_message, log_messages)

    @skip("Skip until we can run backend during tests.")
    @patch('vision_backend_api.views.deploy.run', noop_task)
    def test_classify_classifier_deleted(self):
        data = dict(images=json.dumps(
            [dict(url='URL 1', points=[dict(row=10, column=10)])]
        ))

        # Since extract features is a no-op, this won't run extract features
        # or classify. It'll just create the extract features job unit.
        self.client.post(self.deploy_url, data, **self.token_headers)

        features_unit = ApiJobUnit.objects.filter(
            type='deploy').latest('pk')

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
