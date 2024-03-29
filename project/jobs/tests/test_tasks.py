from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.test.utils import override_settings
from django.utils import timezone

from api_core.models import ApiJob, ApiJobUnit
from config.constants import SpacerJobSpec
from lib.tests.utils import BaseTest
from vision_backend.models import BatchJob
from ..models import Job
from ..tasks import (
    clean_up_old_jobs,
    schedule_periodic_jobs,
    report_stuck_jobs,
    run_scheduled_jobs,
)
from ..utils import job_runner
from .utils import fabricate_job


def call_run_scheduled_jobs():
    run_scheduled_jobs()
    return []


@job_runner()
def return_arg_test(arg):
    return str(arg)


class RunScheduledJobsTest(BaseTest):

    @staticmethod
    def run_scheduled_jobs_and_get_result():
        run_scheduled_jobs()

        job = Job.objects.filter(job_name='run_scheduled_jobs').latest('pk')
        return job.result_message

    def test_result_message(self):
        self.assertEqual(
            self.run_scheduled_jobs_and_get_result(),
            "Ran 0 jobs")

        name = 'return_arg_test'

        job_1 = fabricate_job(name, 1)
        self.assertEqual(
            self.run_scheduled_jobs_and_get_result(),
            f"Ran 1 job(s):\n{job_1.pk}: {name} / 1")

        job_2 = fabricate_job(name, 2)
        job_3 = fabricate_job(name, 3)
        job_4 = fabricate_job(name, 4)
        self.assertEqual(
            self.run_scheduled_jobs_and_get_result(),
            f"Ran 3 job(s):\n{job_2.pk}: {name} / 2"
            f"\n{job_3.pk}: {name} / 3"
            f"\n{job_4.pk}: {name} / 4")

        job_5 = fabricate_job(name, 5)
        job_6 = fabricate_job(name, 6)
        job_7 = fabricate_job(name, 7)
        fabricate_job(name, 8)
        self.assertEqual(
            self.run_scheduled_jobs_and_get_result(),
            f"Ran 4 jobs, including:\n{job_5.pk}: {name} / 5"
            f"\n{job_6.pk}: {name} / 6"
            f"\n{job_7.pk}: {name} / 7")

    @override_settings(JOB_MAX_MINUTES=-1)
    def test_time_out(self):
        for i in range(12):
            fabricate_job('return_arg_test', i)

        result_message = self.run_scheduled_jobs_and_get_result()
        self.assertTrue(
            result_message.startswith("Ran 10 jobs (timed out), including:"))

        result_message = self.run_scheduled_jobs_and_get_result()
        self.assertTrue(
            result_message.startswith("Ran 2 job(s):"))

    def test_no_multiple_runs(self):
        """
        Should block multiple existing runs of this task. That way, no job
        looped through in this task can get started in huey multiple times.
        """
        # Mock a function called by the task, and make that function
        # attempt to run the task recursively.
        with mock.patch(
            'jobs.tasks.get_scheduled_jobs', call_run_scheduled_jobs
        ):
            run_scheduled_jobs()

        self.assertEqual(
            Job.objects.filter(job_name='run_scheduled_jobs').count(), 1,
            "Should not have accepted the second run")

    def test_unrecognized_job_name(self):
        job = fabricate_job('return_arg_test', 1)
        job_2 = fabricate_job('test_2', 1)

        result_message = self.run_scheduled_jobs_and_get_result()
        self.assertRegex(
            result_message, r"Ran 1 job\(s\):\n\d+: return_arg_test / 1")

        job.refresh_from_db()
        self.assertEqual(job.status, Job.Status.SUCCESS)
        job_2.refresh_from_db()
        self.assertEqual(job_2.status, Job.Status.FAILURE)
        self.assertEqual(job_2.result_message, "Unrecognized job name")


@override_settings(JOB_MAX_DAYS=30)
class CleanupTaskTest(BaseTest):

    @staticmethod
    def run_and_get_result():
        job = fabricate_job('clean_up_old_jobs')
        clean_up_old_jobs()
        job.refresh_from_db()
        return job.result_message

    def test_zero_jobs_message(self):
        """
        Check the result message when there are no jobs to clean up.
        """
        # Too new to be cleaned up.
        fabricate_job('new')

        self.assertEqual(
            self.run_and_get_result(), "No old jobs to clean up")

    def test_date_based_selection(self):
        """
        Jobs should be selected for cleanup based on date.
        """
        # More than one job too new to be cleaned up.
        fabricate_job('new')
        fabricate_job(
            '29 days ago',
            modify_date=timezone.now() - timedelta(days=29))

        # More than one job old enough to be cleaned up.
        fabricate_job(
            '31 days ago',
            modify_date=timezone.now() - timedelta(days=31))
        fabricate_job(
            '32 days ago',
            modify_date=timezone.now() - timedelta(days=32))

        self.assertEqual(
            self.run_and_get_result(), "Cleaned up 2 old job(s)")

        self.assertTrue(
            Job.objects.filter(job_name='new').exists(),
            "Shouldn't clean up new job")
        self.assertTrue(
            Job.objects.filter(job_name='29 days ago').exists(),
            "Shouldn't clean up 29 day old job")
        self.assertFalse(
            Job.objects.filter(job_name='31 days ago').exists(),
            "Should clean up 31 day old job")
        self.assertFalse(
            Job.objects.filter(job_name='32 days ago').exists(),
            "Should clean up 32 day old job")

    def test_persist_based_selection(self):
        """
        Jobs with the persist flag set should not be cleaned up.
        """
        fabricate_job(
            'Persist True',
            persist=True,
            modify_date=timezone.now() - timedelta(days=31),
        )
        fabricate_job(
            'Persist False',
            persist=False,
            modify_date=timezone.now() - timedelta(days=31),
        )

        self.assertEqual(
            self.run_and_get_result(), "Cleaned up 1 old job(s)")

        self.assertTrue(
            Job.objects.filter(job_name='Persist True').exists(),
            "Shouldn't clean up Persist True")
        self.assertFalse(
            Job.objects.filter(job_name='Persist False').exists(),
            "Should clean up Persist False")

    def test_unit_presence_based_selection(self):
        """
        Jobs associated with an existing ApiJobUnit should not be
        cleaned up.
        """
        user = User(username='some_user')
        user.save()
        api_job = ApiJob(type='', user=user)
        api_job.save()

        job = fabricate_job('unit 1')
        ApiJobUnit(
            parent=api_job, internal_job=job,
            order_in_parent=1, request_json=[]).save()

        fabricate_job('no unit')

        job = fabricate_job('unit 2')
        ApiJobUnit(
            parent=api_job, internal_job=job,
            order_in_parent=2, request_json=[]).save()

        # Make all jobs old enough to be cleaned up
        Job.objects.update(
            modify_date=timezone.now() - timedelta(days=32))

        self.assertEqual(
            self.run_and_get_result(), "Cleaned up 1 old job(s)")

        self.assertTrue(
            Job.objects.filter(job_name='unit 1').exists(),
            "Shouldn't clean up unit 1's job")
        self.assertTrue(
            Job.objects.filter(job_name='unit 2').exists(),
            "Shouldn't clean up unit 2's job")
        self.assertFalse(
            Job.objects.filter(job_name='no unit').exists(),
            "Should clean up no-unit job")


class ReportStuckJobsTest(BaseTest):
    """
    Test the report_stuck_jobs task.
    """
    @staticmethod
    def run_and_get_result():
        job = fabricate_job('report_stuck_jobs')
        report_stuck_jobs()
        job.refresh_from_db()
        return job.result_message

    @staticmethod
    def create_job(
        name, arg, modify_date,
        status=Job.Status.IN_PROGRESS,
        batch_spec_level=None,
    ):
        job = fabricate_job(name, arg, modify_date=modify_date, status=status)

        if batch_spec_level:
            batch_job = BatchJob(internal_job=job, spec_level=batch_spec_level)
            batch_job.save()

        return job

    def test_zero_jobs_message(self):
        """
        Check the result message when there are no stuck jobs to report.
        """
        # Too new to be cleaned up.
        fabricate_job('new')

        self.assertEqual(
            self.run_and_get_result(), "No stuck jobs detected")

    def test_job_selection_by_date(self):
        """
        Only warn about jobs between 3 and 4 days old, and warn once per job.
        """
        self.create_job(
            '1', '2d 23h ago',
            timezone.now() - timedelta(days=2, hours=23))

        job_2 = self.create_job(
            '2', '3d 1h ago',
            timezone.now() - timedelta(days=3, hours=1))

        job_3 = self.create_job(
            '3', '3d 23h ago',
            timezone.now() - timedelta(days=3, hours=23))

        self.create_job(
            '4', '4d 1h ago',
            timezone.now() - timedelta(days=4, hours=1))

        self.assertEqual(
            self.run_and_get_result(), "2 job(s) haven't progressed in a while")

        self.assertEqual(len(mail.outbox), 1)
        sent_email = mail.outbox[0]

        self.assertEqual(
            "[CoralNet] 2 job(s) haven't progressed in a while",
            sent_email.subject)
        self.assertEqual(
            "The following job(s) haven't progressed in a while:"
            "\n"
            f"\n3 / 3d 23h ago - since {job_3.modify_date}"
            f"\n2 / 3d 1h ago - since {job_2.modify_date}",
            sent_email.body)

    def test_job_selection_by_high_spec(self):
        """
        For jobs defined as high-spec for Batch, the range's 8-9 days, not 3-4.
        """
        self.create_job(
            'Non-Batch 1', '7d 23h',
            timezone.now() - timedelta(days=7, hours=23))
        self.create_job(
            'Non-Batch 2', '8d 1h',
            timezone.now() - timedelta(days=8, hours=1))

        self.create_job(
            'Batch MEDIUM 1', '7d 23h',
            timezone.now() - timedelta(days=7, hours=23),
            batch_spec_level=SpacerJobSpec.MEDIUM)
        self.create_job(
            'Batch MEDIUM 2', '8d 1h',
            timezone.now() - timedelta(days=8, hours=1),
            batch_spec_level=SpacerJobSpec.MEDIUM)

        self.create_job(
            'Batch HIGH 1', '7d 23h',
            timezone.now() - timedelta(days=7, hours=23),
            batch_spec_level=SpacerJobSpec.HIGH)
        bh2 = self.create_job(
            'Batch HIGH 2', '8d 1h',
            timezone.now() - timedelta(days=8, hours=1),
            batch_spec_level=SpacerJobSpec.HIGH)

        self.assertEqual(
            self.run_and_get_result(), "1 job(s) haven't progressed in a while")

        self.assertEqual(len(mail.outbox), 1)
        sent_email = mail.outbox[0]

        self.assertEqual(
            "[CoralNet] 1 job(s) haven't progressed in a while",
            sent_email.subject)
        self.assertEqual(
            "The following job(s) haven't progressed in a while:"
            "\n"
            f"\nBatch HIGH 2 / 8d 1h - since {bh2.modify_date}",
            sent_email.body)

    def test_job_selection_by_status(self):
        """
        Only warn about in-progress jobs.
        """
        d3h1 = timezone.now() - timedelta(days=3, hours=1)

        self.create_job('1', 'PENDING', d3h1, status=Job.Status.PENDING)
        self.create_job('2', 'SUCCESS', d3h1, status=Job.Status.SUCCESS)
        job_3 = self.create_job(
            '3', 'IN_PROGRESS', d3h1, status=Job.Status.IN_PROGRESS)
        self.create_job('4', 'FAILURE', d3h1, status=Job.Status.FAILURE)

        self.assertEqual(
            self.run_and_get_result(), "1 job(s) haven't progressed in a while")

        self.assertEqual(len(mail.outbox), 1)
        sent_email = mail.outbox[0]

        self.assertEqual(
            "[CoralNet] 1 job(s) haven't progressed in a while",
            sent_email.subject)
        self.assertEqual(
            "The following job(s) haven't progressed in a while:"
            "\n"
            f"\n3 / IN_PROGRESS - since {job_3.modify_date}",
            sent_email.body)


class SchedulePeriodicJobsTest(BaseTest):
    """
    Test the schedule_periodic_jobs task.
    """
    @staticmethod
    def run_and_get_result():
        schedule_periodic_jobs()
        job = Job.objects.filter(
            job_name='schedule_periodic_jobs').latest('pk')
        return job.result_message

    def test_zero_jobs_message(self):
        """
        Check the result message when there are no periodic jobs to schedule.
        """
        # Schedule everything first
        schedule_periodic_jobs()
        # Then scheduling again should do nothing
        self.assertEqual(
            self.run_and_get_result(),
            "All periodic jobs are already scheduled")

    def test_schedule_all_periodic_jobs(self):

        def test_periodics():
            """
            By patching get_periodic_job_schedules() with this, we have these
            names available as periodic jobs to schedule.
            """
            return dict(
                periodic1=(5*60, 0),
                periodic2=(5*60, 0),
                periodic3=(5*60, 0),
            )

        with mock.patch(
            'jobs.tasks.get_periodic_job_schedules', test_periodics
        ):
            self.assertEqual(
                self.run_and_get_result(), "Scheduled 3 periodic job(s)")

        # If these lines don't get errors, then the expected
        # scheduled jobs exist
        Job.objects.get(job_name='periodic1', status=Job.Status.PENDING)
        Job.objects.get(job_name='periodic2', status=Job.Status.PENDING)
        Job.objects.get(job_name='periodic3', status=Job.Status.PENDING)
