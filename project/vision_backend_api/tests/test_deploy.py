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
from .utils import DeployBaseTest, mocked_load_image, noop_task


class DeployAccessTest(BaseAPIPermissionTest):

    def assertNeedsAuth(self, url):
        # Request with no token header
        response = self.client.post(url)
        self.assertForbiddenResponse(response)

    def assertNotFound(self, url, request_kwargs):
        response = self.client.post(url, **request_kwargs)
        self.assertEqual(
            response.status_code, status.HTTP_404_NOT_FOUND,
            "Should get 404")
        detail = "This classifier doesn't exist or is not accessible"
        self.assertDictEqual(
            response.json(),
            dict(errors=[dict(detail=detail)]),
            "Response JSON should be as expected")

    def assertPermissionGranted(self, url, request_kwargs):
        response = self.client.post(url, **request_kwargs)
        self.assertNotEqual(
            response.status_code, status.HTTP_404_NOT_FOUND,
            "Should not get 404")
        self.assertNotEqual(
            response.status_code, status.HTTP_403_FORBIDDEN,
            "Should not get 403")

    def test_get_method_not_allowed(self):
        classifier = self.create_robot(self.public_source)
        url = reverse('api:deploy', args=[classifier.pk])

        response = self.client.get(url, **self.user_request_kwargs)
        self.assertMethodNotAllowedResponse(response)

    def test_nonexistent_classifier(self):
        # To secure an ID which corresponds to no classifier, we
        # delete a previously existing classifier.
        classifier = self.create_robot(self.public_source)
        url = reverse('api:deploy', args=[classifier.pk])
        classifier.delete()

        self.assertNotFound(url, self.user_request_kwargs)

    def test_private_source(self):
        classifier = self.create_robot(self.private_source)
        url = reverse('api:deploy', args=[classifier.pk])

        self.assertNeedsAuth(url)
        self.assertNotFound(url, self.user_outsider_request_kwargs)
        self.assertPermissionGranted(url, self.user_viewer_request_kwargs)
        self.assertPermissionGranted(url, self.user_editor_request_kwargs)
        self.assertPermissionGranted(url, self.user_admin_request_kwargs)

    def test_public_source(self):
        classifier = self.create_robot(self.public_source)
        url = reverse('api:deploy', args=[classifier.pk])

        self.assertNeedsAuth(url)
        self.assertPermissionGranted(url, self.user_outsider_request_kwargs)
        self.assertPermissionGranted(url, self.user_viewer_request_kwargs)
        self.assertPermissionGranted(url, self.user_editor_request_kwargs)
        self.assertPermissionGranted(url, self.user_admin_request_kwargs)

    # Alter throttle rates for the following test. Use deepcopy to avoid
    # altering the original setting, since it's a nested data structure.
    throttle_test_settings = copy.deepcopy(settings.REST_FRAMEWORK)
    throttle_test_settings['DEFAULT_THROTTLE_RATES']['sustained'] = '3/hour'

    @override_settings(REST_FRAMEWORK=throttle_test_settings)
    def test_request_rate_throttling(self):
        classifier = self.create_robot(self.public_source)
        url = reverse('api:deploy', args=[classifier.pk])

        for _ in range(3):
            response = self.client.post(url, **self.user_request_kwargs)
            self.assertNotEqual(
                response.status_code, status.HTTP_429_TOO_MANY_REQUESTS,
                "1st-3rd requests should not be throttled")

        response = self.client.post(url, **self.user_request_kwargs)
        self.assertThrottleResponse(
            response, msg="4th request should be denied by throttling")

    @patch('vision_backend_api.views.deploy.run', noop_task)
    @override_settings(MAX_CONCURRENT_API_JOBS_PER_USER=3)
    def test_active_job_throttling(self):
        classifier = self.create_robot(self.public_source)
        url = reverse('api:deploy', args=[classifier.pk])

        images = [
            dict(type='image', attributes=dict(
                url='URL 1', points=[dict(row=10, column=10)]))]
        data = json.dumps(dict(data=images))

        # Submit 3 jobs
        for _ in range(3):
            response = self.client.post(url, data, **self.user_request_kwargs)
            self.assertNotEqual(
                response.status_code, status.HTTP_429_TOO_MANY_REQUESTS,
                "1st-3rd requests should not be throttled")

        job_ids = ApiJob.objects.filter(user=self.user).order_by('pk') \
            .values_list('pk', flat=True)

        # Submit another job with the other 3 still going
        response = self.client.post(url, data, **self.user_request_kwargs)
        detail = (
            "You already have 3 jobs active"
            + " (IDs: {id_0}, {id_1}, {id_2}).".format(
                id_0=job_ids[0], id_1=job_ids[1], id_2=job_ids[2])
            + " You must wait until one of them finishes"
            + " before requesting another job.")
        self.assertThrottleResponse(
            response, detail_substring=detail,
            msg="4th request should be denied by throttling")

        # Submit job as another user
        response = self.client.post(
            url, data, **self.user_viewer_request_kwargs)
        self.assertNotEqual(
            response.status_code, status.HTTP_429_TOO_MANY_REQUESTS,
            "Other users should not be throttled")

        # Finish one job, then submit another job
        job = ApiJob.objects.get(pk=job_ids[0])
        for unit in job.apijobunit_set.all():
            unit.status = ApiJobUnit.SUCCESS
            unit.save()

        response = self.client.post(
            url, data, **self.user_request_kwargs)
        self.assertNotEqual(
            response.status_code, status.HTTP_429_TOO_MANY_REQUESTS,
            "Shouldn't be denied now that one job has finished")


class DeployImagesParamErrorTest(DeployBaseTest):

    def assert_expected_400_error(self, response, error_dict):
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST,
            "Should get 400")
        self.assertDictEqual(
            response.json(),
            dict(errors=[error_dict]),
            "Response JSON should be as expected")

    def test_not_valid_json(self):
        data = '[abc'
        response = self.client.post(
            self.deploy_url, data, **self.request_kwargs)

        # Exact error string depends on Python 2 vs. 3 (json module's error
        # messages were updated), but we can at least check the start of it.
        self.assertEqual(
            response.status_code, status.HTTP_400_BAD_REQUEST,
            "Should get 400")
        error_detail = response.json()['errors'][0]['detail']
        self.assertTrue(error_detail.startswith("JSON parse error"))

    def test_not_a_hash(self):
        data = '[]'
        response = self.client.post(
            self.deploy_url, data, **self.request_kwargs)

        self.assert_expected_400_error(
            response, dict(
                detail="Ensure this element is a hash.",
                source=dict(pointer='/')))

    def test_empty_hash(self):
        data = '{}'
        response = self.client.post(
            self.deploy_url, data, **self.request_kwargs)

        self.assert_expected_400_error(
            response, dict(
                detail="Ensure this hash has a 'data' key.",
                source=dict(pointer='/')))

    def test_data_not_array(self):
        data = '{"data": "a string"}'
        response = self.client.post(
            self.deploy_url, data, **self.request_kwargs)

        self.assert_expected_400_error(
            response, dict(
                detail="Ensure this element is an array.",
                source=dict(pointer='/data')))

    def test_no_images(self):
        data = '{"data": []}'
        response = self.client.post(
            self.deploy_url, data, **self.request_kwargs)

        self.assert_expected_400_error(
            response, dict(
                detail="Ensure this array is non-empty.",
                source=dict(pointer='/data')))

    def test_too_many_images(self):
        # Array of many empty hashes
        images = [{}] * 101
        data = json.dumps(dict(data=images))
        response = self.client.post(
            self.deploy_url, data, **self.request_kwargs)

        self.assert_expected_400_error(
            response, dict(
                detail="This array exceeds the max length of 100.",
                source=dict(pointer='/data')))

    def test_image_not_hash(self):
        images = ['abc']
        data = json.dumps(dict(data=images))
        response = self.client.post(
            self.deploy_url, data, **self.request_kwargs)

        self.assert_expected_400_error(
            response, dict(
                detail="Ensure this element is a hash.",
                source=dict(pointer='/data/0')))

    def test_image_missing_type(self):
        images = [dict(attributes={})]
        data = json.dumps(dict(data=images))
        response = self.client.post(
            self.deploy_url, data, **self.request_kwargs)

        self.assert_expected_400_error(
            response, dict(
                detail="Ensure this hash has a 'type' key.",
                source=dict(pointer='/data/0')))

    def test_image_missing_attributes(self):
        images = [dict(type='image')]
        data = json.dumps(dict(data=images))
        response = self.client.post(
            self.deploy_url, data, **self.request_kwargs)

        self.assert_expected_400_error(
            response, dict(
                detail="Ensure this hash has a 'attributes' key.",
                source=dict(pointer='/data/0')))

    def test_image_type_incorrect(self):
        images = [dict(type='point', attributes={})]
        data = json.dumps(dict(data=images))
        response = self.client.post(
            self.deploy_url, data, **self.request_kwargs)

        self.assert_expected_400_error(
            response, dict(
                detail="This element should be equal to 'image'.",
                source=dict(pointer='/data/0/type')))

    def test_image_missing_url(self):
        images = [dict(type='image', attributes=dict(points=[]))]
        data = json.dumps(dict(data=images))
        response = self.client.post(
            self.deploy_url, data, **self.request_kwargs)

        self.assert_expected_400_error(
            response, dict(
                detail="Ensure this hash has a 'url' key.",
                source=dict(pointer='/data/0/attributes')))

    def test_image_missing_points(self):
        images = [dict(type='image', attributes=dict(url='URL 1'))]
        data = json.dumps(dict(data=images))
        response = self.client.post(
            self.deploy_url, data, **self.request_kwargs)

        self.assert_expected_400_error(
            response, dict(
                detail="Ensure this hash has a 'points' key.",
                source=dict(pointer='/data/0/attributes')))

    def test_url_not_string(self):
        images = [dict(type='image', attributes=dict(url=[], points=[]))]
        data = json.dumps(dict(data=images))
        response = self.client.post(
            self.deploy_url, data, **self.request_kwargs)

        self.assert_expected_400_error(
            response, dict(
                detail="Ensure this element is a string.",
                source=dict(pointer='/data/0/attributes/url')))

    def test_points_not_array(self):
        images = [
            dict(type='image', attributes=dict(url='URL 1', points='abc'))]
        data = json.dumps(dict(data=images))
        response = self.client.post(
            self.deploy_url, data, **self.request_kwargs)

        self.assert_expected_400_error(
            response, dict(
                detail="Ensure this element is an array.",
                source=dict(pointer='/data/0/attributes/points')))

    def test_points_empty(self):
        images = [
            dict(type='image', attributes=dict(url='URL 1', points=[]))]
        data = json.dumps(dict(data=images))
        response = self.client.post(
            self.deploy_url, data, **self.request_kwargs)

        self.assert_expected_400_error(
            response, dict(
                detail="Ensure this array is non-empty.",
                source=dict(pointer='/data/0/attributes/points')))

    def test_too_many_points(self):
        images = [
            dict(type='image', attributes=dict(url='URL 1', points=[{}]*201))]
        data = json.dumps(dict(data=images))
        response = self.client.post(
            self.deploy_url, data, **self.request_kwargs)

        self.assert_expected_400_error(
            response, dict(
                detail="This array exceeds the max length of 200.",
                source=dict(pointer='/data/0/attributes/points')))

    def test_point_not_hash(self):
        images = [
            dict(type='image', attributes=dict(url='URL 1', points=['abc']))]
        data = json.dumps(dict(data=images))
        response = self.client.post(
            self.deploy_url, data, **self.request_kwargs)

        self.assert_expected_400_error(
            response, dict(
                detail="Ensure this element is a hash.",
                source=dict(pointer='/data/0/attributes/points/0')))

    def test_point_missing_row(self):
        images = [
            dict(type='image', attributes=dict(
                url='URL 1', points=[dict(column=10)]))]
        data = json.dumps(dict(data=images))
        response = self.client.post(
            self.deploy_url, data, **self.request_kwargs)

        self.assert_expected_400_error(
            response, dict(
                detail="Ensure this hash has a 'row' key.",
                source=dict(pointer='/data/0/attributes/points/0')))

    def test_point_missing_column(self):
        images = [
            dict(type='image', attributes=dict(
                url='URL 1', points=[dict(row=10)]))]
        data = json.dumps(dict(data=images))
        response = self.client.post(
            self.deploy_url, data, **self.request_kwargs)

        self.assert_expected_400_error(
            response, dict(
                detail="Ensure this hash has a 'column' key.",
                source=dict(pointer='/data/0/attributes/points/0')))

    def test_point_row_below_minimum(self):
        images = [
            dict(type='image', attributes=dict(
                url='URL 1', points=[dict(row=-1, column=0)]))]
        data = json.dumps(dict(data=images))
        response = self.client.post(
            self.deploy_url, data, **self.request_kwargs)

        self.assert_expected_400_error(
            response, dict(
                detail="This element's value is below the minimum of 0.",
                source=dict(pointer='/data/0/attributes/points/0/row')))

    def test_point_column_below_minimum(self):
        images = [
            dict(type='image', attributes=dict(
                url='URL 1', points=[dict(row=0, column=-1)]))]
        data = json.dumps(dict(data=images))
        response = self.client.post(
            self.deploy_url, data, **self.request_kwargs)

        self.assert_expected_400_error(
            response, dict(
                detail="This element's value is below the minimum of 0.",
                source=dict(pointer='/data/0/attributes/points/0/column')))

    def test_second_image_error(self):
        images = [
            dict(type='image', attributes=dict(
                url='URL 1', points=[dict(row=10, column=10)])),
            dict(type='image', attributes=dict(points=[])),
        ]
        data = json.dumps(dict(data=images))
        response = self.client.post(
            self.deploy_url, data, **self.request_kwargs)

        self.assert_expected_400_error(
            response, dict(
                detail="Ensure this hash has a 'url' key.",
                source=dict(pointer='/data/1/attributes')))

    def test_second_point_error(self):
        images = [
            dict(type='image', attributes=dict(
                url='URL 1', points=[dict(row=10, column=10), dict(row=10)]))]
        data = json.dumps(dict(data=images))
        response = self.client.post(
            self.deploy_url, data, **self.request_kwargs)

        self.assert_expected_400_error(
            response, dict(
                detail="Ensure this hash has a 'column' key.",
                source=dict(pointer='/data/0/attributes/points/1')))


class SuccessTest(DeployBaseTest):
    """
    Test the deploy process's success case from start to finish.
    """

    def test_deploy_response(self):
        """Test the response of a valid deploy request."""
        images = [
            dict(type='image', attributes=dict(
                url='URL 1', points=[dict(row=10, column=10)]))]
        data = json.dumps(dict(data=images))
        response = self.client.post(
            self.deploy_url, data, **self.request_kwargs)

        self.assertEqual(
            response.status_code, status.HTTP_202_ACCEPTED,
            "Should get 202")

        deploy_job = ApiJob.objects.latest('pk')

        self.assertEqual(
            response.content.decode('utf-8'), '',
            "Response content should be empty")

        self.assertEqual(
            response['Location'],
            reverse('api:deploy_status', args=[deploy_job.pk]),
            "Response should contain status endpoint URL")

    @patch('vision_backend_api.views.deploy.run', noop_task)
    def test_pre_deploy(self):
        """
        Test pre-deploy state. To do this, we disable the task by patching it.
        """
        images = [
            dict(type='image', attributes=dict(
                url='URL 1', points=[dict(row=10, column=10)]))]
        data = json.dumps(dict(data=images))
        self.client.post(self.deploy_url, data, **self.request_kwargs)

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
            # There should be just one job unit: deploy for the only image
            job_unit = ApiJobUnit.objects.latest('pk')
        except ApiJobUnit.DoesNotExist:
            self.fail("Job unit should be created")

        self.assertEqual(
            job_unit.job.pk, deploy_job.pk, "Unit job should be correct")
        self.assertEqual(
            job_unit.type, 'deploy', "Unit type should be deploy")
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

    @patch('spacer.tasks.load_image', mocked_load_image)
    def test_done(self):
        """
        Test state after deploy is done. To do this, just don't replace
        anything and let the tasks run synchronously.
        """
        images = [
            dict(type='image', attributes=dict(
                url='URL 1', points=[dict(row=10, column=10)]))]
        data = json.dumps(dict(data=images))
        self.client.post(self.deploy_url, data, **self.request_kwargs)

        deploy_job = ApiJob.objects.latest('pk')

        try:
            deploy_unit = ApiJobUnit.objects.filter(
                type='deploy', job=deploy_job).latest('pk')
        except ApiJobUnit.DoesNotExist:
            self.fail("Deploy job unit should be created")

        self.assertEqual(
            ApiJobUnit.SUCCESS, deploy_unit.status,
            "Unit should be done")

        classifications = [dict(
            label_id=self.labels[0].pk, label_name='A',
            label_code='A_mycode', score=1.0)]
        self.assertDictEqual(
            deploy_unit.result_json,
            dict(
                url='URL 1',
                points=[dict(
                    row=10, column=10, classifications=classifications)]),
            "Unit's result_json should be as expected"
            " (labelset with 1 label makes the scores deterministic)")


class TaskErrorsTest(DeployBaseTest):
    """
    Test error cases of the deploy tasks.
    """

    def test_nonexistent_job_unit(self):
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

    @skip("Skip until we can run backend during tests.")
    @patch('vision_backend_api.views.deploy.run', noop_task)
    def test_classifier_deleted(self):
        images = [
            dict(type='image', attributes=dict(
                url='URL 1', points=[dict(row=10, column=10)]))]
        data = json.dumps(dict(data=images))

        # Since the task is a no-op, this'll just create the job unit.
        self.client.post(self.deploy_url, data, **self.request_kwargs)

        job_unit = ApiJobUnit.objects.filter(
            type='deploy').latest('pk')

        # Delete the classifier.
        classifier_id = job_unit.request_json['classifier_id']
        classifier = Classifier.objects.get(pk=classifier_id)
        classifier.delete()

        # Run the task.
        deploy.delay(job_unit.pk)

        job_unit.refresh_from_db()

        self.assertEqual(
            job_unit.status, ApiJobUnit.FAILURE,
            "Unit should have failed")
        message = "Classifier of id {pk} does not exist.".format(
            pk=classifier_id)
        self.assertDictEqual(
            job_unit.result_json,
            dict(url='URL 1', errors=[message]))
