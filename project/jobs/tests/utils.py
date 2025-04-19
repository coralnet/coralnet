from datetime import datetime, timedelta, timezone
import re
from typing import Union
from unittest.case import TestCase

from django.contrib.auth.models import User

from ..exceptions import UnrecognizedJobNameError
from ..models import Job
from ..utils import get_job_details, get_or_create_job, job_runner, start_job


def fabricate_job(
    name: str,
    *task_args,
    delay: timedelta = None,
    scheduled_start_date: datetime = None,
    start_date: datetime = None,
    create_date: datetime = None,
    modify_date: datetime = None,
    status: str = Job.Status.PENDING,
    **kwargs
) -> Job:
    """
    Similar to the job-creation case of get_or_create_job(), except:
    - This allows specifying dates and initial status.
    - This allows specifying an arbitrary job name.
    """

    # Ensure that any made-up test job names are registered.
    try:
        get_job_details(name)
    except UnrecognizedJobNameError:
        @job_runner(job_name=name)
        def task_func():
            return ""

    # Accept naive datetimes as UTC.
    if start_date and start_date.tzinfo is None:
        start_date = start_date.replace(tzinfo=timezone.utc)
    if create_date and create_date.tzinfo is None:
        create_date = create_date.replace(tzinfo=timezone.utc)
    if modify_date and modify_date.tzinfo is None:
        modify_date = modify_date.replace(tzinfo=timezone.utc)

    if scheduled_start_date:
        if scheduled_start_date.tzinfo is None:
            scheduled_start_date = scheduled_start_date.replace(
                tzinfo=timezone.utc)
    elif delay:
        # For some callers, specifying delay is more convenient than
        # specifying scheduled start date.
        scheduled_start_date = datetime.now(timezone.utc) + delay

    job_kwargs = {
        key: value for key, value in kwargs.items()
        if key in [
            'source', 'source_id', 'user', 'attempt_number',
            'persist', 'hidden',
        ]
    }
    job = Job(
        job_name=name,
        arg_identifier=Job.args_to_identifier(task_args),
        status=status,
        scheduled_start_date=scheduled_start_date,
        start_date=start_date,
        **job_kwargs
    )
    job.save()

    if create_date:
        # Now that the job's been created already, we can set a custom create
        # date on it.
        job.create_date = create_date
        job.save()
    if modify_date:
        # When we use QuerySet.update() instead of Model.save(), the
        # modify date doesn't get auto-updated to the current date,
        # allowing us to set a custom value.
        Job.objects.filter(pk=job.pk).update(modify_date=modify_date)

    job.refresh_from_db()
    return job


def do_job(
    name: str,
    *task_args,
    source_id: int = None,
    user: User = None,
) -> Job:
    """
    Here we just want to run a particular job and don't really care about
    how we get there (creating or starting).
    Note: this doesn't generally work for jobs decorated with @full_job.
    """

    job, created = get_or_create_job(
        name, *task_args, source_id=source_id, user=user)

    now = datetime.now(timezone.utc)

    if created:
        started = start_job(job)
    else:
        if job.status == Job.Status.PENDING:
            if job.scheduled_start_date < now:
                # This Job was previously considered scheduled for later, but
                # now it's just being run outright. Null out the scheduled date
                # since it can be misleading.
                job.scheduled_start_date = None
                job.save()
            started = start_job(job)
        else:
            # The same job was already existing and running.
            started = True

    assert started, "Expected to start the job, but start condition not met."

    job.refresh_from_db()
    return job


class JobUtilsMixin(TestCase):

    @staticmethod
    def get_latest_job_by_name(job_name):
        return Job.objects.filter(job_name=job_name).latest('pk')

    def assert_job_persist_value(self, job_name, expected_value):
        job = self.get_latest_job_by_name(job_name)
        self.assertEqual(
            job.persist, expected_value,
            "Job persist value should be as expected"
        )

    def assert_job_result_message(
        self, job_name,
        expected_message: Union[str, re.Pattern],
        assert_msg="Job result message should be as expected",
    ):
        job = self.get_latest_job_by_name(job_name)

        if isinstance(expected_message, re.Pattern):
            self.assertRegex(
                job.result_message, expected_message, msg=assert_msg,
            )
        else:
            self.assertEqual(
                job.result_message, expected_message, msg=assert_msg,
            )

    def assert_job_failure_message(
        self, job_name,
        expected_message: Union[str, re.Pattern],
        assert_msg="Job result message should be as expected",
    ):
        job = self.get_latest_job_by_name(job_name)

        self.assertEqual(job.status, Job.Status.FAILURE)

        if isinstance(expected_message, re.Pattern):
            self.assertRegex(
                job.result_message, expected_message, msg=assert_msg,
            )
        else:
            self.assertEqual(
                job.result_message, expected_message, msg=assert_msg,
            )
