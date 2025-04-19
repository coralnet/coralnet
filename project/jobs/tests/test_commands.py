from datetime import datetime, timedelta, timezone
import json

from django.conf import settings
from django.urls import reverse

from api_core.models import ApiJob
from export.tests.utils import ExportTestMixin
from lib.tests.utils import ManagementCommandTest
from vision_backend_api.tests.utils import DeployTestMixin
from ..models import Job
from .utils import fabricate_job


class AbortJobTest(ManagementCommandTest):

    def test_abort(self):
        job_1 = Job(job_name='1')
        job_1.save()
        job_2 = Job(job_name='2')
        job_2.save()
        job_3 = Job(job_name='3')
        job_3.save()

        stdout_text, _ = self.call_command_and_get_output(
            'jobs', 'abort_job', args=[job_1.pk, job_3.pk])
        self.assertIn(
            f"The 2 specified Job(s) have been aborted.",
            stdout_text)

        job_details = {
            (job.job_name, job.status, job.result_message)
            for job in Job.objects.all()
        }
        self.assertSetEqual(
            job_details,
            {
                ('1', Job.Status.FAILURE, "Aborted manually"),
                ('2', Job.Status.PENDING, ""),
                ('3', Job.Status.FAILURE, "Aborted manually"),
            },
            "Only jobs 1 and 3 should have been aborted",
        )


class ExpediteJobTest(ManagementCommandTest):

    def test_expedite(self):
        # Schedule 3 jobs days into the future. 2 pending, 1 in progress.
        job_1 = fabricate_job(
            name='1', delay=timedelta(days=3))
        job_2 = fabricate_job(
            name='2', delay=timedelta(days=3),
            status=Job.Status.IN_PROGRESS)
        job_3 = fabricate_job(
            name='3', delay=timedelta(days=3))
        original_start_dates = [
            job_1.scheduled_start_date,
            job_2.scheduled_start_date,
            job_3.scheduled_start_date,
        ]

        # Try to expedite each job. Should work for the pending ones only.
        stdout_text, _ = self.call_command_and_get_output(
            'jobs', 'expedite_job', args=[job_1.pk, job_2.pk, job_3.pk])
        self.assertIn(
            f"Job {job_1.pk} has been expedited.", stdout_text)
        self.assertIn(
            f"Job {job_2.pk} isn't pending; no action taken.", stdout_text)
        self.assertIn(
            f"Job {job_3.pk} has been expedited.", stdout_text)

        job_1.refresh_from_db()
        job_2.refresh_from_db()
        job_3.refresh_from_db()
        new_start_dates = [
            job_1.scheduled_start_date,
            job_2.scheduled_start_date,
            job_3.scheduled_start_date,
        ]
        self.assertLess(new_start_dates[0], original_start_dates[0])
        self.assertEqual(new_start_dates[1], original_start_dates[1])
        self.assertLess(new_start_dates[2], original_start_dates[2])


class RecentStatsTest(ManagementCommandTest, DeployTestMixin, ExportTestMixin):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user1 = cls.create_user(username='user1', password='SamplePassword')
        cls.user2 = cls.create_user(username='user2', password='SamplePassword')
        cls.user3 = cls.create_user(username='user3', password='SamplePassword')
        cls.source = cls.create_source(cls.user1)
        labels = cls.create_labels(cls.user1, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user1, cls.source, labels)
        cls.classifier = cls.upload_data_and_train_classifier(
            source=cls.source, user=cls.user1)
        cls.deploy_url = reverse('api:deploy', args=[cls.classifier.pk])
        cls.request_kwargs = {
            user.pk: cls.get_request_kwargs_for_user(
                user.username, 'SamplePassword')
            for user in [cls.user1, cls.user2, cls.user3]
        }

    def fabricate_api_job(
            self, modify_date: datetime,
            status=Job.Status.SUCCESS, user=None, ppi=None):
        # Create actual deploy jobs to ensure all the relevant DB objects
        # are created (ApiJobs, and ApiJobUnits with request_json).
        points_per_image = ppi or 5
        units_per_job = 2
        images = [dict(
            type='image',
            attributes=dict(
                url='URL 1',
                points=[
                    dict(row=10*i, column=10)
                    for i in range(points_per_image)
                ],
            ),
        )] * units_per_job
        data = json.dumps(dict(data=images))

        if user is None:
            user = self.user1
        self.client.force_login(user)
        self.client.post(self.deploy_url, data, **self.request_kwargs[user.pk])
        api_job = ApiJob.objects.latest('pk')

        # Accept naive datetimes as UTC.
        if modify_date.tzinfo is None:
            modify_date = modify_date.replace(tzinfo=timezone.utc)

        # But fake the date values and statuses.
        internal_jobs = Job.objects.filter(apijobunit__parent=api_job)
        internal_jobs.update(
            status=status,
            # This command's api_jobs analysis just looks at modify dates of
            # the jobs.
            # To prove that start date and create date aren't considered,
            # we'll always make these two dates out of the analysis range,
            # i.e. before the year 2000.
            create_date=datetime(
                1999, 12, 28, 0, 0, tzinfo=timezone.utc),
            start_date=datetime(
                1999, 12, 29, 0, 0, tzinfo=timezone.utc),
            # When we use QuerySet.update() instead of Model.save(), the
            # modify date doesn't get auto-updated to the current date,
            # allowing us to set a custom value.
            modify_date=modify_date,
        )

        return api_job

    @staticmethod
    def fabricate_completed_job(**kwargs):
        """
        For turnaround_time tests.
        """
        # Not passing in a name is generally okay for our purposes here,
        # unless there's a concern of avoiding dupe active jobs.
        if 'name' not in kwargs:
            kwargs['name'] = 'extract_features'
        if 'status' not in kwargs:
            kwargs['status'] = Job.Status.SUCCESS

        if 'scheduled_start_date' in kwargs:
            # Accept naive datetimes as UTC.
            if kwargs['scheduled_start_date'].tzinfo is None:
                kwargs['scheduled_start_date'] = (
                    kwargs['scheduled_start_date'].replace(tzinfo=timezone.utc))

        return fabricate_job(**kwargs)

    def assert_output_csv_equal(self, expected_lines):
        filepath = settings.COMMAND_OUTPUT_DIR / 'jobs_recent_stats.csv'
        # newline='' preserves the \r\n newlines of the file instead of
        # converting to \n, which helps with checking the contents.
        with open(filepath, newline='') as f:
            actual_content = f.read()
        self.assert_csv_content_equal(actual_content, expected_lines)

    def test_api_jobs_short_span(self):
        # Test the date extents (before start, after start, before end,
        # after end) and multiple in at least one hour.
        self.fabricate_api_job(modify_date=datetime(1999, 12, 31, 23, 59))
        self.fabricate_api_job(modify_date=datetime(2000, 1, 1, 0, 1))
        self.fabricate_api_job(modify_date=datetime(2000, 1, 5, 23, 1))
        self.fabricate_api_job(modify_date=datetime(2000, 1, 5, 23, 59))
        self.fabricate_api_job(modify_date=datetime(2000, 1, 6, 0, 1))

        stdout_text, _ = self.call_command_and_get_output(
            'jobs', 'jobs_recent_stats',
            args=[
                'api_jobs', '--span_days', '5',
                '--span_end', '2000-01-06T00:00',
            ])

        self.assertEqual(
            stdout_text,
            f"Output:"
            f" {settings.COMMAND_OUTPUT_DIR / 'jobs_recent_stats.csv'}"
            f"\nOutput:"
            f" {settings.COMMAND_OUTPUT_DIR / 'jobs_recent_stats.png'}")
        self.assert_output_csv_equal([
            "hour,user1",
            "2000-01-01 00:xx,2",
            "2000-01-05 23:xx,4",
            "Total,6",
            "Avg points per image,5.000",
        ])

        # TODO: Do assertions on matplotlib image output. Perhaps try just
        #  strict equality pixel by pixel with an 'expected image' fixture
        #  and see how it goes. If the assertion fails, print a message
        #  pointing out the paths of the actual and expected images, so that
        #  they can be compared for debugging.

    def test_api_jobs_long_span(self):
        self.fabricate_api_job(modify_date=datetime(1999, 12, 31, 23, 59))
        self.fabricate_api_job(modify_date=datetime(2000, 1, 1, 0, 1))
        self.fabricate_api_job(modify_date=datetime(2000, 1, 6, 23, 1))
        self.fabricate_api_job(modify_date=datetime(2000, 1, 6, 23, 59))
        self.fabricate_api_job(modify_date=datetime(2000, 1, 7, 0, 1))

        stdout_text, _ = self.call_command_and_get_output(
            'jobs', 'jobs_recent_stats',
            args=[
                'api_jobs', '--span_days', '6',
                '--span_end', '2000-01-07T00:00',
            ])

        self.assert_output_csv_equal([
            "day,user1",
            "2000-01-01 xx:xx,2",
            "2000-01-06 xx:xx,4",
            "Total,6",
            "Avg points per image,5.000",
        ])

    def test_api_jobs_zero_jobs(self):
        """
        This case doesn't get useful output, but it should at least not crash
        with a confusing error.
        """
        stdout_text, _ = self.call_command_and_get_output(
            'jobs', 'jobs_recent_stats', args=['api_jobs'])

        self.assert_output_csv_equal([
            "day",
            "Total",
            "Avg points per image",
        ])

    def test_api_jobs_ignored_job_conditions(self):
        # Don't count non-completed.
        self.fabricate_api_job(
            modify_date=datetime(2000, 1, 1, 0, 1),
            status=Job.Status.PENDING)
        self.fabricate_api_job(
            modify_date=datetime(2000, 1, 2, 0, 1),
            status=Job.Status.IN_PROGRESS)
        # These are completed API jobs and should count.
        self.fabricate_api_job(
            modify_date=datetime(2000, 1, 3, 0, 1),
            status=Job.Status.SUCCESS)
        self.fabricate_api_job(
            modify_date=datetime(2000, 1, 4, 0, 1),
            status=Job.Status.FAILURE)
        # Don't count non-API.
        fabricate_job(
            'extract_features',
            modify_date=datetime(2000, 1, 5, 0, 1),
            status=Job.Status.SUCCESS)
        fabricate_job(
            'update_label_details',
            modify_date=datetime(2000, 1, 6, 0, 1),
            status=Job.Status.SUCCESS)

        stdout_text, _ = self.call_command_and_get_output(
            'jobs', 'jobs_recent_stats',
            args=[
                'api_jobs', '--span_days', '6',
                '--span_end', '2000-01-07T00:00',
            ])

        self.assert_output_csv_equal([
            "day,user1",
            "2000-01-03 xx:xx,2",
            "2000-01-04 xx:xx,2",
            "Total,4",
            "Avg points per image,5.000",
        ])

    def test_api_jobs_users(self):
        self.fabricate_api_job(
            modify_date=datetime(2000, 1, 1, 0, 1), user=self.user1)
        self.fabricate_api_job(
            modify_date=datetime(2000, 1, 3, 0, 1), user=self.user1)
        self.fabricate_api_job(
            modify_date=datetime(2000, 1, 3, 0, 1), user=self.user1)
        self.fabricate_api_job(
            modify_date=datetime(2000, 1, 3, 0, 1), user=self.user1)
        self.fabricate_api_job(
            modify_date=datetime(2000, 1, 2, 0, 1), user=self.user2)
        self.fabricate_api_job(
            modify_date=datetime(2000, 1, 2, 0, 1), user=self.user2)
        self.fabricate_api_job(
            modify_date=datetime(2000, 1, 3, 0, 1), user=self.user2)

        stdout_text, _ = self.call_command_and_get_output(
            'jobs', 'jobs_recent_stats',
            args=[
                'api_jobs', '--span_days', '6',
                '--span_end', '2000-01-07T00:00',
            ])

        # The timespan has days with only user1, days with only user2, days
        # with both, and days with neither.
        self.assert_output_csv_equal([
            "day,user1,user2",
            "2000-01-01 xx:xx,2,0",
            "2000-01-02 xx:xx,0,4",
            "2000-01-03 xx:xx,6,2",
            "Total,8,6",
            "Avg points per image,5.000,5.000",
        ])

    def test_api_jobs_average_points_per_image(self):
        self.fabricate_api_job(
            modify_date=datetime(2000, 1, 1, 0, 1), user=self.user1, ppi=7)
        self.fabricate_api_job(
            modify_date=datetime(2000, 1, 1, 0, 1), user=self.user1, ppi=13)
        self.fabricate_api_job(
            modify_date=datetime(2000, 1, 1, 0, 1), user=self.user2, ppi=5)
        self.fabricate_api_job(
            modify_date=datetime(2000, 1, 1, 0, 1), user=self.user2, ppi=5)
        self.fabricate_api_job(
            modify_date=datetime(2000, 1, 1, 0, 1), user=self.user2, ppi=10)

        stdout_text, _ = self.call_command_and_get_output(
            'jobs', 'jobs_recent_stats',
            args=[
                'api_jobs', '--span_days', '6',
                '--span_end', '2000-01-07T00:00',
            ])
        self.assert_output_csv_equal([
            "day,user1,user2",
            "2000-01-01 xx:xx,4,6",
            "Total,4,6",
            "Avg points per image,10.000,6.667",
        ])

    def test_turnaround_time_short_span(self):
        # Test the modify_date extents (before start, after start, before end,
        # after end) and multiple in at least one hour.
        # scheduled_start_date and modify_date determine the turnaround_time.
        self.fabricate_completed_job(
            modify_date=datetime(1999, 12, 31, 23, 59))
        self.fabricate_completed_job(
            scheduled_start_date=datetime(1999, 12, 31, 23, 51),
            modify_date=datetime(2000, 1, 1, 0, 1))
        self.fabricate_completed_job(
            scheduled_start_date=datetime(2000, 1, 1, 7, 0),
            modify_date=datetime(2000, 1, 1, 7, 6))
        self.fabricate_completed_job(
            scheduled_start_date=datetime(2000, 1, 1, 7, 0),
            modify_date=datetime(2000, 1, 1, 7, 9))
        self.fabricate_completed_job(
            scheduled_start_date=datetime(2000, 1, 1, 23, 50),
            modify_date=datetime(2000, 1, 1, 23, 59))
        self.fabricate_completed_job(
            scheduled_start_date=datetime(2000, 1, 1, 23, 50),
            modify_date=datetime(2000, 1, 2, 0, 1))

        stdout_text, _ = self.call_command_and_get_output(
            'jobs', 'jobs_recent_stats',
            args=[
                'turnaround_time', '--span_days', '1',
                '--span_end', '2000-01-02T00:00',
            ])

        self.assertEqual(
            stdout_text,
            f"Output:"
            f" {settings.COMMAND_OUTPUT_DIR / 'jobs_recent_stats.csv'}"
            f"\nOutput:"
            f" {settings.COMMAND_OUTPUT_DIR / 'jobs_recent_stats.png'}")
        self.assert_output_csv_equal([
            "hour,turnaround_time",
            "2000-01-01 00:xx,10.0",
            # 90th percentile from 6 and 9
            "2000-01-01 07:xx,8.7",
            "2000-01-01 23:xx,9.0",
        ])

    def test_turnaround_time_long_span(self):
        self.fabricate_completed_job(
            modify_date=datetime(1999, 12, 31, 23, 59))
        self.fabricate_completed_job(
            scheduled_start_date=datetime(1999, 12, 31, 23, 51),
            modify_date=datetime(2000, 1, 1, 0, 1))
        self.fabricate_completed_job(
            scheduled_start_date=datetime(2000, 1, 15, 0, 0),
            modify_date=datetime(2000, 1, 15, 0, 19))
        self.fabricate_completed_job(
            scheduled_start_date=datetime(2000, 1, 15, 23, 50),
            modify_date=datetime(2000, 1, 15, 23, 59))
        self.fabricate_completed_job(
            scheduled_start_date=datetime(2000, 1, 15, 23, 50),
            modify_date=datetime(2000, 1, 16, 0, 1))
        stdout_text, _ = self.call_command_and_get_output(
            'jobs', 'jobs_recent_stats',
            args=[
                'turnaround_time', '--span_days', '15',
                '--span_end', '2000-01-16T00:00',
            ])

        self.assert_output_csv_equal([
            "day,turnaround_time",
            "2000-01-01 xx:xx,10.0",
            # 90th percentile from 19 and 9
            "2000-01-15 xx:xx,18.0",
        ])

    def test_turnaround_time_zero_jobs(self):
        stdout_text, _ = self.call_command_and_get_output(
            'jobs', 'jobs_recent_stats',
            args=[
                'turnaround_time', '--span_days', '1',
                '--span_end', '2000-01-02T00:00',
            ])

        self.assert_output_csv_equal([
            "hour,turnaround_time",
        ])

    def test_turnaround_time_ignored_job_conditions(self):
        # Don't count non-completed.
        fabricate_job(
            name='classify_image',
            scheduled_start_date=datetime(2000, 1, 1, 0, 0),
            modify_date=datetime(2000, 1, 1, 0, 1),
            status=Job.Status.PENDING)
        fabricate_job(
            name='extract_features',
            scheduled_start_date=datetime(2000, 1, 2, 0, 0),
            modify_date=datetime(2000, 1, 2, 0, 2),
            status=Job.Status.IN_PROGRESS)
        # These are completed jobs and should count.
        # We'll demonstrate one API and one non-API background job.
        fabricate_job(
            name='classify_image',
            scheduled_start_date=datetime(2000, 1, 3, 0, 0),
            modify_date=datetime(2000, 1, 3, 0, 3),
            status=Job.Status.FAILURE)
        fabricate_job(
            name='extract_features',
            scheduled_start_date=datetime(2000, 1, 4, 0, 0),
            modify_date=datetime(2000, 1, 4, 0, 4),
            status=Job.Status.SUCCESS)
        # Realtime jobs, which have no scheduled start date, do not count.
        fabricate_job(
            name='generate_patch',
            modify_date=datetime(2000, 1, 5, 0, 5),
            status=Job.Status.SUCCESS)

        stdout_text, _ = self.call_command_and_get_output(
            'jobs', 'jobs_recent_stats',
            args=[
                'turnaround_time', '--span_days', '6',
                '--span_end', '2000-01-07T00:00',
            ])

        self.assert_output_csv_equal([
            "day,turnaround_time",
            "2000-01-03 xx:xx,3.0",
            "2000-01-04 xx:xx,4.0",
        ])

    def test_default_span_args(self):
        """
        Default args are current date and 30 days.
        """
        now = datetime.now(tz=timezone.utc)
        five_minutes_ago = now - timedelta(minutes=5)
        # These two datetimes are guaranteed to land on different calendar
        # days regardless of DST. First datetime is within the timespan,
        # second datetime is not.
        twenty_nine_days_11h_ago = now - timedelta(days=29, hours=11)
        thirty_days_13h_ago = now - timedelta(days=30, hours=13)
        self.fabricate_api_job(modify_date=five_minutes_ago)
        self.fabricate_api_job(modify_date=twenty_nine_days_11h_ago)
        self.fabricate_api_job(modify_date=twenty_nine_days_11h_ago)
        self.fabricate_api_job(modify_date=thirty_days_13h_ago)
        self.fabricate_api_job(modify_date=thirty_days_13h_ago)
        self.fabricate_api_job(modify_date=thirty_days_13h_ago)

        stdout_text, _ = self.call_command_and_get_output(
            'jobs', 'jobs_recent_stats', args=['api_jobs'])

        self.assert_output_csv_equal([
            "day,user1",
            f"{twenty_nine_days_11h_ago.strftime('%Y-%m-%d')} xx:xx,4",
            f"{five_minutes_ago.strftime('%Y-%m-%d')} xx:xx,2",
            "Total,6",
            "Avg points per image,5.000",
        ])

    def test_unsupported_subject(self):
        with self.assertRaises(ValueError) as cm:
            stdout_text, _ = self.call_command_and_get_output(
                'jobs', 'jobs_recent_stats', args=['job_market'])
        self.assertEqual(
            str(cm.exception), "Unsupported subject: job_market")
