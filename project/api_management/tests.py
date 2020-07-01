from __future__ import unicode_literals

from bs4 import BeautifulSoup
from django.urls import reverse

from api_core.models import ApiJob, ApiJobUnit
from lib.tests.utils import BasePermissionTest, ClientTest


class PermissionTest(BasePermissionTest):

    def test_job_list(self):
        url = reverse('api_management:job_list')
        template = 'api_management/job_list.html'

        self.source_to_private()
        self.assertPermissionLevel(
            url, self.SUPERUSER, template=template,
            deny_type=self.REQUIRE_LOGIN)
        self.source_to_public()
        self.assertPermissionLevel(
            url, self.SUPERUSER, template=template,
            deny_type=self.REQUIRE_LOGIN)

    def test_job_detail(self):
        job = ApiJob(type='test', user=self.user)
        job.save()
        url = reverse('api_management:job_detail', args=[job.pk])
        template = 'api_management/job_detail.html'

        self.source_to_private()
        self.assertPermissionLevel(
            url, self.SUPERUSER, template=template,
            deny_type=self.REQUIRE_LOGIN)
        self.source_to_public()
        self.assertPermissionLevel(
            url, self.SUPERUSER, template=template,
            deny_type=self.REQUIRE_LOGIN)


class JobListTest(ClientTest):

    @classmethod
    def setUpTestData(cls):
        super(JobListTest, cls).setUpTestData()

        cls.user = cls.create_user()

    def test_all_table_columns(self):
        job = ApiJob(type='test_job_type', user=self.user)
        job.save()

        # Create job units of various statuses
        unit_statuses = (
            [ApiJobUnit.PENDING]*4 + [ApiJobUnit.IN_PROGRESS]*3
            + [ApiJobUnit.FAILURE]*2 + [ApiJobUnit.SUCCESS])
        for status in unit_statuses:
            unit = ApiJobUnit(
                job=job, type='test_unit_type', status=status, request_json={})
            unit.save()

        self.client.force_login(self.superuser)
        response = self.client.get(reverse('api_management:job_list'))

        response_soup = BeautifulSoup(response.content, 'html.parser')
        job_row = response_soup.find('tbody').find('tr')
        cells_text = [
            td.get_text().strip() for td in job_row.find_all('td')]

        self.assertEqual(cells_text[0], str(job.pk))
        # Date; we just check that it shows something
        self.assertNotEqual(cells_text[1], '')
        self.assertEqual(cells_text[2], self.user.username)
        self.assertEqual(cells_text[3], 'test_job_type')
        self.assertEqual(cells_text[4], ApiJob.IN_PROGRESS)
        # 4 pending + 3 in progress
        self.assertEqual(cells_text[5], '7')
        # Failures
        self.assertEqual(cells_text[6], '2')
        # Successes
        self.assertEqual(cells_text[7], '1')

    def test_all_job_statuses(self):
        pending_job = ApiJob(type='test', user=self.user)
        pending_job.save()
        unit = ApiJobUnit(
            job=pending_job, type='test', status=ApiJobUnit.PENDING,
            request_json={})
        unit.save()

        in_progress_job = ApiJob(type='test', user=self.user)
        in_progress_job.save()
        unit = ApiJobUnit(
            job=in_progress_job, type='test', status=ApiJobUnit.IN_PROGRESS,
            request_json={})
        unit.save()

        done_with_fails_job = ApiJob(type='test', user=self.user)
        done_with_fails_job.save()
        unit = ApiJobUnit(
            job=done_with_fails_job, type='test', status=ApiJobUnit.SUCCESS,
            request_json={})
        unit.save()
        unit = ApiJobUnit(
            job=done_with_fails_job, type='test', status=ApiJobUnit.FAILURE,
            request_json={})
        unit.save()

        done_success_job = ApiJob(type='test', user=self.user)
        done_success_job.save()
        unit = ApiJobUnit(
            job=done_success_job, type='test', status=ApiJobUnit.SUCCESS,
            request_json={})
        unit.save()

        self.client.force_login(self.superuser)
        response = self.client.get(reverse('api_management:job_list'))

        response_soup = BeautifulSoup(response.content, 'html.parser')
        job_rows = response_soup.find('tbody').find_all('tr')
        cells_text = [
            [td.get_text().strip() for td in row.find_all('td')]
            for row in job_rows]

        # Jobs are ordered by status: in progress, then pending, then done
        self.assertEqual(cells_text[0][0], str(in_progress_job.pk))
        self.assertEqual(cells_text[0][4], ApiJob.IN_PROGRESS)
        self.assertEqual(cells_text[1][0], str(pending_job.pk))
        self.assertEqual(cells_text[1][4], ApiJob.PENDING)
        # For jobs of the same status, latest ID first
        self.assertEqual(cells_text[2][0], str(done_success_job.pk))
        self.assertEqual(cells_text[2][4], ApiJob.DONE)
        self.assertEqual(cells_text[3][0], str(done_with_fails_job.pk))
        self.assertEqual(cells_text[3][4], ApiJob.DONE)


class JobDetailTest(ClientTest):

    @classmethod
    def setUpTestData(cls):
        super(JobDetailTest, cls).setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)
        cls.classifier = cls.create_robot(cls.source)

        cls.sample_request_json = dict(
            classifier_id=cls.classifier.pk,
            url='my/url',
            points=[dict(row=20, column=30), dict(row=40, column=50)],
        )
        cls.sample_result_json_with_error = dict(
            error="Error goes here",
        )

    def test_all_table_columns(self):
        job = ApiJob(type='test_job_type', user=self.user)
        job.save()

        unit = ApiJobUnit(
            job=job, type='test_unit_type', status=ApiJobUnit.FAILURE,
            request_json=self.sample_request_json,
            result_json=self.sample_result_json_with_error)
        unit.save()

        self.client.force_login(self.superuser)
        response = self.client.get(
            reverse('api_management:job_detail', args=[job.pk]))

        response_soup = BeautifulSoup(response.content, 'html.parser')
        unit_row = response_soup.find('tbody').find('tr')
        cells = unit_row.find_all('td')
        cells_text = [cell.get_text().strip() for cell in cells]

        request_json_as_html = (
            "<li>Classifier ID {} (Source ID {})</li>".format(
                self.classifier.pk, self.source.pk)
            + "<li>URL: my/url</li>"
            + "<li>Point count: 2</li>")

        self.assertEqual(cells_text[0], str(unit.pk))
        self.assertEqual(cells_text[1], 'test_unit_type')
        self.assertEqual(cells_text[2], "Failure")
        self.assertInHTML(
            request_json_as_html, str(cells[3].find('ul')))
        self.assertEqual(cells_text[4], "Error goes here")

    def test_deleted_classifier(self):
        classifier = self.create_robot(self.source)
        classifier_id = classifier.pk
        classifier.delete()

        job = ApiJob(type='test', user=self.user)
        job.save()

        request_json = self.sample_request_json.copy()
        request_json['classifier_id'] = classifier_id

        unit = ApiJobUnit(
            job=job, type='test', status=ApiJobUnit.FAILURE,
            request_json=request_json,
            result_json=self.sample_result_json_with_error)
        unit.save()

        self.client.force_login(self.superuser)
        response = self.client.get(
            reverse('api_management:job_detail', args=[job.pk]))

        response_soup = BeautifulSoup(response.content, 'html.parser')
        unit_row = response_soup.find('tbody').find('tr')
        cells = unit_row.find_all('td')

        request_json_as_html = (
            "<li>Classifier ID {} (deleted)</li>".format(classifier_id)
            + "<li>URL: my/url</li>"
            + "<li>Point count: 2</li>")
        self.assertInHTML(
            request_json_as_html, str(cells[3].find('ul')))

    def test_no_errors(self):
        job = ApiJob(type='test_job_type', user=self.user)
        job.save()

        unit = ApiJobUnit(
            job=job, type='test_unit_type', status=ApiJobUnit.SUCCESS,
            request_json=self.sample_request_json,
            result_json={})
        unit.save()

        self.client.force_login(self.superuser)
        response = self.client.get(
            reverse('api_management:job_detail', args=[job.pk]))

        response_soup = BeautifulSoup(response.content, 'html.parser')
        unit_row = response_soup.find('tbody').find('tr')
        cells = unit_row.find_all('td')
        cells_text = [cell.get_text().strip() for cell in cells]

        self.assertEqual(cells_text[4], "", "Error cell should be blank")

    def test_no_result_json(self):
        """
        Unfinished job units won't have any result_json set yet.
        """
        job = ApiJob(type='test_job_type', user=self.user)
        job.save()

        unit = ApiJobUnit(
            job=job, type='test_unit_type', status=ApiJobUnit.IN_PROGRESS,
            request_json=self.sample_request_json)
        unit.save()

        self.client.force_login(self.superuser)
        response = self.client.get(
            reverse('api_management:job_detail', args=[job.pk]))

        response_soup = BeautifulSoup(response.content, 'html.parser')
        unit_row = response_soup.find('tbody').find('tr')
        cells = unit_row.find_all('td')
        cells_text = [cell.get_text().strip() for cell in cells]

        self.assertEqual(cells_text[4], "", "Error cell should be blank")

    def test_all_unit_statuses(self):
        job = ApiJob(type='test_job_type', user=self.user)
        job.save()

        # Create job units of various statuses
        unit_statuses = [
            ApiJobUnit.PENDING, ApiJobUnit.IN_PROGRESS,
            ApiJobUnit.FAILURE, ApiJobUnit.SUCCESS]
        for status in unit_statuses:
            unit = ApiJobUnit(
                job=job, type='test_unit_type', status=status,
                request_json=self.sample_request_json)
            unit.save()

        self.client.force_login(self.superuser)
        response = self.client.get(
            reverse('api_management:job_detail', args=[job.pk]))

        response_soup = BeautifulSoup(response.content, 'html.parser')
        unit_rows = response_soup.find('tbody').find_all('tr')
        cells_text = [
            [td.get_text().strip() for td in row.find_all('td')]
            for row in unit_rows]

        # Units should be ordered latest to earliest
        self.assertEqual(cells_text[0][2], "Success")
        self.assertEqual(cells_text[1][2], "Failure")
        self.assertEqual(cells_text[2][2], "In Progress")
        self.assertEqual(cells_text[3][2], "Pending")
