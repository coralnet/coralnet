from abc import ABC, abstractmethod
from datetime import timedelta
import operator
from typing import Callable
from unittest import mock, skip

from bs4 import BeautifulSoup
from django.contrib.auth.models import User
from django.template.defaultfilters import date as date_template_filter
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from api_core.models import ApiJob, ApiJobUnit
from lib.tests.utils import (
    BasePermissionTest, ClientTest, HtmlAssertionsMixin, scrambled_run
)
from ..models import Job
from .utils import fabricate_job


def date_display(date):
    return date_template_filter(
        date.astimezone(timezone.get_current_timezone()), 'N j, Y, P')


class PermissionTest(BasePermissionTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.img = cls.upload_image(cls.user, cls.source)

    def test_summary(self):
        url = reverse('jobs:summary')
        template = 'jobs/all_jobs_summary.html'

        self.assertPermissionLevel(
            url, self.SUPERUSER, template=template,
            deny_type=self.REQUIRE_LOGIN)

    def test_all_jobs_list(self):
        url = reverse('jobs:all_jobs_list')
        template = 'jobs/all_jobs_list.html'

        self.assertPermissionLevel(
            url, self.SUPERUSER, template=template,
            deny_type=self.REQUIRE_LOGIN)

    def test_non_source_list(self):
        url = reverse('jobs:non_source_job_list')
        template = 'jobs/non_source_job_list.html'

        self.assertPermissionLevel(
            url, self.SUPERUSER, template=template,
            deny_type=self.REQUIRE_LOGIN)

    def test_source_job_list(self):
        url = reverse('jobs:source_job_list', args=[self.source.pk])
        template = 'jobs/source_job_list.html'

        self.source_to_private()
        self.assertPermissionLevel(url, self.SOURCE_EDIT, template=template)
        self.source_to_public()
        self.assertPermissionLevel(url, self.SOURCE_EDIT, template=template)

    def test_background_job_status(self):
        url = reverse('jobs:status')
        template = 'jobs/background_job_status.html'

        self.assertPermissionLevel(
            url, self.SIGNED_IN, template=template,
            deny_type=self.REQUIRE_LOGIN)


class JobViewTestMixin(HtmlAssertionsMixin, ABC):

    create_source: Callable
    create_user: Callable
    user: User

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.sources = [
            cls.create_source(cls.user, name="Source 1"),
            cls.create_source(cls.user, name="Source 2"),
            cls.create_source(cls.user, name="Source 3"),
            cls.create_source(cls.user, name="Source 4"),
            cls.create_source(cls.user, name="Source 5"),
            cls.create_source(cls.user, name="Source 6"),
        ]

    job_count = 0

    def job(
        self,
        status: Job.Status = Job.Status.PENDING,
        source: int | None = None,
        job_name: str = None,
        modified_time_ago: timedelta = None,
        started_time_ago: timedelta = None,
        scheduled_time_ago: timedelta = None,
        created_time_ago: timedelta = None,
        **kwargs
    ):
        """
        Shortcut method for creating a job for this class's purposes.
        """
        self.job_count += 1
        if not job_name:
            # For the purposes of this test class, we generally just need any
            # unique job name.
            job_name = str(self.job_count)

        updated_kwargs = kwargs | dict(status=status)
        if source:
            updated_kwargs['source_id'] = self.sources[source - 1].pk

        if modified_time_ago or started_time_ago or created_time_ago:
            now = timezone.now()
            if modified_time_ago:
                # This may also be negative to indicate time in future.
                updated_kwargs['modify_date'] = now - modified_time_ago
            if started_time_ago:
                updated_kwargs['start_date'] = now - started_time_ago
            if created_time_ago:
                updated_kwargs['create_date'] = now - created_time_ago
        if scheduled_time_ago:
            updated_kwargs['delay'] = -scheduled_time_ago
        job = fabricate_job(job_name, **updated_kwargs)

        return job


class JobSummaryTest(JobViewTestMixin, ClientTest):

    def get_response(self, data=None):
        self.client.force_login(self.superuser)
        url = reverse('jobs:summary')
        return self.client.get(url, data=data)

    def assert_summary_table_values(
        self, expected_values: list[dict|list], data=None
    ):
        response = self.get_response(data=data)
        response_soup = BeautifulSoup(response.content, 'html.parser')
        table_soup = response_soup.select('table#job-summary')[0]
        self.assert_table_values(table_soup, expected_values)

    @property
    def all_jobs_first_cell(self):
        return (
            f'<a href="{reverse("jobs:all_jobs_list")}">'
            f'All jobs</a>'
        )

    @property
    def non_source_jobs_first_cell(self):
        return (
            f'<a href="{reverse("jobs:non_source_job_list")}">'
            f'Non-source jobs</a>'
        )

    def source_cell(self, source_number):
        source = self.sources[source_number - 1]
        return (
            f'<a href="{reverse("jobs:source_job_list", args=[source.pk])}">'
            f'{source.name}</a>'
        )

    def test_no_jobs(self):
        self.assert_summary_table_values(
            [
                [self.all_jobs_first_cell, 0, 0, 0, '-'],
                [self.non_source_jobs_first_cell, 0, 0, 0, '-'],
            ]
        )

    def test_source_jobs_only(self):
        self.job(Job.Status.PENDING, source=1)
        self.job(Job.Status.PENDING, source=1)
        self.job(Job.Status.IN_PROGRESS, source=1)
        self.job(Job.Status.SUCCESS, source=1)
        self.job(Job.Status.SUCCESS, source=1)
        self.job(Job.Status.FAILURE, source=1)

        self.assert_summary_table_values(
            [
                [self.all_jobs_first_cell, 1, 2, 3, None],
                [self.non_source_jobs_first_cell, 0, 0, 0, '-'],
                [self.source_cell(1), 1, 2, 3, None],
            ]
        )

    def test_non_source_jobs_only(self):
        self.job(Job.Status.PENDING)
        self.job(Job.Status.PENDING)
        self.job(Job.Status.IN_PROGRESS)
        self.job(Job.Status.SUCCESS)
        self.job(Job.Status.SUCCESS)
        self.job(Job.Status.FAILURE)

        self.assert_summary_table_values(
            [
                [self.all_jobs_first_cell, 1, 2, 3, None],
                [self.non_source_jobs_first_cell, 1, 2, 3, None],
            ]
        )

    def test_source_and_non_source_jobs(self):
        self.job(Job.Status.PENDING, source=1)
        self.job(Job.Status.PENDING)

        self.assert_summary_table_values(
            [
                [self.all_jobs_first_cell, 0, 2, 0, None],
                [self.non_source_jobs_first_cell, 0, 1, 0, None],
                [self.source_cell(1), 0, 1, 0, None],
            ]
        )

    def test_sort_by_job_count(self):
        def f1(num):
            # 1st: most in-progress
            self.job(Job.Status.IN_PROGRESS, source=num)
            self.job(Job.Status.IN_PROGRESS, source=num)
        def f2(num):
            # 2nd: more pending than 3rd
            self.job(Job.Status.IN_PROGRESS, source=num)
            self.job(Job.Status.PENDING, source=num)
            self.job(Job.Status.PENDING, source=num)
        def f3(num):
            # 3rd: more completed than 4th
            self.job(Job.Status.IN_PROGRESS, source=num)
            self.job(Job.Status.PENDING, source=num)
            self.job(Job.Status.SUCCESS, source=num)
        def f4(num):
            # 4th
            self.job(Job.Status.IN_PROGRESS, source=num)
            self.job(Job.Status.PENDING, source=num)
        def f5(num):
            # 5th: most jobs overall but doesn't matter; last on in-progress
            self.job(Job.Status.PENDING, source=num)
            self.job(Job.Status.PENDING, source=num)
            self.job(Job.Status.SUCCESS, source=num)
            self.job(Job.Status.SUCCESS, source=num)
            self.job(Job.Status.SUCCESS, source=num)

        # Scramble the order to demonstrate that source name, source id,
        # and job date are not factors for sorting.
        run_order, _ = scrambled_run([f1, f2, f3, f4, f5])

        expected_source_rows: list[dict] = []
        for run_number in run_order:
            source_number = run_number
            expected_source_rows.append(
                {"Source": self.source_cell(source_number)})

        self.assert_summary_table_values(
            [{}, {}] + expected_source_rows
        )

    def test_sort_by_recently_updated(self):
        def f1(num):
            # 1st: has in progress, modified later
            self.job(
                Job.Status.IN_PROGRESS, source=num,
                modified_time_ago=timedelta(days=-1))
            self.job(Job.Status.PENDING, source=num)
        def f2(num):
            # 2nd: has in progress
            self.job(Job.Status.IN_PROGRESS, source=num)
            self.job(Job.Status.SUCCESS, source=num)

        def f3(num):
            # 3rd: has pending, modified later
            self.job(
                Job.Status.PENDING, source=num,
                modified_time_ago=timedelta(days=-1))
            self.job(Job.Status.SUCCESS, source=num)
        def f4(num):
            # 4th: has pending
            self.job(Job.Status.PENDING, source=num)
            self.job(Job.Status.PENDING, source=num)

        def f5(num):
            # 5th: only has completed, modified later
            self.job(Job.Status.SUCCESS, source=num)
            self.job(
                Job.Status.SUCCESS, source=num,
                modified_time_ago=timedelta(days=-1))
        def f6(num):
            # 6th: only has completed
            self.job(Job.Status.SUCCESS, source=num)
            self.job(Job.Status.SUCCESS, source=num)

        run_order, _ = scrambled_run([f1, f2, f3, f4, f5, f6])

        expected_source_rows: list[dict] = []
        for run_number in run_order:
            source_number = run_number
            expected_source_rows.append(
                {"Source": self.source_cell(source_number)})

        self.assert_summary_table_values(
            [{}, {}] + expected_source_rows,
            data=dict(source_sort_method='recently_updated')
        )

    def test_sort_by_source_name(self):
        def f1(_num):
            self.job(Job.Status.PENDING, source=1)
        def f2(_num):
            self.job(Job.Status.PENDING, source=2)
        def f3(_num):
            self.job(Job.Status.PENDING, source=3)

        run_order, _ = scrambled_run([f1, f2, f3])

        expected_source_rows: list[dict] = []
        for source_number in range(1, 1+len(run_order)):
            expected_source_rows.append(
                {"Source": self.source_cell(source_number)})

        self.assert_summary_table_values(
            [{}, {}] + expected_source_rows,
            data=dict(source_sort_method='source')
        )

    def test_source_job_age_cutoff(self):
        # Not old enough to clean up
        self.job(
            Job.Status.SUCCESS, source=1,
            modified_time_ago=timedelta(days=2, hours=23))

        # Old enough to clean up
        self.job(
            Job.Status.SUCCESS, source=2,
            modified_time_ago=timedelta(days=3, hours=1))

        # Old enough to clean up, but pending
        self.job(
            Job.Status.PENDING, source=3,
            modified_time_ago=timedelta(days=3, hours=1))

        # Old enough to clean up, but in progress
        self.job(
            Job.Status.IN_PROGRESS, source=4,
            modified_time_ago=timedelta(days=3, hours=1))

        self.assert_summary_table_values(
            [
                {},
                {},
                [self.source_cell(4), 1, 0, 0, None],
                [self.source_cell(3), 0, 1, 0, None],
                [self.source_cell(1), 0, 0, 1, None],
            ]
        )

    def test_non_source_job_age_cutoff(self):
        # Not old enough to clean up
        self.job(
            Job.Status.SUCCESS,
            modified_time_ago=timedelta(days=2, hours=23))

        # Old enough to clean up
        self.job(
            Job.Status.SUCCESS,
            modified_time_ago=timedelta(days=3, hours=1))

        # Old enough to clean up, but pending
        self.job(
            Job.Status.PENDING,
            modified_time_ago=timedelta(days=3, hours=1))

        # Old enough to clean up, but in progress
        self.job(
            Job.Status.IN_PROGRESS,
            modified_time_ago=timedelta(days=3, hours=1))

        # Should only show 1 pending
        self.assert_summary_table_values(
            [
                [self.all_jobs_first_cell, 1, 1, 1, None],
                [self.non_source_jobs_first_cell, 1, 1, 1, None],
            ]
        )

    def test_custom_age_cutoff(self):
        # Not old enough to clean up
        self.job(
            Job.Status.SUCCESS, source=1,
            modified_time_ago=timedelta(days=12, hours=23))

        # Old enough to clean up
        self.job(
            Job.Status.SUCCESS, source=2,
            modified_time_ago=timedelta(days=13, hours=1))

        self.assert_summary_table_values(
            [
                {},
                {},
                [self.source_cell(1), 0, 0, 1, None],
            ],
            data=dict(completed_count_day_limit=13)
        )

    def test_age_cutoff_limits(self):
        def page_response(day_limit):
            return self.get_response(
                data=dict(completed_count_day_limit=day_limit))

        message = "Search parameters were invalid."
        self.assertContains(page_response(0), message)
        self.assertNotContains(page_response(1), message)
        self.assertNotContains(page_response(30), message)
        self.assertContains(page_response(31), message)


class JobListTestsMixin(JobViewTestMixin, ABC):
    """
    Tests common to all the job-list views.

    Test methods aren't detected from this class itself since it's not a
    descendant of unittest.TestCase.
    However, the test methods will be detected in TestCase descendants
    which use this class as a mixin.

    This achieves a high level of DRY, though one drawback is that
    PyCharm has trouble running tests individually in this scheme
    (so manage.py commands must be used instead).
    """
    @property
    @abstractmethod
    def view_shows_source_jobs(self) -> bool:
        raise NotImplementedError

    @property
    @abstractmethod
    def view_shows_non_source_jobs(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def get_response(self, data=None):
        raise NotImplementedError

    def table_soup(self, data=None):
        response = self.get_response(data=data)
        response_soup = BeautifulSoup(response.content, 'html.parser')
        return response_soup.select('table#job-table')[0]

    def assert_job_table_values(
        self, expected_values: list[dict|list], data=None
    ):
        response = self.get_response(data=data)
        response_soup = BeautifulSoup(response.content, 'html.parser')
        table_soup = response_soup.select('table#job-table')[0]
        self.assert_table_values(table_soup, expected_values)

    def test_no_jobs(self):
        response = self.get_response()
        self.assertContains(response, "(No jobs found)")

    @override_settings(JOB_MAX_DAYS=30)
    def test_cleanup_message(self):
        # No-job case
        response = self.get_response()
        self.assertContains(
            response,
            "Most job records are cleaned up after approximately 30 days.")

        self.job()

        # With-jobs case
        response = self.get_response()
        self.assertContains(
            response,
            "Most job records are cleaned up after approximately 30 days,"
            " except for jobs with * in Timing info.")

    def test_job_id_column(self):
        jobs = [
            self.job(),
            self.job(),
            self.job(),
        ]

        self.assert_job_table_values(
            list(reversed([
                {"Job ID": jobs[0].pk},
                {"Job ID": jobs[1].pk},
                {"Job ID": jobs[2].pk},
            ]))
        )

    def test_job_type_column(self):
        self.job(job_name='extract_features')
        self.job(job_name='train_classifier')
        self.job(job_name='classify_features')
        self.job(job_name='update_label_details')
        self.job(job_name='classify_image')

        self.assert_job_table_values(
            list(reversed([
                {"Type": "Extract features"},
                {"Type": "Train classifier"},
                # Special case
                {"Type": "Classify"},
                {"Type": "Update label details"},
                # Special case
                {"Type": "Deploy"},
            ]))
        )

    @skip(
        "This test interacts badly with tests that register made-up jobs."
        " Not sure how to solve that in a clean way yet.")
    def test_type_choices(self):
        response = self.get_response()
        form = response.context['job_search_form']

        source_types = [
            ('check_source', "Check source"),
            ('classify_features', "Classify"),
            ('extract_features', "Extract features"),
            ('reset_classifiers_for_source',
             "Reset classifiers for source"),
            ('reset_features_for_source', "Reset features for source"),
            ('train_classifier', "Train classifier"),
        ]
        non_source_types = [
            ('check_all_sources', "Check all sources"),
            ('classify_image', "Deploy"),
            ('clean_up_old_api_jobs', "Clean up old api jobs"),
            ('clean_up_old_jobs', "Clean up old jobs"),
            ('collect_spacer_jobs', "Collect spacer jobs"),
            ('generate_patch', "Generate patch"),
            ('generate_thumbnail', "Generate thumbnail"),
            ('report_stuck_jobs', "Report stuck jobs"),
            ('run_scheduled_jobs', "Run scheduled jobs"),
            ('schedule_periodic_jobs', "Schedule periodic jobs"),
            ('update_label_details', "Update label details"),
            ('update_map_sources', "Update map sources"),
            ('update_sitewide_annotation_count',
             "Update sitewide annotation count"),
        ]

        if self.view_shows_source_jobs and self.view_shows_non_source_jobs:
            expected_choices = [
                ('', "Any"),
                ('background_queue_types', "Any background job"),
                ('realtime_queue_types', "Any realtime job"),
            ] + source_types + non_source_types
            expected_choices.sort(key=operator.itemgetter(1))
        elif self.view_shows_source_jobs:
            expected_choices = [
                ('', "Any"),
            ] + source_types
        else:
            expected_choices = [
                ('', "Any"),
                ('background_queue_types', "Any background job"),
                ('realtime_queue_types', "Any realtime job"),
            ] + non_source_types

        self.assertListEqual(
            list(form.fields['type'].choices),
            expected_choices,
        )

    def test_status_row_classes(self):
        self.job(Job.Status.PENDING)
        self.job(Job.Status.IN_PROGRESS)
        self.job(Job.Status.SUCCESS)
        self.job(Job.Status.FAILURE)

        table = self.table_soup(data=dict(sort='latest_scheduled'))
        rows = table.select('tbody > tr')
        self.assertEqual(rows[0].attrs['class'], ['failure'])
        self.assertEqual(rows[1].attrs['class'], ['success'])
        self.assertEqual(rows[2].attrs['class'], ['in_progress'])
        self.assertEqual(rows[3].attrs['class'], ['pending'])

    def test_status_column(self):
        self.job(Job.Status.PENDING)
        self.job(Job.Status.IN_PROGRESS)
        self.job(Job.Status.SUCCESS)
        self.job(Job.Status.FAILURE)

        self.assert_job_table_values(
            [
                {"Status": "Failure"},
                {"Status": "Success"},
                {"Status": "In Progress"},
                {"Status": "Pending"},
            ],
            data=dict(sort='latest_scheduled')
        )

    def test_other_id_column(self):

        if self.view_shows_source_jobs:

            job = fabricate_job(
                'extract_features', '1', source_id=self.sources[0].pk)
            image_1_url = reverse('image_detail', args=['1'])
            self.assert_job_table_values([
                {"Other ID": f'<a href="{image_1_url}">Image 1</a>'}])
            job.delete()

            job = fabricate_job(
                'train_classifier', '2', source_id=self.sources[0].pk)
            self.assert_job_table_values([
                {"Other ID": ''}])
            job.delete()

            job = fabricate_job(
                'classify_features', '3', source_id=self.sources[0].pk)
            image_3_url = reverse('image_detail', args=['3'])
            self.assert_job_table_values([
                {"Other ID": f'<a href="{image_3_url}">Image 3</a>'}])
            job.delete()

        if self.view_shows_non_source_jobs:

            job = fabricate_job('update_label_details', '1', '2')
            self.assert_job_table_values([
                {"Other ID": ''}])
            job.delete()

            job = fabricate_job('classify_image', '3', '4')
            api_job = ApiJob(type='deploy', user=self.user)
            api_job.save()
            api_job_unit = ApiJobUnit(
                parent=api_job, order_in_parent=1, internal_job=job,
                request_json={})
            api_job_unit.save()
            api_job_url = reverse(
                'api_management:job_detail', args=[api_job.pk])
            self.assert_job_table_values([
                {"Other ID":
                     f'<a href="{api_job_url}">'
                     f'API unit {api_job_unit.pk}</a>'}])
            api_job_unit.delete()
            job.delete()

    def test_result_message_column(self):
        self.job(Job.Status.SUCCESS)

        job = self.job(Job.Status.FAILURE)
        job.result_message = "Error message goes here"
        job.save()

        job = self.job(Job.Status.SUCCESS)
        job.result_message = "Comment about the result goes here"
        job.save()

        self.assert_job_table_values(
            [
                {"Detail": "Comment about the result goes here"},
                {"Detail": "Error message goes here"},
                {"Detail": ""},
            ]
        )

    def test_scheduled_column(self):
        # Just keep changing the same job so we don't have to worry about
        # ordering.
        job = self.job(delay=timedelta(minutes=10))
        self.assert_job_table_values([
            {"Scheduled start date": date_display(job.scheduled_start_date)}])

        job.start_date = job.scheduled_start_date - timedelta(minutes=10)
        job.scheduled_start_date = None
        job.save()
        self.assert_job_table_values([
            {"Scheduled start date": date_display(job.start_date)}])

        job.start_date = None
        job.save()
        self.assert_job_table_values([
            {"Scheduled start date": "-"}])

    def assert_cell_and_title(self, column_name, expected_cell, expected_title):
        if expected_title:
            cell_html = (
                f'<span class="tooltip" title="{expected_title}">'
                f'{expected_cell}</span>')
        else:
            cell_html = f'<span>{expected_cell}</span>'
        self.assert_job_table_values([{column_name: cell_html}])

    def test_timing_column(self):
        job = self.job(
            Job.Status.PENDING,
            delay=-timedelta(minutes=10, seconds=30),
        )
        self.assert_cell_and_title(
            "Timing info", "Waited for 10\xa0minutes so far",
            None,
        )

        job.scheduled_start_date = (
            timezone.now() + timedelta(minutes=11, seconds=30))
        job.save()
        self.assert_cell_and_title(
            "Timing info", "11\xa0minutes until scheduled start",
            None,
        )

        job.scheduled_start_date = None
        job.create_date = timezone.now() - timedelta(minutes=12, seconds=30)
        job.save()
        self.assert_cell_and_title(
            "Timing info", "Created 12\xa0minutes ago",
            f"Created: {date_display(job.create_date)}",
        )

        job.status = Job.Status.IN_PROGRESS
        job.start_date = timezone.now() - timedelta(minutes=13, seconds=30)
        job.save()
        self.assert_cell_and_title(
            "Timing info", "Started 13\xa0minutes ago",
            f"Started: {date_display(job.start_date)}",
        )

        job.status = Job.Status.SUCCESS
        job.scheduled_start_date = timezone.now() - timedelta(minutes=30)
        job.save()
        # Use QuerySet.update() instead of Model.save() so that the modify
        # date doesn't get auto-updated to the current date.
        Job.objects.filter(pk=job.pk).update(
            modify_date=timezone.now() - timedelta(minutes=14, seconds=30))
        job.refresh_from_db()
        self.assert_cell_and_title(
            "Timing info", "Completed 14\xa0minutes ago",
            f"Completed {date_display(job.modify_date)},"
            f" 15\xa0minutes after scheduled start",
        )

        # Test 1) no scheduled start date, but start date; and 2) persist flag
        job.status = Job.Status.FAILURE
        job.scheduled_start_date = None
        job.start_date = timezone.now() - timedelta(minutes=34)
        job.persist = True
        job.save()
        Job.objects.filter(pk=job.pk).update(
            modify_date=timezone.now() - timedelta(minutes=16, seconds=30))
        job.refresh_from_db()
        self.assert_cell_and_title(
            "Timing info", "Completed 16\xa0minutes ago *",
            f"Completed {date_display(job.modify_date)},"
            f" 17\xa0minutes after scheduled start",
        )

    @override_settings(JOBS_PER_PAGE=2)
    def test_multiple_pages(self):
        for _ in range(7):
            self.job()

        for page, expected_row_count in [(1, 2), (2, 2), (3, 2), (4, 1)]:
            self.assert_job_table_values(
                # Just verify the row count
                [{}] * expected_row_count,
                data=dict(page=page)
            )

    def test_sort_by_status(self):
        def f1(_num):
            # 1st: incomplete, scheduled 1st
            return self.job(
                Job.Status.PENDING, scheduled_time_ago=timedelta(hours=2))
        def f2(_num):
            # 2nd: incomplete, scheduled 2nd
            # (pending/incomplete doesn't matter)
            return self.job(
                Job.Status.IN_PROGRESS, scheduled_time_ago=timedelta(hours=1))
        def f3(_num):
            # 3rd: incomplete, scheduled 3rd
            return self.job(
                Job.Status.PENDING, scheduled_time_ago=timedelta(hours=-2))

        def f4(_num):
            # 4th: completed, modified latest
            return self.job(
                Job.Status.SUCCESS, modified_time_ago=timedelta(minutes=1))
        def f5(_num):
            # 5th: completed, modified 2nd latest
            # (success/failure doesn't matter)
            return self.job(
                Job.Status.FAILURE, modified_time_ago=timedelta(hours=1))
        def f6(_num):
            # 6th: completed, modified 3rd latest
            return self.job(
                Job.Status.SUCCESS, modified_time_ago=timedelta(hours=3))

        run_order, returned_jobs = scrambled_run([f1, f2, f3, f4, f5, f6])

        expected_rows = []
        for run_number in run_order:
            job = returned_jobs[run_number]
            expected_rows.append({"Job ID": job.pk, "Type": job.job_name})

        self.assert_job_table_values(expected_rows)

    def test_sort_by_recently_updated(self):
        def f1(_num):
            # 1st
            return self.job(Job.Status.PENDING)
        def f2(_num):
            # 2nd; different status to demonstrate it doesn't affect order
            return self.job(
                Job.Status.SUCCESS, modified_time_ago=timedelta(days=1))
        def f3(_num):
            # 3rd
            return self.job(
                Job.Status.IN_PROGRESS, modified_time_ago=timedelta(days=2))

        run_order, returned_jobs = scrambled_run([f1, f2, f3])

        expected_rows = []
        for run_number in run_order:
            job = returned_jobs[run_number]
            expected_rows.append({"Job ID": job.pk, "Type": job.job_name})

        self.assert_job_table_values(
            expected_rows, data=dict(sort='recently_updated'))

    def test_sort_by_latest_scheduled(self):
        def f1(_num):
            # 1st
            return self.job(
                Job.Status.IN_PROGRESS, scheduled_time_ago=timedelta(hours=-1))
        def f2(_num):
            # 2nd; no scheduled date, but has start date, which is sorted with
            # the scheduled start dates of other jobs
            return self.job(
                Job.Status.SUCCESS,
                scheduled_time_ago=None, started_time_ago=timedelta(hours=1))
        def f3(_num):
            # 3rd
            return self.job(
                Job.Status.PENDING, scheduled_time_ago=timedelta(hours=2))
        def f4(_num):
            # 4th; no scheduled start date or start date
            return self.job(
                Job.Status.PENDING,
                scheduled_time_ago=None, started_time_ago=None)

        run_order, returned_jobs = scrambled_run([f1, f2, f3, f4])

        expected_rows = []
        for run_number in run_order:
            job = returned_jobs[run_number]
            expected_rows.append({"Job ID": job.pk, "Type": job.job_name})

        self.assert_job_table_values(
            expected_rows, data=dict(sort='latest_scheduled'))

    def test_filter_by_status(self):
        jobs = [
            self.job(Job.Status.PENDING),
            self.job(Job.Status.PENDING),
            self.job(Job.Status.IN_PROGRESS),
            self.job(Job.Status.IN_PROGRESS),
            self.job(Job.Status.SUCCESS),
            self.job(Job.Status.SUCCESS),
            self.job(Job.Status.FAILURE),
            self.job(Job.Status.FAILURE),
        ]

        self.assert_job_table_values(
            list(reversed(
                [{"Job ID": job.pk} for job in jobs[:2]])),
            data=dict(status='pending')
        )
        self.assert_job_table_values(
            list(reversed(
                [{"Job ID": job.pk} for job in jobs[2:4]])),
            data=dict(status='in_progress')
        )
        self.assert_job_table_values(
            list(reversed(
                [{"Job ID": job.pk} for job in jobs[4:6]])),
            data=dict(status='success')
        )
        self.assert_job_table_values(
            list(reversed(
                [{"Job ID": job.pk} for job in jobs[6:]])),
            data=dict(status='failure')
        )
        self.assert_job_table_values(
            list(reversed(
                [{"Job ID": job.pk} for job in jobs[4:]])),
            data=dict(status='completed')
        )

    def test_filter_by_type(self):
        source_id = self.sources[0].pk
        jobs = [
            fabricate_job('extract_features', '1', source_id=source_id),
            fabricate_job('extract_features', '2', source_id=source_id),
            fabricate_job('check_source', source_id=source_id),
            fabricate_job('update_label_details'),
            fabricate_job('deploy', '1'),
            fabricate_job('deploy', '2'),
            fabricate_job('generate_thumbnail', '1'),
            fabricate_job('generate_thumbnail', '2'),
            fabricate_job('generate_patch', '1'),
            fabricate_job('generate_patch', '2'),
        ]

        if self.view_shows_source_jobs:

            self.assert_job_table_values(
                list(reversed(
                    [{"Job ID": job.pk} for job in jobs[:2]])),
                data=dict(type='extract_features')
            )

            self.assert_job_table_values(
                list(reversed(
                    [{"Job ID": job.pk} for job in jobs[2:3]])),
                data=dict(type='check_source')
            )

        if self.view_shows_non_source_jobs:

            self.assert_job_table_values(
                list(reversed(
                    [{"Job ID": job.pk} for job in jobs[3:4]])),
                data=dict(type='update_label_details')
            )

            self.assert_job_table_values(
                list(reversed(
                    [{"Job ID": job.pk} for job in jobs[4:6]])),
                data=dict(type='deploy')
            )

            self.assert_job_table_values(
                list(reversed(
                    [{"Job ID": job.pk} for job in jobs[6:8]])),
                data=dict(type='generate_thumbnail')
            )

            self.assert_job_table_values(
                list(reversed(
                    [{"Job ID": job.pk} for job in jobs[8:]])),
                data=dict(type='generate_patch')
            )

            if self.view_shows_source_jobs:
                expected_jobs = jobs[:6]
            else:
                expected_jobs = jobs[3:6]
            self.assert_job_table_values(
                list(reversed(
                    [{"Job ID": job.pk} for job in expected_jobs])),
                data=dict(type='background_queue_types')
            )

            self.assert_job_table_values(
                list(reversed(
                    [{"Job ID": job.pk} for job in jobs[6:]])),
                data=dict(type='realtime_queue_types')
            )

    def test_invalid_search_message(self):
        message = "Search parameters were invalid."
        self.assertNotContains(self.get_response(), message)
        self.assertContains(
            self.get_response(data=dict(status='unknown_status')), message)
        self.assertContains(
            self.get_response(data=dict(sort='unknown_sort')), message)


class AllJobsListTest(JobListTestsMixin, ClientTest):

    def get_response(self, data=None):
        self.client.force_login(self.superuser)
        url = reverse('jobs:all_jobs_list')
        return self.client.get(url, data=data)

    @property
    def view_shows_source_jobs(self):
        return True

    @property
    def view_shows_non_source_jobs(self):
        return True

    def test_source_column(self):
        self.job(source=1)
        self.job(source=2)
        self.job(source=None)

        def source_jobs_url(source):
            return reverse('jobs:source_job_list', args=[source.pk])

        self.assert_job_table_values(
            list(reversed([
                {"Source":
                     f'<a href="{source_jobs_url(self.sources[0])}">'
                     f'{self.sources[0].name}</a>'},
                {"Source":
                     f'<a href="{source_jobs_url(self.sources[1])}">'
                     f'{self.sources[1].name}</a>'},
                {"Source": ''},
            ]))
        )


class SourceJobListTest(JobListTestsMixin, ClientTest):

    def get_response(self, data=None):
        self.client.force_login(self.user)
        url = reverse(
            'jobs:source_job_list', args=[self.sources[0].pk])
        return self.client.get(url, data=data)

    def assert_source_check_status_equal(self, expected_content):
        response = self.get_response()
        response_soup = BeautifulSoup(response.content, 'html.parser')
        status_soup = response_soup.select('#source-check-status')[0]
        actual_content=''.join(
            [str(item) for item in status_soup.contents])
        self.assertHTMLEqual(
            actual_content, expected_content,
            msg="Source-check status line should be as expected"
        )

    @property
    def view_shows_source_jobs(self):
        return True

    @property
    def view_shows_non_source_jobs(self):
        return False

    def job(
        self, status: Job.Status = Job.Status.PENDING,
        source: int|None = 1, **kwargs
    ):
        return super().job(
            status=status,
            source=source,
            **kwargs
        )

    def test_this_sources_jobs_only(self):
        self.sources[1] = self.create_source(self.user, name="Source 2")

        job = self.job(source=1)
        # Shouldn't show this
        self.job(source=2)
        # Shouldn't show this
        self.job(source=None)

        self.assert_job_table_values(
            [
                {"Job ID": job.pk},
            ]
        )

    def test_check_source_message(self):
        # No recent source check
        self.assert_source_check_status_equal(
            "This source hasn't been status-checked recently.")

        # In progress
        job = fabricate_job(
            'check_source', self.sources[0].pk,
            source_id=self.sources[0].pk,
            status=Job.Status.IN_PROGRESS)
        self.assert_source_check_status_equal(
            "This source is currently being checked for jobs to schedule.")

        # Completed checks
        job.status = Job.Status.SUCCESS
        job.result_message = "Message 1"
        job.save()
        job = fabricate_job(
            'check_source', self.sources[0].pk,
            source_id=self.sources[0].pk,
            status=Job.Status.SUCCESS)
        job.result_message = "Message 2"
        job.save()
        # Should show the most recent completed source check
        date = date_display(job.modify_date)
        self.assert_source_check_status_equal(
            f'<strong>Latest source check result:</strong>'
            f' Message 2 ({date})')


class NonSourceJobListTest(JobListTestsMixin, ClientTest):

    @property
    def view_shows_source_jobs(self):
        return False

    @property
    def view_shows_non_source_jobs(self):
        return True

    def get_response(self, data=None):
        self.client.force_login(self.superuser)
        url = reverse('jobs:non_source_job_list')
        return self.client.get(url, data=data)

    def test_non_source_jobs_only(self):
        # Shouldn't show this
        self.job(source=1)
        job = self.job(source=None)

        self.assert_job_table_values(
            [
                {"Job ID": job.pk},
            ]
        )


class BackgroundJobStatusTest(JobViewTestMixin, ClientTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()

    def get_response(self, user=None, data=None):
        if user is None:
            user = self.user
        self.client.force_login(user)
        url = reverse('jobs:status')
        return self.client.get(url, data=data)

    def get_content_soup(self, user=None, data=None):
        response = self.get_response(user=user, data=data)
        response_soup = BeautifulSoup(response.content, 'html.parser')
        return response_soup.select('#content-container')[0]

    def get_detail_list_soup(self, user=None, data=None):
        response = self.get_response(user=user, data=data)
        response_soup = BeautifulSoup(response.content, 'html.parser')
        return response_soup.select('ul.detail_list')[0]

    def test_wait_time(self):
        def f_20m(_num):
            # Wait time: 20 minutes
            self.job(
                status=Job.Status.SUCCESS,
                scheduled_time_ago=timedelta(days=2, minutes=50),
                started_time_ago=timedelta(days=2, minutes=30),
            )
        def f_2h(_num):
            # Wait time: 2 hours
            self.job(
                status=Job.Status.SUCCESS,
                scheduled_time_ago=timedelta(hours=7),
                started_time_ago=timedelta(hours=5),
            )
        def f_1d(_num):
            # Wait time: 1 day
            self.job(
                status=Job.Status.IN_PROGRESS,
                scheduled_time_ago=timedelta(days=2, hours=3),
                started_time_ago=timedelta(days=1, hours=3),
            )
        def f_1d10h(_num):
            # Wait time: 1 day 10 hours
            self.job(
                status=Job.Status.FAILURE,
                scheduled_time_ago=timedelta(days=2, hours=22),
                started_time_ago=timedelta(days=1, hours=12),
            )
        def f_1d20h(_num):
            # Wait time: 1 day 20 hours
            self.job(
                status=Job.Status.FAILURE,
                scheduled_time_ago=timedelta(days=1, hours=23),
                started_time_ago=timedelta(hours=3),
            )

        # 20 jobs total;
        # The 10th percentile should be calculated as being between 2nd
        # and 3rd, and 9x closer to the 3rd. So (20m + 2h*9) / 10 = 110m.
        # The 90th percentile should be calculated as being between 18th
        # and 19th, and 9x closer to the 18th. So (1d*9 + 1d10h) / 10 = 1d1h.
        scrambled_run([f_20m]*2 + [f_2h] + [f_1d]*15 + [f_1d10h, f_1d20h])

        detail_list_soup = self.get_detail_list_soup()
        self.assertInHTML(
            "Time waited before starting: 1\xa0hour, 50\xa0minutes ~ 1\xa0day, 1\xa0hour",
            str(detail_list_soup))

    def test_wait_time_no_jobs(self):
        # Jobs that don't have both a scheduled start time and a start time
        # don't count.
        self.job(
            status=Job.Status.PENDING,
            scheduled_time_ago=timedelta(days=2, minutes=50),
        )
        self.job(
            status=Job.Status.SUCCESS,
            started_time_ago=timedelta(days=2, minutes=30),
        )
        # Jobs not started within the recency threshold don't count.
        self.job(
            status=Job.Status.IN_PROGRESS,
            scheduled_time_ago=timedelta(days=3, hours=2),
            started_time_ago=timedelta(days=3, hours=1),
        )

        detail_list_soup = self.get_detail_list_soup()
        self.assertInHTML(
            "Time waited before starting: 0\xa0minutes ~ 0\xa0minutes",
            str(detail_list_soup))

    def test_total_time(self):
        # The 30-second adjustments below provide some leeway for the time
        # string assertions, given that timesince() truncates to the minute
        # instead of rounding.

        def f_0m(_num):
            # Total time: 0
            self.job(
                status=Job.Status.SUCCESS,
                scheduled_time_ago=timedelta(minutes=5, seconds=30),
                modified_time_ago=timedelta(minutes=5),
            )
        def f_10m(_num):
            # Total time: 10 minutes
            self.job(
                status=Job.Status.FAILURE,
                scheduled_time_ago=timedelta(minutes=15, seconds=30),
                modified_time_ago=timedelta(minutes=5),
            )
        def f_20m(_num):
            # Total time: 20 minutes
            self.job(
                status=Job.Status.SUCCESS,
                scheduled_time_ago=timedelta(minutes=25, seconds=30),
                modified_time_ago=timedelta(minutes=5),
            )

        # 20 jobs total;
        # The 10th percentile should be calculated as being between 2nd
        # and 3rd, and 9x closer to the 3rd. So (0m + 10m*9) / 10 = 9m.
        # The 90th percentile should be calculated as being between 18th
        # and 19th, and 9x closer to the 18th. So (10m*9 + 20m) / 10 = 11m.
        scrambled_run([f_0m]*2 + [f_10m]*16 + [f_20m]*2)

        detail_list_soup = self.get_detail_list_soup()
        self.assertInHTML(
            "Total time: 9\xa0minutes ~ 11\xa0minutes",
            str(detail_list_soup))

    def test_total_time_no_jobs(self):
        # Jobs that don't have a scheduled start time don't count.
        self.job(
            status=Job.Status.SUCCESS,
            modified_time_ago=timedelta(days=1),
        )
        # Jobs not modified within the recency threshold don't count.
        self.job(
            status=Job.Status.SUCCESS,
            scheduled_time_ago=timedelta(days=5),
            modified_time_ago=timedelta(days=4),
        )
        # Incomplete jobs don't count.
        self.job(
            status=Job.Status.PENDING,
            scheduled_time_ago=timedelta(minutes=30),
            modified_time_ago=timedelta(minutes=20),
        )
        self.job(
            status=Job.Status.IN_PROGRESS,
            scheduled_time_ago=timedelta(minutes=30),
            modified_time_ago=timedelta(minutes=20),
        )

        detail_list_soup = self.get_detail_list_soup()
        self.assertInHTML(
            "Total time: 0\xa0minutes ~ 0\xa0minutes",
            str(detail_list_soup))

    def test_incomplete_count(self):

        now = timezone.now()

        def get_time_ago(**kwargs):
            return now - timedelta(**kwargs)

        expected_graph_data = []

        # 3 jobs exist before the 3-day timeline
        with mock.patch('django.utils.timezone.now') as mock_now:
            mock_now.return_value = get_time_ago(days=3, hours=6)
            job1 = self.job(status=Job.Status.PENDING)
            job2 = self.job(status=Job.Status.PENDING)
            job3 = self.job(status=Job.Status.IN_PROGRESS)
        expected_graph_data.insert(0, dict(
            x=0, y=3,
            tooltip=(
                "3\xa0days ago"
                "<br><strong>3</strong> incomplete jobs"
            )
        ))
        expected_graph_data.insert(0, dict(
            x=1, y=3,
            tooltip=(
                "2\xa0days, 12\xa0hours ago"
                "<br><strong>3</strong> incomplete jobs"
                "<br>Last 12\xa0hours: 0 completed, 0 created"
            )
        ))

        # One 12-hour interval creates and completes jobs
        with mock.patch('django.utils.timezone.now') as mock_now:
            mock_now.return_value = get_time_ago(days=2, hours=6)
            job1.status = Job.Status.SUCCESS
            job1.save()
            job4 = self.job(status=Job.Status.PENDING)
            _job5 = self.job(status=Job.Status.IN_PROGRESS)
        expected_graph_data.insert(0, dict(
            x=2, y=4,
            tooltip=(
                "2\xa0days ago"
                "<br><strong>4</strong> incomplete jobs"
                "<br>Last 12\xa0hours: 1 completed, 2 created"
            )
        ))

        # One 12-hour interval completes jobs
        with mock.patch('django.utils.timezone.now') as mock_now:
            mock_now.return_value = get_time_ago(days=1, hours=18)
            job2.status = Job.Status.FAILURE
            job2.save()
            job4.status = Job.Status.SUCCESS
            job4.save()
        expected_graph_data.insert(0, dict(
            x=3, y=2,
            tooltip=(
                "1\xa0day, 12\xa0hours ago"
                "<br><strong>2</strong> incomplete jobs"
                "<br>Last 12\xa0hours: 2 completed, 0 created"
            )
        ))
        expected_graph_data.insert(0, dict(
            x=4, y=2,
            tooltip=(
                "1\xa0day ago"
                "<br><strong>2</strong> incomplete jobs"
                "<br>Last 12\xa0hours: 0 completed, 0 created"
            )
        ))
        expected_graph_data.insert(0, dict(
            x=5, y=2,
            tooltip=(
                "12\xa0hours ago"
                "<br><strong>2</strong> incomplete jobs"
                "<br>Last 12\xa0hours: 0 completed, 0 created"
            )
        ))

        # One 12-hour interval creates jobs (and drives the average up)
        with mock.patch('django.utils.timezone.now') as mock_now:
            mock_now.return_value = get_time_ago(hours=6)
            for _ in range(15):
                self.job(status=Job.Status.PENDING)
        expected_graph_data.insert(0, dict(
            x=6, y=17,
            tooltip=(
                "Now"
                "<br><strong>17</strong> incomplete jobs"
                "<br>Last 12\xa0hours: 0 completed, 15 created"
            )
        ))

        response = self.get_response()
        graph_data = response.context['incomplete_count_graph_data']
        for i in range(6+1):
            self.assertDictEqual(
                graph_data[i],
                expected_graph_data[i],
            )

        response_soup = BeautifulSoup(response.content, 'html.parser')
        detail_list_soup = response_soup.select('ul.detail_list')[0]
        self.assertInHTML(
            "Now: 17",
            str(detail_list_soup))
        self.assertInHTML(
            # (3+3+4+2+2+2+17) / 7 = 4.71; round to nearest
            "Rough average over the past 3 days: 5",
            str(detail_list_soup))

    def test_incomplete_count_no_jobs(self):
        # Jobs completed before the timeline don't count.
        self.job(
            status=Job.Status.SUCCESS,
            created_time_ago=timedelta(days=3, hours=4),
            modified_time_ago=timedelta(days=3, hours=2),
        )
        self.job(
            status=Job.Status.FAILURE,
            created_time_ago=timedelta(days=3, hours=4),
            modified_time_ago=timedelta(days=3, hours=2),
        )
        # Jobs started and completed within the same interval don't contribute
        # to any incomplete job counts, but they do count toward the created
        # and completed counts in the tooltip.
        self.job(status=Job.Status.SUCCESS)
        self.job(status=Job.Status.FAILURE)

        expected_graph_data = [
            dict(
                x=6, y=0,
                tooltip=(
                    "Now"
                    "<br><strong>0</strong> incomplete jobs"
                    "<br>Last 12\xa0hours: 2 completed, 2 created"
                )
            ),
            dict(
                x=5, y=0,
                tooltip=(
                    "12\xa0hours ago"
                    "<br><strong>0</strong> incomplete jobs"
                    "<br>Last 12\xa0hours: 0 completed, 0 created"
                )
            ),
            dict(
                x=4, y=0,
                tooltip=(
                    "1\xa0day ago"
                    "<br><strong>0</strong> incomplete jobs"
                    "<br>Last 12\xa0hours: 0 completed, 0 created"
                )
            ),
            dict(
                x=3, y=0,
                tooltip=(
                    "1\xa0day, 12\xa0hours ago"
                    "<br><strong>0</strong> incomplete jobs"
                    "<br>Last 12\xa0hours: 0 completed, 0 created"
                )
            ),
            dict(
                x=2, y=0,
                tooltip=(
                    "2\xa0days ago"
                    "<br><strong>0</strong> incomplete jobs"
                    "<br>Last 12\xa0hours: 0 completed, 0 created"
                )
            ),
            dict(
                x=1, y=0,
                tooltip=(
                    "2\xa0days, 12\xa0hours ago"
                    "<br><strong>0</strong> incomplete jobs"
                    "<br>Last 12\xa0hours: 0 completed, 0 created"
                )
            ),
            dict(
                x=0, y=0,
                tooltip=(
                    "3\xa0days ago"
                    "<br><strong>0</strong> incomplete jobs"
                )
            ),
        ]

        response = self.get_response()
        graph_data = response.context['incomplete_count_graph_data']
        for i in range(6+1):
            self.assertDictEqual(
                graph_data[i],
                expected_graph_data[i],
            )

        response_soup = BeautifulSoup(response.content, 'html.parser')
        detail_list_soup = response_soup.select('ul.detail_list')[0]
        self.assertInHTML(
            "Now: 0",
            str(detail_list_soup))
        self.assertInHTML(
            "Rough average over the past 3 days: 0",
            str(detail_list_soup))

    def test_recency_threshold_default(self):
        # The 30-second adjustments below provide some leeway for the time
        # string assertions, given that timesince() truncates to the minute
        # instead of rounding.

        # This should be the only job accounted for in wait times.
        self.job(
            status=Job.Status.SUCCESS,
            scheduled_time_ago=timedelta(days=3, minutes=3, seconds=30),
            started_time_ago=timedelta(days=2, hours=23, minutes=50),
            modified_time_ago=timedelta(days=3, minutes=3),
        )
        # This should be the only job accounted for in total times.
        self.job(
            status=Job.Status.SUCCESS,
            scheduled_time_ago=timedelta(days=3, minutes=29, seconds=30),
            modified_time_ago=timedelta(days=2, hours=23, minutes=50),
        )
        # This should be in neither.
        self.job(
            status=Job.Status.SUCCESS,
            scheduled_time_ago=timedelta(days=3, hours=5),
            started_time_ago=timedelta(days=3, hours=2),
            modified_time_ago=timedelta(days=3, hours=1),
        )

        detail_list_soup = self.get_detail_list_soup()
        self.assertInHTML(
            "Jobs in the past 3 days - 10th to 90th percentile times:",
            str(detail_list_soup))
        self.assertInHTML(
            "Time waited before starting: 13\xa0minutes ~ 13\xa0minutes",
            str(detail_list_soup))
        self.assertInHTML(
            "Total time: 39\xa0minutes ~ 39\xa0minutes",
            str(detail_list_soup))

    def test_recency_threshold_hour(self):
        # This should be the only job accounted for in wait times.
        self.job(
            status=Job.Status.SUCCESS,
            scheduled_time_ago=timedelta(hours=1, minutes=3, seconds=30),
            started_time_ago=timedelta(minutes=50),
            modified_time_ago=timedelta(hours=1, minutes=3),
        )
        # This should be the only job accounted for in total times.
        self.job(
            status=Job.Status.SUCCESS,
            scheduled_time_ago=timedelta(hours=1, minutes=29, seconds=30),
            modified_time_ago=timedelta(minutes=50),
        )
        # This should be in neither.
        self.job(
            status=Job.Status.SUCCESS,
            scheduled_time_ago=timedelta(hours=1, minutes=5),
            started_time_ago=timedelta(hours=1, minutes=2),
            modified_time_ago=timedelta(hours=1, minutes=1),
        )

        detail_list_soup = self.get_detail_list_soup(
            data=dict(recency_threshold='1'))
        self.assertInHTML(
            "Jobs in the past hour - 10th to 90th percentile times:",
            str(detail_list_soup))
        self.assertInHTML(
            "Time waited before starting: 13\xa0minutes ~ 13\xa0minutes",
            str(detail_list_soup))
        self.assertInHTML(
            "Total time: 39\xa0minutes ~ 39\xa0minutes",
            str(detail_list_soup))

    def test_recency_threshold_30_days(self):
        # This should be the only job accounted for in wait times.
        self.job(
            status=Job.Status.SUCCESS,
            scheduled_time_ago=timedelta(days=30, minutes=3, seconds=30),
            started_time_ago=timedelta(days=29, hours=23, minutes=50),
            modified_time_ago=timedelta(days=30, minutes=3),
        )
        # This should be the only job accounted for in total times.
        self.job(
            status=Job.Status.SUCCESS,
            scheduled_time_ago=timedelta(days=30, minutes=29, seconds=30),
            modified_time_ago=timedelta(days=29, hours=23, minutes=50),
        )
        # This should be in neither.
        self.job(
            status=Job.Status.SUCCESS,
            scheduled_time_ago=timedelta(days=30, hours=5),
            started_time_ago=timedelta(days=30, hours=2),
            modified_time_ago=timedelta(days=30, hours=1),
        )

        detail_list_soup = self.get_detail_list_soup(
            data=dict(recency_threshold='720'))
        self.assertInHTML(
            "Jobs in the past 30 days - 10th to 90th percentile times:",
            str(detail_list_soup))
        self.assertInHTML(
            "Time waited before starting: 13\xa0minutes ~ 13\xa0minutes",
            str(detail_list_soup))
        self.assertInHTML(
            "Total time: 39\xa0minutes ~ 39\xa0minutes",
            str(detail_list_soup))

    def test_recency_threshold_invalid(self):
        # Should use the default threshold.
        detail_list_soup = self.get_detail_list_soup(
            data=dict(recency_threshold='some_unrecognized_value'))
        self.assertInHTML(
            "Jobs in the past 3 days - 10th to 90th percentile times:",
            str(detail_list_soup))

    def test_exclude_realtime_jobs(self):
        # Expect realtime jobs to be recognized by job name.
        # These two are realtime.
        self.job(
            status=Job.Status.SUCCESS,
            job_name='generate_thumbnail',
            scheduled_time_ago=timedelta(minutes=11),
            started_time_ago=timedelta(minutes=10),
        )
        self.job(
            status=Job.Status.SUCCESS,
            job_name='generate_patch',
            scheduled_time_ago=timedelta(minutes=11),
            started_time_ago=timedelta(minutes=10),
        )
        # This isn't realtime. This should be the only job accounted for
        # in wait times.
        self.job(
            status=Job.Status.SUCCESS,
            job_name='update_label_details',
            scheduled_time_ago=timedelta(minutes=15, seconds=30),
            started_time_ago=timedelta(minutes=10),
        )

        detail_list_soup = self.get_detail_list_soup()
        self.assertInHTML(
            "Time waited before starting: 5\xa0minutes ~ 5\xa0minutes",
            str(detail_list_soup))

    def test_pending_wait_time(self):
        def f1(_num):
            self.job(
                status=Job.Status.PENDING,
                scheduled_time_ago=timedelta(minutes=5),
            )
        def f2(_num):
            self.job(
                status=Job.Status.PENDING,
                scheduled_time_ago=timedelta(hours=5, minutes=15),
            )
        def f3(_num):
            self.job(
                status=Job.Status.PENDING,
                scheduled_time_ago=timedelta(hours=5, minutes=20),
            )

        scrambled_run([f1, f2, f3])

        detail_list_soup = self.get_content_soup(user=self.superuser)
        self.assertInHTML(
            "Current highest pending wait time: 5\xa0hours, 20\xa0minutes",
            str(detail_list_soup))

    def test_pending_wait_time_no_jobs(self):
        # Non-pending jobs aren't considered here.
        self.job(
            status=Job.Status.IN_PROGRESS,
            scheduled_time_ago=timedelta(days=2),
        )
        self.job(
            status=Job.Status.SUCCESS,
            scheduled_time_ago=timedelta(days=2),
        )
        self.job(
            status=Job.Status.FAILURE,
            scheduled_time_ago=timedelta(days=2),
        )

        content_soup = self.get_content_soup(user=self.superuser)
        self.assertInHTML(
            "Current highest pending wait time: 0\xa0minutes",
            str(content_soup))

    def test_pending_wait_time_not_admin(self):
        response = self.get_response(user=self.superuser)
        self.assertContains(response, "Current highest pending wait time")

        response = self.get_response()
        self.assertNotContains(response, "Current highest pending wait time")
