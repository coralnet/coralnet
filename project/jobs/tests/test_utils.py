from datetime import datetime, timedelta, timezone
import re
from unittest import mock

from django.test.utils import override_settings

from errorlogs.tests.utils import ErrorReportTestMixin
from lib.tests.utils import BaseTest, EmailAssertionsMixin
from ..exceptions import JobError
from ..models import Job
from ..utils import (
    bulk_create_jobs,
    finish_job,
    full_job,
    job_runner,
    job_starter,
    schedule_job,
)
from .utils import fabricate_job


class ScheduleJobTest(BaseTest, EmailAssertionsMixin, ErrorReportTestMixin):

    def test_when_already_pending(self):
        fabricate_job('name', 'arg')
        job, created = schedule_job('name', 'arg')

        self.assertFalse(
            created, "Should not have created a second job")
        self.assertEqual(
            Job.objects.all().count(),
            1,
            "Should only have one job")

    def test_when_already_in_progress(self):
        fabricate_job('name', 'arg', status=Job.Status.IN_PROGRESS)
        job, created = schedule_job('name', 'arg')

        self.assertFalse(
            created, "Should not have created a second job")
        self.assertEqual(
            Job.objects.all().count(),
            1,
            "Should only have one job")

    def test_when_previously_done(self):
        fabricate_job('name', 'arg', status=Job.Status.SUCCESS)
        schedule_job('name', 'arg')

        self.assertEqual(
            Job.objects.all().count(),
            2,
            "Should have created the second job")

    def test_start_date_expedited(self):
        """
        Test a pending job's scheduled start date getting expedited by a
        subsequent schedule_job() call.
        """
        job, _ = schedule_job('name', 'arg', delay=timedelta(hours=1))
        original_start_date = job.scheduled_start_date

        schedule_job('name', 'arg', delay=timedelta(hours=5))
        job.refresh_from_db()
        self.assertEqual(
            job.scheduled_start_date, original_start_date,
            msg="Start date shouldn't be updated when requesting a later date"
        )

        schedule_job('name', 'arg', delay=timedelta(seconds=30))
        job.refresh_from_db()
        self.assertLess(
            job.scheduled_start_date, original_start_date,
            msg="Start date should be updated when requesting an earlier date"
        )

    def test_attempt_number_increment(self):
        fabricate_job('name', 'arg', status=Job.Status.FAILURE)
        job, _ = schedule_job('name', 'arg')

        self.assertEqual(
            job.attempt_number,
            2,
            "Should have attempt number of 2")

    def test_attempt_number_non_increment(self):
        fabricate_job('name', 'arg', status=Job.Status.SUCCESS)
        job, _ = schedule_job('name', 'arg')

        self.assertEqual(
            job.attempt_number,
            1,
            "Shouldn't increment if last completed attempt succeeded")

    def test_attempt_number_increment_among_other_jobs(self):
        fabricate_job('name', 'arg', status=Job.Status.FAILURE)
        fabricate_job('other', 'arg', status=Job.Status.SUCCESS)

        job, _ = schedule_job('name', 'arg')
        self.assertEqual(
            job.attempt_number,
            2,
            "Should increment, ignoring the different-named job"
            " that succeeded")

        job.status = Job.Status.FAILURE
        job.save()
        fabricate_job('name', 'arg2', status=Job.Status.FAILURE)
        fabricate_job('name', 'arg3', status=Job.Status.FAILURE)

        job, _ = schedule_job('name', 'arg')
        self.assertEqual(
            job.attempt_number,
            3,
            "Should increment from 2 to 3, ignoring the different-arg jobs")

    def test_repeated_failure(self):
        # 5 fails in a row
        for _ in range(5):
            job, _ = schedule_job('name', 'arg')
            finish_job(job, success=False, result_message="An error")
            self.assert_no_email()

        # Do the same job again
        job, _ = schedule_job('name', 'arg')
        self.assert_latest_email(
            "Job has been failing repeatedly: name / arg, attempt 5",
            ["Error info:\n\nAn error"],
        )
        self.assertAlmostEqual(
            datetime.now(timezone.utc) + timedelta(days=3),
            job.scheduled_start_date,
            delta=timedelta(minutes=10),
            msg="Latest job should be pushed back to 3 days in the future",
        )

        # And again
        finish_job(job, success=False, result_message="An error")
        schedule_job('name', 'arg')
        self.assert_latest_email(
            "Job has been failing repeatedly: name / arg, attempt 6",
            ["Error info:\n\nAn error"],
        )

    def test_repeated_failure_longer_delay(self):
        # 5 fails in a row
        for _ in range(5):
            job, _ = schedule_job('name', 'arg')
            finish_job(job, success=False, result_message="An error")
            self.assert_no_email()

        # Schedule the same job again, with longer delay
        job, _ = schedule_job('name', 'arg', delay=timedelta(days=5))
        self.assert_latest_email(
            "Job has been failing repeatedly: name / arg, attempt 5",
            ["Error info:\n\nAn error"],
        )
        self.assertAlmostEqual(
            datetime.now(timezone.utc) + timedelta(days=5),
            job.scheduled_start_date,
            delta=timedelta(minutes=10),
            msg=(
                "Latest job should still be 5 days in the future;"
                " 3 days is just a lower bound"),
        )

    def test_repeated_failure_no_expediting(self):
        # 5 fails in a row
        for _ in range(5):
            job, _ = schedule_job('name', 'arg', delay=timedelta(days=5))

            # Call again with shorter delay
            schedule_job('name', 'arg', delay=timedelta(days=2))
            job.refresh_from_db()
            self.assertAlmostEqual(
                datetime.now(timezone.utc) + timedelta(days=2),
                job.scheduled_start_date,
                delta=timedelta(minutes=10),
                msg="Start date should have been expedited",
            )

            schedule_job('name', 'arg')
            finish_job(job, success=False, result_message="An error")

        # Schedule the same job again
        job, _ = schedule_job('name', 'arg', delay=timedelta(days=5))

        # Call again with shorter delay
        schedule_job('name', 'arg', delay=timedelta(days=2))
        job.refresh_from_db()
        self.assertAlmostEqual(
            datetime.now(timezone.utc) + timedelta(days=5),
            job.scheduled_start_date,
            delta=timedelta(minutes=10),
            msg="Start date shouldn't have been expedited",
        )


class BulkCreateJobsTest(BaseTest):

    def test(self):
        jobs = bulk_create_jobs(
            'name',
            [
                ['arg1a', 'arg2a'],
                ['arg1b', 'arg2b'],
                ['arg1c', 'arg2c'],
            ],
        )

        for job in jobs:
            self.assertEqual(job.status, Job.Status.PENDING)
            self.assertIsNotNone(job.scheduled_start_date)
        self.assertEqual(len(jobs), 3)


class FinishJobTest(BaseTest):

    @override_settings(ENABLE_PERIODIC_JOBS=True)
    def test_periodic_job_schedules_another_run(self):
        """
        Test a periodic job getting another instance of it scheduled after the
        current instance finishes.
        """
        def test_periodic():
            """
            By patching get_periodic_job_schedules() with this, we have
            my_job registered as a periodic job.
            """
            return dict(
                my_job=(5*60, 0),
            )

        with mock.patch(
            'jobs.utils.get_periodic_job_schedules', test_periodic
        ):
            job, _ = schedule_job('my_job')
            finish_job(job, success=True)

        job.refresh_from_db()
        self.assertEqual(job.status, Job.Status.SUCCESS)

        # Another PENDING job should exist now
        Job.objects.get(job_name='my_job', status=Job.Status.PENDING)


@full_job()
def full_job_example(arg1):
    if arg1 == 'job_error':
        raise JobError("A JobError")
    if arg1 == 'other_error':
        raise ValueError("A ValueError")
    return "Comment about result"


@job_runner()
def job_runner_example(arg1):
    if arg1 == 'job_error':
        raise JobError("A JobError")
    if arg1 == 'other_error':
        raise ValueError("A ValueError")
    return "Comment about result"


@job_starter()
def job_starter_example(arg1, job_id):
    if arg1 == 'job_error':
        raise JobError(f"A JobError (ID: {job_id})")
    if arg1 == 'other_error':
        raise ValueError(f"A ValueError (ID: {job_id})")


class JobDecoratorTest(BaseTest, ErrorReportTestMixin, EmailAssertionsMixin):

    def test_full_completion(self):
        full_job_example('some_arg')
        job = Job.objects.latest('pk')

        self.assertEqual(job.job_name, 'full_job_example')
        self.assertEqual(job.arg_identifier, 'some_arg')
        self.assertEqual(job.status, Job.Status.SUCCESS)
        self.assertEqual(job.result_message, "Comment about result")

    def test_full_job_error(self):
        full_job_example('job_error')
        job = Job.objects.latest('pk')

        self.assertEqual(job.status, Job.Status.FAILURE)
        self.assertEqual(job.result_message, "A JobError")
        self.assert_no_error_log_saved()
        self.assert_no_email()

    def test_full_other_error(self):
        full_job_example('other_error')
        job = Job.objects.latest('pk')

        self.assertEqual(job.status, Job.Status.FAILURE)
        self.assertEqual(job.result_message, "ValueError: A ValueError")

        self.assert_error_log_saved(
            "ValueError",
            "A ValueError",
        )
        self.assert_latest_email(
            "Error in job: full_job_example",
            ["ValueError: A ValueError"],
        )

    def test_runner_completion(self):
        job, _ = schedule_job('job_runner_example', 'some_arg')

        job_runner_example('some_arg')
        job.refresh_from_db()

        self.assertEqual(job.job_name, 'job_runner_example')
        self.assertEqual(job.arg_identifier, 'some_arg')
        self.assertEqual(job.status, Job.Status.SUCCESS)
        self.assertEqual(job.result_message, "Comment about result")

    def test_runner_job_error(self):
        job, _ = schedule_job('job_runner_example', 'job_error')

        job_runner_example('job_error')
        job.refresh_from_db()

        self.assertEqual(job.status, Job.Status.FAILURE)
        self.assertEqual(job.result_message, "A JobError")
        self.assert_no_error_log_saved()
        self.assert_no_email()

    def test_runner_other_error(self):
        job, _ = schedule_job('job_runner_example', 'other_error')

        job_runner_example('other_error')
        job.refresh_from_db()

        self.assertEqual(job.status, Job.Status.FAILURE)
        self.assertEqual(job.result_message, "ValueError: A ValueError")

        self.assert_error_log_saved(
            "ValueError",
            "A ValueError",
        )
        self.assert_latest_email(
            "Error in job: job_runner_example",
            ["ValueError: A ValueError"],
        )

    def test_starter_progression(self):
        job, _ = schedule_job('job_starter_example', 'some_arg')

        job_starter_example('some_arg')
        job.refresh_from_db()

        self.assertEqual(job.job_name, 'job_starter_example')
        self.assertEqual(job.arg_identifier, 'some_arg')
        self.assertEqual(job.status, Job.Status.IN_PROGRESS)
        self.assertEqual(job.result_message, "")

    def test_starter_job_error(self):
        job, _ = schedule_job('job_starter_example', 'job_error')

        job_starter_example('job_error')
        job.refresh_from_db()

        self.assertEqual(job.status, Job.Status.FAILURE)
        self.assertEqual(job.result_message, f"A JobError (ID: {job.pk})")
        self.assert_no_error_log_saved()
        self.assert_no_email()

    def test_starter_other_error(self):
        job, _ = schedule_job('job_starter_example', 'other_error')

        job_starter_example('other_error')
        job.refresh_from_db()

        self.assertEqual(job.status, Job.Status.FAILURE)
        self.assertEqual(
            job.result_message, f"ValueError: A ValueError (ID: {job.pk})")

        self.assert_error_log_saved(
            "ValueError",
            f"A ValueError (ID: {job.pk})",
        )
        self.assert_latest_email(
            "Error in job: job_starter_example",
            [f"ValueError: A ValueError (ID: {job.pk})"],
        )

    def test_logging(self):
        with self.assertLogs(logger='coralnet_tasks', level='DEBUG') as cm:
            full_job_example('some_arg')

        expected_start_message_regex = re.compile(
            # Message prefix applied by assertLogs() (the logging handler
            # format defined in settings is not used here)
            r"DEBUG:coralnet_tasks:"
            # UUID for this task instance
            r"[a-f\d\-]+;"
            # view or task
            r"task;"
            # start or end of task
            r"start;"
            r";"
            # Task name
            r"full_job_example;"
            # Task args
            r";;;\('some_arg',\)"
        )
        self.assertRegex(
            cm.output[0],
            expected_start_message_regex,
            f"Should log the expected start message")

        expected_end_message_regex = re.compile(
            r"DEBUG:coralnet_tasks:"
            r"[a-f\d\-]+;"
            r"task;"
            r"end;"
            # Seconds elapsed
            r"[\d.]+;"
            r"full_job_example;"
            r";;;\('some_arg',\)"
        )
        self.assertRegex(
            cm.output[1],
            expected_end_message_regex,
            f"Should log the expected end message")
