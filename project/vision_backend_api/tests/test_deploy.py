import copy
import json
import operator
from unittest import mock

from django.conf import settings
from django.http import UnreadablePostError
from django.test import override_settings
from django.urls import reverse
from PIL import UnidentifiedImageError
from rest_framework import status
from rest_framework.exceptions import ParseError
from rest_framework.request import Request
from spacer.exceptions import (
    DataLimitError, RowColumnInvalidError, URLDownloadError)

from api_core.models import ApiJob, ApiJobUnit, UserApiLimits
from api_core.tests.utils import BaseAPIPermissionTest
from errorlogs.tests.utils import ErrorReportTestMixin
from jobs.models import Job
from jobs.tasks import run_scheduled_jobs
from jobs.tests.utils import JobUtilsMixin
from jobs.utils import start_job
from lib.tests.utils import EmailAssertionsMixin
from sources.models import Source
from vision_backend.models import Classifier
from .utils import DeployBaseTest


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


class DeployThrottleTest(DeployBaseTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.set_up_classifier(cls.user)

        # Second user
        cls.user_viewer = cls.create_user(
            username='user_viewer', password='SamplePass')
        cls.user_viewer_request_kwargs = cls.get_request_kwargs_for_user(
            'user_viewer', 'SamplePass')
        cls.add_source_member(
            cls.user, cls.source,
            cls.user_viewer, Source.PermTypes.VIEW.code)

    def submit_deploy(self):
        return self.client.post(
            self.deploy_url, self.deploy_data, **self.request_kwargs)

    # Alter throttle rates for the following test. Use deepcopy to avoid
    # altering the original setting, since it's a nested data structure.
    throttle_test_settings = copy.deepcopy(settings.REST_FRAMEWORK)
    throttle_test_settings['DEFAULT_THROTTLE_RATES']['sustained'] = '3/hour'

    @override_settings(REST_FRAMEWORK=throttle_test_settings)
    def test_request_rate_throttling(self):
        for _ in range(3):
            response = self.submit_deploy()
            self.assertNotEqual(
                response.status_code, status.HTTP_429_TOO_MANY_REQUESTS,
                "1st-3rd requests should not be throttled")

        response = self.submit_deploy()
        self.assertThrottleResponse(
            response, msg="4th request should be denied by throttling")

    @override_settings(USER_DEFAULT_MAX_ACTIVE_API_JOBS=3)
    def test_active_job_throttling_default(self):
        # Submit 3 jobs
        for _ in range(3):
            response = self.submit_deploy()
            self.assertNotEqual(
                response.status_code, status.HTTP_429_TOO_MANY_REQUESTS,
                "1st-3rd requests should not be throttled")

        job_ids = ApiJob.objects.filter(user=self.user).order_by('pk') \
            .values_list('pk', flat=True)

        # Submit another job with the other 3 still going
        response = self.submit_deploy()
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
            self.deploy_url, self.deploy_data,
            **self.user_viewer_request_kwargs)
        self.assertNotEqual(
            response.status_code, status.HTTP_429_TOO_MANY_REQUESTS,
            "Other users should not be throttled")

        # Finish one of the original user's jobs
        job = ApiJob.objects.get(pk=job_ids[0])
        self.run_deploy_api_job(job)
        self.do_collect_spacer_jobs()

        # Try submitting again as the original user
        response = self.submit_deploy()
        self.assertNotEqual(
            response.status_code, status.HTTP_429_TOO_MANY_REQUESTS,
            "Shouldn't be denied now that one job has finished")

    @override_settings(USER_DEFAULT_MAX_ACTIVE_API_JOBS=3)
    def test_active_job_throttling_user_specific(self):
        # Set user specific limit of 4
        limits = UserApiLimits(user=self.user, max_active_jobs=4)
        limits.save()

        # Submit 4 jobs
        for _ in range(4):
            response = self.submit_deploy()
            self.assertNotEqual(
                response.status_code, status.HTTP_429_TOO_MANY_REQUESTS,
                "1st-4th requests should not be throttled")

        job_ids = ApiJob.objects.filter(user=self.user).order_by('pk') \
            .values_list('pk', flat=True)

        # Submit another job with the other 4 still going
        response = self.submit_deploy()
        detail = (
            "You already have 4 jobs active"
            + " (IDs: {}, {}, {}, {}).".format(*job_ids)
            + " You must wait until one of them finishes"
            + " before requesting another job.")
        self.assertThrottleResponse(
            response, detail_substring=detail,
            msg="5th request should be denied by throttling")


class DeployImagesParamErrorTest(DeployBaseTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.set_up_classifier(cls.user)

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


class RequestDataErrorTest(DeployBaseTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.set_up_classifier(cls.user)

    def test_parse_error(self):
        def raise_parse_error(self, *args, **kwargs):
            raise ParseError("Some ParseError")

        images = [
            dict(type='image', attributes=dict(
                url='URL 1', points=[dict(row=10, column=10)]))]
        data = json.dumps(dict(data=images))

        # Make the `data` property of the request raise an error.
        # Not sure how to mock a property though, so let's mock
        # something that the property calls, instead.
        with mock.patch.object(
            Request, '_load_data_and_files', raise_parse_error
        ):
            response = self.client.post(
                self.deploy_url, data, **self.request_kwargs)

        self.assert_expected_400_error(
            response, dict(detail="Some ParseError"))

    def test_unreadable_post_error(self):
        def raise_unreadable_post_error(self, *args, **kwargs):
            raise UnreadablePostError("Some UnreadablePostError")

        images = [
            dict(type='image', attributes=dict(
                url='URL 1', points=[dict(row=10, column=10)]))]
        data = json.dumps(dict(data=images))

        with mock.patch.object(
            Request, '_load_data_and_files', raise_unreadable_post_error
        ):
            response = self.client.post(
                self.deploy_url, data, **self.request_kwargs)

        self.assert_expected_400_error(
            response, dict(detail="Some UnreadablePostError"))


class SuccessTest(DeployBaseTest):
    """
    Test the deploy process's success case from start to finish.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.set_up_classifier(cls.user)

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
            response.content.decode(), '',
            "Response content should be empty")

        self.assertEqual(
            response['Location'],
            reverse('api:deploy_status', args=[deploy_job.pk]),
            "Response should contain status endpoint URL")

    def test_pre_deploy(self):
        """
        Test pre-deploy state.
        """
        images = [
            dict(type='image', attributes=dict(
                url='URL 1',
                points=[dict(row=10, column=10), dict(row=40, column=20)]))]
        data = json.dumps(dict(data=images))
        # This should schedule a deploy job without running it yet.
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
            job_unit.parent.pk, deploy_job.pk, "Unit parent should be correct")
        self.assertEqual(
            job_unit.order_in_parent, 1, "Unit order should be correct")
        self.assertEqual(
            job_unit.status, Job.Status.PENDING,
            "Unit status should be pending")
        self.assertDictEqual(
            job_unit.request_json,
            dict(
                classifier_id=self.classifier.pk,
                url='URL 1',
                points=[dict(row=10, column=10), dict(row=40, column=20)],
            ),
            "Unit's request_json should be correct")
        self.assertEqual(
            job_unit.size, 2,
            "Unit's size should equal the point count")

    def test_done(self):
        """
        Test state after deploy is done.
        """
        images = [
            dict(type='image', attributes=dict(
                url='URL 1', points=[dict(row=10, column=10)]))]
        data = json.dumps(dict(data=images))

        # Schedule deploy
        self.client.post(self.deploy_url, data, **self.request_kwargs)
        # Deploy
        self.run_scheduled_jobs_including_deploy()
        self.do_collect_spacer_jobs()

        deploy_job = ApiJob.objects.latest('pk')

        try:
            deploy_unit = ApiJobUnit.objects.filter(
                parent=deploy_job).latest('pk')
        except ApiJobUnit.DoesNotExist:
            self.fail("Deploy job unit should be created")

        self.assertEqual(
            Job.Status.SUCCESS, deploy_unit.status,
            "Unit should be done")

        # Verify result. The classifications can vary, so we can't just verify
        # in a single assertion.

        expected_json_without_classifications = dict(
            url='URL 1',
            points=[dict(row=10, column=10)],
        )
        actual_classifications = \
            deploy_unit.result_json['points'][0].pop('classifications')
        actual_json_without_classifications = deploy_unit.result_json

        self.assertDictEqual(
            expected_json_without_classifications,
            actual_json_without_classifications,
            "Result JSON besides classifications should be as expected")

        # The following is an example of what the classifications may
        # look like, but the label order or scores may vary.
        # [
        #     dict(
        #         label_id=self.labels_by_name['B'].pk, label_name='B',
        #         label_code='B_mycode', score=0.5),
        #     dict(
        #         label_id=self.labels_by_name['A'].pk, label_name='A',
        #         label_code='A_mycode', score=0.5),
        # ]

        scores = [
            label_dict.pop('score') for label_dict in actual_classifications]
        self.assertAlmostEqual(
            1.0, sum(scores), places=3,
            msg="Scores for each point should add up to 1")
        self.assertGreaterEqual(
            scores[0], scores[1], "Scores should be in descending order")

        classifications_without_scores = actual_classifications
        classifications_without_scores.sort(
            key=operator.itemgetter('label_name'))
        self.assertListEqual(
            [
                dict(
                    label_id=self.labels_by_name['A'].pk, label_name='A',
                    label_code='A_mycode'),
                dict(
                    label_id=self.labels_by_name['B'].pk, label_name='B',
                    label_code='B_mycode'),
            ],
            classifications_without_scores,
            "Classifications JSON besides scores should be as expected")


class TaskErrorsTest(
    DeployBaseTest, EmailAssertionsMixin, ErrorReportTestMixin, JobUtilsMixin,
):
    """
    Test error cases of the deploy task.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.set_up_classifier(cls.user)

    def test_job_unit_deleted_before_run(self):
        """
        Try to run a deploy job when the API job unit
        has been deleted.
        """
        images = [
            dict(type='image', attributes=dict(
                url='URL 1', points=[dict(row=10, column=10)]))]
        data = json.dumps(dict(data=images))

        # Schedule deploy job
        self.client.post(self.deploy_url, data, **self.request_kwargs)

        # Delete the job unit.
        job_unit = ApiJobUnit.objects.latest('pk')
        api_job = job_unit.parent
        job_unit.delete()

        # Deploy. It should fail since the unit was deleted.
        run_scheduled_jobs()
        self.assert_job_failure_message(
            'classify_image',
            f"Job unit [{api_job.pk} / 1] does not exist.")

    def test_classifier_deleted_before_run(self):
        """
        Try to run a deploy job when the classifier associated with the job
        has been deleted.
        """
        images = [
            dict(type='image', attributes=dict(
                url='URL 1', points=[dict(row=10, column=10)]))]
        data = json.dumps(dict(data=images))

        # Schedule deploy job
        self.client.post(self.deploy_url, data, **self.request_kwargs)

        job_unit = ApiJobUnit.objects.latest('pk')

        # Delete the classifier.
        classifier_id = job_unit.request_json['classifier_id']
        classifier = Classifier.objects.get(pk=classifier_id)
        classifier.delete()

        # Deploy. It should fail since the classifier was deleted.
        run_scheduled_jobs()

        job_unit.refresh_from_db()

        self.assertEqual(
            job_unit.status, Job.Status.FAILURE,
            "Unit should have failed")
        self.assertEqual(
            job_unit.internal_job.result_message,
            f"Classifier of id {classifier_id} does not exist."
            f" Maybe it was deleted.")

    def test_internal_job_deleted_before_collect(self):
        images = [
            dict(type='image', attributes=dict(
                url='URL 1', points=[dict(row=10, column=10)]))]
        data = json.dumps(dict(data=images))

        # Schedule deploy job
        self.client.post(self.deploy_url, data, **self.request_kwargs)
        # Deploy
        run_scheduled_jobs()
        # Delete Job (which requires deleting the job unit first due to
        # protected foreign keys).
        unit = ApiJobUnit.objects.latest('pk')
        job = unit.internal_job
        unit.delete()
        job.delete()
        # Collect. The deleted Job shouldn't cause particular issues.
        # The corresponding BatchJob is considered successful, and besides
        # that there's no Job to mark the status of.
        self.do_collect_spacer_jobs()
        self.assert_job_result_message(
            'collect_spacer_jobs',
            "Jobs checked/collected: 1 SUCCEEDED",
        )

    def test_job_unit_deleted_before_collect(self):
        images = [
            dict(type='image', attributes=dict(
                url='URL 1', points=[dict(row=10, column=10)]))]
        data = json.dumps(dict(data=images))

        # Schedule deploy job
        self.client.post(self.deploy_url, data, **self.request_kwargs)
        # Deploy
        run_scheduled_jobs()
        # Delete job unit.
        unit = ApiJobUnit.objects.latest('pk')
        job_id = unit.internal_job_id
        unit.delete()
        # Collect.
        self.do_collect_spacer_jobs()
        self.assert_job_failure_message(
            'classify_image',
            f"API job unit for internal-job {job_id} does not exist.",
        )

    def do_test_spacer_error(self, error):
        images = [
            dict(type='image', attributes=dict(
                url='URL 1', points=[dict(row=10, column=10)]))]
        data = json.dumps(dict(data=images))

        # Schedule deploy
        self.client.post(self.deploy_url, data, **self.request_kwargs)

        # Deploy, while mocking the spacer task call. Thus, we don't test
        # spacer behavior itself. We just test that we appropriately handle any
        # errors coming from the spacer call.
        def raise_error(*args):
            raise error
        with mock.patch('spacer.tasks.classify_image', raise_error):
            run_scheduled_jobs()
        self.do_collect_spacer_jobs()

        return ApiJobUnit.objects.latest('pk')

    def test_spacer_priority_error(self):
        """Spacer error that's not in the non-priority categories."""

        job_unit = self.do_test_spacer_error(ValueError("A spacer error"))

        self.assertEqual(
            job_unit.status, Job.Status.FAILURE,
            "Unit should have failed")
        self.assertEqual(
            "ValueError: A spacer error", job_unit.result_message,
            "Result JSON should have the error info")

        self.assert_error_log_saved(
            "ValueError",
            "A spacer error",
        )
        self.assert_latest_email(
            "Spacer job failed: classify_image",
            ["ValueError: A spacer error"],
        )

    def test_url_download_error(self):
        """These errors aren't considered priority."""
        job_unit = self.do_test_spacer_error(URLDownloadError(
            "Couldn't access URL", ValueError("Original error")))

        self.assertEqual(
            job_unit.status, Job.Status.FAILURE,
            "Unit should have failed")
        self.assertEqual(
            "spacer.exceptions.URLDownloadError: Couldn't access URL"
            " / Details - ValueError: Original error",
            job_unit.result_message,
            "Result JSON should have the error info")

        self.assert_no_error_log_saved()
        self.assert_no_email()

    def test_unidentified_image_error(self):
        """These errors aren't considered priority."""
        job_unit = self.do_test_spacer_error(UnidentifiedImageError(
            "cannot identify image file <image>"))

        self.assertEqual(
            job_unit.status, Job.Status.FAILURE,
            "Unit should have failed")
        self.assertEqual(
            "PIL.UnidentifiedImageError: cannot identify image file <image>",
            job_unit.result_message,
            "Result JSON should have the error info")

        self.assert_no_error_log_saved()
        self.assert_no_email()

    def test_data_limit_error(self):
        """These errors aren't considered priority."""
        job_unit = self.do_test_spacer_error(DataLimitError(
            "1500 point locations were specified"))

        self.assertEqual(
            job_unit.status, Job.Status.FAILURE,
            "Unit should have failed")
        self.assertEqual(
            "spacer.exceptions.DataLimitError:"
            " 1500 point locations were specified",
            job_unit.result_message,
            "Result JSON should have the error info")

        self.assert_no_error_log_saved()
        self.assert_no_email()

    def test_row_column_invalid_error(self):
        """These errors aren't considered priority."""
        job_unit = self.do_test_spacer_error(RowColumnInvalidError(
            "Row value 909 falls outside this image's valid range of 0-799."))

        self.assertEqual(
            job_unit.status, Job.Status.FAILURE,
            "Unit should have failed")
        self.assertEqual(
            "spacer.exceptions.RowColumnInvalidError:"
            " Row value 909 falls outside this image's valid range of 0-799.",
            job_unit.result_message,
            "Result JSON should have the error info")

        self.assert_no_error_log_saved()
        self.assert_no_email()

    def test_classifier_deleted_before_collect(self):
        images = [
            dict(type='image', attributes=dict(
                url='URL 1', points=[dict(row=10, column=10)]))]
        data = json.dumps(dict(data=images))

        # Schedule deploy job
        self.client.post(self.deploy_url, data, **self.request_kwargs)
        # Deploy
        self.run_scheduled_jobs_including_deploy()
        # Delete classifier.
        unit = ApiJobUnit.objects.latest('pk')
        classifier_id = unit.request_json['classifier_id']
        Classifier.objects.get(pk=classifier_id).delete()
        # Collect.
        self.do_collect_spacer_jobs()
        self.assert_job_failure_message(
            'classify_image',
            f"Classifier of id {classifier_id} does not exist.",
        )


class ApiRequestsQueriesTest(DeployBaseTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.set_up_classifier(cls.user)

    def test(self):
        image_count = 30
        images = [
            dict(type='image', attributes=dict(
                url=f'URL {index}', points=[dict(row=10, column=10)]))
            for index in range(image_count)
        ]

        data = json.dumps(dict(data=images))

        # Should run less than 1 query per image.
        with self.assert_queries_less_than(image_count):
            response = self.client.post(
                self.deploy_url, data, **self.request_kwargs)

        self.assertEqual(
            response.status_code, status.HTTP_202_ACCEPTED,
            msg="Should get 202")

        deploy_job = ApiJob.objects.latest('pk')
        self.assertEqual(
            deploy_job.apijobunit_set.count(), image_count,
            msg=f"Should have {image_count} job units")


class ApiJobFinishDateTest(DeployBaseTest):
    """Test that an ApiJob gets its finish_date set when it's supposed to."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.set_up_classifier(cls.user)

    def test_single(self):
        images = [
            dict(type='image', attributes=dict(
                url=f'URL {index}', points=[dict(row=10, column=10)]))
            # 4 units
            for index in range(4)
        ]
        data = json.dumps(dict(data=images))
        # Schedule deploy
        self.client.post(self.deploy_url, data, **self.request_kwargs)

        api_job = ApiJob.objects.latest('pk')
        units = list(api_job.apijobunit_set.all())
        # Shouldn't have finish date yet: all pending
        self.assertIsNone(api_job.finish_date)

        start_job(units[0].internal_job)
        # Shouldn't have finish date yet: 1 in progress, rest pending
        api_job.refresh_from_db()
        self.assertIsNone(api_job.finish_date)

        start_job(units[1].internal_job)
        start_job(units[2].internal_job)
        start_job(units[3].internal_job)
        # Shouldn't have finish date yet: all in progress
        api_job.refresh_from_db()
        self.assertIsNone(api_job.finish_date)

        def mock_batcher(items, batch_size):
            # Force a batch size of 3 so that collect_spacer_jobs() doesn't
            # collect everything in one go.
            batch_size = 3
            index = 0
            while index < len(items):
                yield items[index:index+batch_size]
                index += batch_size

        with (
            override_settings(JOB_MAX_MINUTES=-1),
            mock.patch('vision_backend.tasks.batch_generator', mock_batcher),
        ):
            self.do_collect_spacer_jobs()
        # Shouldn't have finish date yet: 1 in progress, 3 finished
        api_job.refresh_from_db()
        self.assertIsNone(api_job.finish_date)

        self.do_collect_spacer_jobs()
        # Should have finish date: all finished
        api_job.refresh_from_db()
        self.assertIsNotNone(api_job.finish_date)

    def test_multiple(self):
        images = [
            dict(type='image', attributes=dict(
                url=f'URL {index}', points=[dict(row=10, column=10)]))
            # 2 units
            for index in range(2)
        ]
        data = json.dumps(dict(data=images))
        # 3 ApiJobs
        api_jobs = []
        units = []
        for _ in range(3):
            self.client.post(self.deploy_url, data, **self.request_kwargs)
            api_job = ApiJob.objects.latest('pk')
            api_jobs.append(api_job)
            units.append(list(api_job.apijobunit_set.all()))

        start_job(units[0][0].internal_job)
        start_job(units[0][1].internal_job)
        start_job(units[1][0].internal_job)
        # Shouldn't have finish dates yet: some in progress, some pending
        api_jobs[0].refresh_from_db()
        self.assertIsNone(api_jobs[0].finish_date)
        api_jobs[1].refresh_from_db()
        self.assertIsNone(api_jobs[1].finish_date)
        api_jobs[2].refresh_from_db()
        self.assertIsNone(api_jobs[2].finish_date)

        self.do_collect_spacer_jobs()
        # Should have finished [0] but not [1] (1/2 units) or [2] (0/2 units)
        api_jobs[0].refresh_from_db()
        self.assertIsNotNone(api_jobs[0].finish_date)
        api_jobs[1].refresh_from_db()
        self.assertIsNone(api_jobs[1].finish_date)
        api_jobs[2].refresh_from_db()
        self.assertIsNone(api_jobs[2].finish_date)

        start_job(units[1][1].internal_job)
        start_job(units[2][0].internal_job)
        start_job(units[2][1].internal_job)
        self.do_collect_spacer_jobs()
        # All finished
        api_jobs[0].refresh_from_db()
        self.assertIsNotNone(api_jobs[0].finish_date)
        api_jobs[1].refresh_from_db()
        self.assertIsNotNone(api_jobs[1].finish_date)
        api_jobs[2].refresh_from_db()
        self.assertIsNotNone(api_jobs[2].finish_date)


# TODO: Also query-optimize and test the task which starts the deploy job.


class CollectJobsQueriesTest(DeployBaseTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.set_up_classifier(cls.user)

    def test(self):
        image_count = 30
        images = [
            dict(type='image', attributes=dict(
                url=f'URL {index}', points=[dict(row=10, column=10)]))
            for index in range(image_count)
        ]

        data = json.dumps(dict(data=images))

        # Schedule deploy
        self.client.post(self.deploy_url, data, **self.request_kwargs)
        # Deploy run
        self.run_scheduled_jobs_including_deploy()
        # Deploy collect; should run less than 1 query per image.
        with self.assert_queries_less_than(image_count):
            self.do_collect_spacer_jobs()

        deploy_job = ApiJob.objects.latest('pk')
        self.assertEqual(
            deploy_job.apijobunit_set.filter(
                internal_job__status=Job.Status.SUCCESS).count(),
            image_count,
            msg=f"All {image_count} job units should have finished",
        )
