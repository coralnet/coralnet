from datetime import timedelta
from unittest import mock

from django.db import connections, transaction
from django.db.utils import DEFAULT_DB_ALIAS
from django.test.testcases import TransactionTestCase
from django.utils import timezone

from errorlogs.tests.utils import ErrorReportTestMixin
from lib.tests.utils import BaseTest, EmailAssertionsMixin
from ..exceptions import JobError
from ..models import Job
from ..utils import (
    finish_job, full_job, job_runner,
    job_starter, queue_job, start_pending_job)


class QueueJobTest(BaseTest, EmailAssertionsMixin, ErrorReportTestMixin):

    def test_queue_job_when_already_pending(self):
        queue_job('name', 'arg')

        with self.assertLogs(logger='jobs.utils', level='DEBUG') as cm:
            queue_job('name', 'arg')

        log_message = (
            "DEBUG:jobs.utils:"
            "Job [name / arg] is already pending or in progress."
        )
        self.assertIn(
            log_message, cm.output,
            "Should log the appropriate message")

        self.assertEqual(
            Job.objects.all().count(),
            1,
            "Should not have queued the second job")

    def test_queue_job_when_already_in_progress(self):
        queue_job('name', 'arg', initial_status=Job.Status.IN_PROGRESS)

        with self.assertLogs(logger='jobs.utils', level='DEBUG') as cm:
            queue_job('name', 'arg')

        log_message = (
            "DEBUG:jobs.utils:"
            "Job [name / arg] is already pending or in progress."
        )
        self.assertIn(
            log_message, cm.output,
            "Should log the appropriate message")

        self.assertEqual(
            Job.objects.all().count(),
            1,
            "Should not have queued the second job")

    def test_queue_job_when_multiple_pending(self):
        # queue_job() normally prevents dupes unless there's a race
        # condition. To keep this test simple, we'll create Jobs with the
        # ORM instead.
        job = Job(job_name='name', arg_identifier='arg')
        job.save()
        job_2 = Job(job_name='name', arg_identifier='arg')
        job_2.save()

        with self.assertLogs(logger='jobs.utils', level='DEBUG') as cm:
            queue_job('name', 'arg')

        log_message = (
            "DEBUG:jobs.utils:"
            "Job [name / arg] is already pending or in progress."
        )
        self.assertIn(
            log_message, cm.output,
            "Should log the appropriate message (and not crash)")

    def test_queue_job_when_previously_done(self):
        queue_job('name', 'arg', initial_status=Job.Status.SUCCESS)
        queue_job('name', 'arg')

        self.assertEqual(
            Job.objects.all().count(),
            2,
            "Should have queued the second job")

    def test_start_date_expedited(self):
        """
        Test a pending job's scheduled start date getting expedited by a
        subsequent queue_job() call.
        """
        job = queue_job('name', 'arg', delay=timedelta(hours=1))
        original_start_date = job.scheduled_start_date

        queue_job('name', 'arg', delay=timedelta(hours=5))
        job.refresh_from_db()
        self.assertEqual(
            job.scheduled_start_date, original_start_date,
            msg="Start date shouldn't be updated when requesting a later date"
        )

        queue_job('name', 'arg', delay=timedelta(seconds=30))
        job.refresh_from_db()
        self.assertLess(
            job.scheduled_start_date, original_start_date,
            msg="Start date should be updated when requesting an earlier date"
        )

    def test_attempt_number_increment(self):
        job = queue_job('name', 'arg', initial_status=Job.Status.FAILURE)
        job.result_message = "An error"
        job.save()

        job_2 = queue_job('name', 'arg')

        self.assertEqual(
            job_2.attempt_number,
            2,
            "Should have attempt number of 2")

    def test_attempt_number_non_increment(self):
        queue_job('name', 'arg', initial_status=Job.Status.SUCCESS)
        job_2 = queue_job('name', 'arg')

        self.assertEqual(
            job_2.attempt_number,
            1,
            "Should have attempt number of 1")

    def test_repeated_failure(self):
        # 5 fails in a row
        for _ in range(5):
            job = queue_job(
                'name', 'arg', initial_status=Job.Status.IN_PROGRESS)
            finish_job(job, success=False, result_message="An error")
            self.assert_no_email()

        # Queue the same job again
        job = queue_job('name', 'arg')
        self.assert_latest_email(
            "Job has been failing repeatedly: name / arg, attempt 5",
            ["Error info:\n\nAn error"],
        )
        self.assertAlmostEquals(
            timezone.now() + timedelta(days=3),
            job.scheduled_start_date,
            delta=timedelta(minutes=10),
            msg="Latest job should be pushed back to 3 days in the future",
        )

        # And again
        finish_job(job, success=False, result_message="An error")
        queue_job('name', 'arg')
        self.assert_latest_email(
            "Job has been failing repeatedly: name / arg, attempt 6",
            ["Error info:\n\nAn error"],
        )

    def test_repeated_failure_longer_delay(self):
        # 5 fails in a row
        for _ in range(5):
            job = queue_job(
                'name', 'arg', initial_status=Job.Status.IN_PROGRESS)
            finish_job(job, success=False, result_message="An error")
            self.assert_no_email()

        # Queue the same job again, with longer delay
        job = queue_job('name', 'arg', delay=timedelta(days=5))
        self.assert_latest_email(
            "Job has been failing repeatedly: name / arg, attempt 5",
            ["Error info:\n\nAn error"],
        )
        self.assertAlmostEquals(
            timezone.now() + timedelta(days=5),
            job.scheduled_start_date,
            delta=timedelta(minutes=10),
            msg=(
                "Latest job should still be 5 days in the future;"
                " 3 days is just a lower bound"),
        )

    def test_repeated_failure_no_expediting(self):
        # 5 fails in a row
        for _ in range(5):
            job = queue_job('name', 'arg', delay=timedelta(days=5))

            # Call again with shorter delay
            queue_job('name', 'arg', delay=timedelta(days=2))
            job.refresh_from_db()
            self.assertAlmostEquals(
                timezone.now() + timedelta(days=2),
                job.scheduled_start_date,
                delta=timedelta(minutes=10),
                msg="Start date should have been expedited",
            )

            start_pending_job('name', 'arg')
            finish_job(job, success=False, result_message="An error")

        # Queue the same job again
        job = queue_job('name', 'arg', delay=timedelta(days=5))

        # Call again with shorter delay
        queue_job('name', 'arg', delay=timedelta(days=2))
        job.refresh_from_db()
        self.assertAlmostEquals(
            timezone.now() + timedelta(days=5),
            job.scheduled_start_date,
            delta=timedelta(minutes=10),
            msg="Start date shouldn't have been expedited",
        )


class StartPendingJobTest(BaseTest):

    def test_job_not_found(self):
        with self.assertLogs(logger='jobs.utils', level='INFO') as cm:
            start_pending_job('name', 'arg')

        log_message = (
            "INFO:jobs.utils:"
            "Job [name / arg] not found."
        )
        self.assertIn(
            log_message, cm.output,
            "Should log the appropriate message")

    def test_job_already_in_progress(self):
        queue_job('name', 'arg', initial_status=Job.Status.IN_PROGRESS)

        with self.assertLogs(logger='jobs.utils', level='INFO') as cm:
            start_pending_job('name', 'arg')

            log_message = (
                "INFO:jobs.utils:"
                "Job [name / arg] already in progress."
            )
            self.assertIn(
                log_message, cm.output,
                "Should log the appropriate message")

    def test_delete_duplicate_jobs(self):
        queue_job('name', 'arg')
        for _ in range(5):
            Job(
                job_name='name',
                arg_identifier='arg',
            ).save()
        self.assertEqual(Job.objects.count(), 6)

        start_pending_job('name', 'arg')
        self.assertEqual(
            Job.objects.count(), 1,
            "Dupe jobs should have been deleted")


class FinishJobTest(BaseTest):

    def test_periodic_job_queues_another_run(self):
        """
        Test a periodic job getting another instance of it queued after the
        current instance finishes.
        """
        def test_periodic():
            """
            By patching get_periodic_job_schedules() with this, we have this
            name registered as a periodic job.
            """
            return dict(
                name=(5*60, 0),
            )

        with mock.patch(
            'jobs.utils.get_periodic_job_schedules', test_periodic
        ):
            job = queue_job(
                'name', initial_status=Job.Status.IN_PROGRESS)
            finish_job(job, success=True)

        job.refresh_from_db()
        self.assertEqual(job.status, Job.Status.SUCCESS)

        # Another PENDING job should exist now
        Job.objects.get(job_name='name', status=Job.Status.PENDING)


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
        job = queue_job('job_runner_example', 'some_arg')

        job_runner_example('some_arg')
        job.refresh_from_db()

        self.assertEqual(job.job_name, 'job_runner_example')
        self.assertEqual(job.arg_identifier, 'some_arg')
        self.assertEqual(job.status, Job.Status.SUCCESS)
        self.assertEqual(job.result_message, "Comment about result")

    def test_runner_job_error(self):
        job = queue_job('job_runner_example', 'job_error')

        job_runner_example('job_error')
        job.refresh_from_db()

        self.assertEqual(job.status, Job.Status.FAILURE)
        self.assertEqual(job.result_message, "A JobError")
        self.assert_no_error_log_saved()
        self.assert_no_email()

    def test_runner_other_error(self):
        job = queue_job('job_runner_example', 'other_error')

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
        job = queue_job('job_starter_example', 'some_arg')

        job_starter_example('some_arg')
        job.refresh_from_db()

        self.assertEqual(job.job_name, 'job_starter_example')
        self.assertEqual(job.arg_identifier, 'some_arg')
        self.assertEqual(job.status, Job.Status.IN_PROGRESS)
        self.assertEqual(job.result_message, "")

    def test_starter_job_error(self):
        job = queue_job('job_starter_example', 'job_error')

        job_starter_example('job_error')
        job.refresh_from_db()

        self.assertEqual(job.status, Job.Status.FAILURE)
        self.assertEqual(job.result_message, f"A JobError (ID: {job.pk})")
        self.assert_no_error_log_saved()
        self.assert_no_email()

    def test_starter_other_error(self):
        job = queue_job('job_starter_example', 'other_error')

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


def save_two_copies(self, *args, **kwargs):
    # Must use the 2-arg super() form when using super() in a
    # function defined outside of a class.
    super(Job, self).save(*args, **kwargs)
    self.pk = None
    super(Job, self).save(*args, **kwargs)


class JobStartRaceConditionTest(TransactionTestCase):
    """
    This test class involves the locking behavior of
    select_for_update(), which is why we must base off of
    TransactionTestCase instead of TestCase.
    https://docs.djangoproject.com/en/4.1/topics/testing/tools/#transactiontestcase
    """

    def test_start_pending_job(self):
        # Create a pending job.
        queue_job('name', 'arg')

        # Prepare a select-for-update query which includes that job.
        queryset = Job.objects \
            .filter(job_name='name') \
            .select_for_update(nowait=True)

        # Get the query's SQL. We don't particularly need to execute the
        # query here, but in the process of getting the SQL, it does get
        # executed. Since it's a select-for-update, a transaction is
        # required.
        with transaction.atomic():
            queryset_sql = \
                queryset.query.sql_with_params()[0] % "'name'"

        # Make an extra DB connection.
        connection = connections.create_connection(alias=DEFAULT_DB_ALIAS)
        try:
            # Start a transaction with the extra DB connection.
            # We do it this way because transaction.atomic() would only
            # apply to the default connection.
            connection.set_autocommit(False)

            # With the extra DB connection, query the job row with
            # select_for_update(). This should lock the row for update
            # for the duration of the connection's transaction.
            with connection.cursor() as c:
                c.execute(queryset_sql)

            # With the default DB connection, make a start_pending_job() call
            # which will query the same row. Should get locked out.
            with self.assertLogs(logger='jobs.utils', level='INFO') as cm:
                start_pending_job('name', 'arg')

            log_message = (
                "INFO:jobs.utils:"
                "Job [name / arg] is locked to prevent overlapping runs."
            )
            self.assertIn(
                log_message, cm.output,
                "Should log the appropriate message")
        finally:
            # Close the extra DB connection.
            connection.close()

    def test_queue_in_progress_job(self):
        # Try to queue two in-progress jobs of the same name/args.
        # To simulate the race condition, we've mocked Job.save()
        # to create two identical jobs instead of just one job.
        with mock.patch.object(Job, 'save', save_two_copies):
            with self.assertLogs(logger='jobs.utils', level='INFO') as cm:
                queue_job('name', 'arg', initial_status=Job.Status.IN_PROGRESS)

        log_message = (
            "INFO:jobs.utils:"
            "Job [name / arg] is already in progress."
        )
        self.assertIn(
            log_message, cm.output,
            "Should log the appropriate message")
