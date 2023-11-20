from datetime import datetime, timedelta
import logging
import math
import random
import sys
import traceback
from typing import Optional

from django.conf import settings
from django.core.mail import mail_admins
from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone
from django.utils.module_loading import autodiscover_modules
from django.views.debug import ExceptionReporter
from huey import crontab
from huey.contrib.djhuey import db_periodic_task, db_task

from errorlogs.utils import instantiate_error_log
from .exceptions import JobError
from .models import Job

logger = logging.getLogger(__name__)


MANY_FAILURES = 5


def queue_job(
        name: str,
        *task_args,
        delay: timedelta = None,
        source_id: int = None,
        initial_status: str = Job.Status.PENDING) -> Optional[Job]:

    if delay is None:
        # Use a random amount of jitter to slightly space out jobs that are
        # being submitted in quick succession.
        delay = timedelta(seconds=random.randrange(5, 30))
    now = timezone.now()
    scheduled_start_date = now + delay

    arg_identifier = Job.args_to_identifier(task_args)
    job_kwargs = dict(
        job_name=name,
        arg_identifier=arg_identifier,
    )

    # See if the same job is already pending or in progress. This is just a
    # best-effort check. We want this to be safe for views to call without
    # crashing the current transaction, which is why we don't make this
    # stricter against race conditions. We'll be stricter if actually
    # starting a job (as opposed to just queueing it as pending).
    jobs = Job.objects.filter(**job_kwargs)
    try:
        # There may be multiple such jobs; just get at most one.
        # We'll leave the task of dupe cleanup to start_pending_job()
        # (which is more strict on race conditions).
        job = jobs.filter(status__in=[
            Job.Status.PENDING, Job.Status.IN_PROGRESS]).earliest('pk')
    except Job.DoesNotExist:
        pass
    else:
        logger.debug(f"Job [{job}] is already pending or in progress.")

        if (
            job.status == Job.Status.PENDING
            and job.attempt_number <= MANY_FAILURES
        ):
            # Update the scheduled start date if an earlier date was just
            # requested
            if scheduled_start_date < job.scheduled_start_date:
                job.scheduled_start_date = scheduled_start_date
                job.save()
                logger.debug(f"Updated the job's scheduled start date.")

        return None

    # See if the same job failed last time (if there was a last time).
    # If so, set the attempt count accordingly.
    attempt_number = 1
    try:
        last_job = jobs.filter(
            status__in=[Job.Status.SUCCESS, Job.Status.FAILURE]).latest('pk')
    except Job.DoesNotExist:
        pass
    else:
        if last_job.status == Job.Status.FAILURE:
            attempt_number = last_job.attempt_number + 1

            if attempt_number > MANY_FAILURES:
                # Notify admins on repeated failure.
                mail_admins(
                    f"Job has been failing repeatedly: {last_job}",
                    f"Error info:\n\n{last_job.result_message}",
                )
                # Make sure it doesn't retry too quickly until the failure
                # situation's manually resolved.
                three_days_from_now = now + timedelta(days=3)
                if scheduled_start_date < three_days_from_now:
                    scheduled_start_date = three_days_from_now

    # Create a new job and proceed
    job = Job(
        scheduled_start_date=scheduled_start_date,
        attempt_number=attempt_number,
        source_id=source_id,
        status=initial_status,
        **job_kwargs
    )
    try:
        job.save()
    except IntegrityError:
        # There's a DB-level uniqueness check which prevents duplicate
        # in-progress jobs.
        # This ensures that we don't have two threads starting the same
        # job at the same time. (This works most effectively if we use
        # short transactions or autocommit when creating in-progress jobs.)
        logger.info(f"Job [{job}] is already in progress.")
        return None

    return job


def start_pending_job(job_name: str, arg_identifier: str) -> Optional[Job]:
    """
    Find a pending job matching the passed fields.
    If job not found, or already in progress, return None.
    Else, update the status to in-progress and return the job.
    """
    # select_for_update() locks these DB rows from evaluation time
    # to the end of the transaction. This ensures that we don't
    # have two threads starting the same job at the same time.
    # Instead, the first thread will get to run, while the second thread
    # will get a DatabaseError and return.
    # (This works most effectively if we're using autocommit when entering
    # this function.)
    jobs_queryset = Job.objects.select_for_update(nowait=True).filter(
        job_name=job_name,
        arg_identifier=arg_identifier,
        status__in=[Job.Status.PENDING, Job.Status.IN_PROGRESS],
    )
    with transaction.atomic():
        # Evaluate the query.
        try:
            jobs = list(jobs_queryset)
        except DatabaseError:
            # Probably tripped the select_for_update() row locking, meaning
            # there's another thread in here already.
            logger.info(
                f"Job [{job_name} / {arg_identifier}] is locked"
                f" to prevent overlapping runs.")
            return None

        if len(jobs) == 0:
            logger.info(f"Job [{job_name} / {arg_identifier}] not found.")
            return None

        if Job.Status.IN_PROGRESS in [job.status for job in jobs]:
            logger.info(f"Job [{jobs[0]}] already in progress.")
            return None

        job = jobs[0]
        if len(jobs) > 1:
            for dupe_job in jobs[1:]:
                # Delete any duplicate pending jobs
                dupe_job.delete()

        job.status = Job.Status.IN_PROGRESS
        job.save()
    return job


def finish_job(job, success=False, result_message=None):
    """
    Update Job status from IN_PROGRESS to SUCCESS/FAILURE,
    and do associated bookkeeping.
    """
    # This field doesn't take None; no message is set as an empty string.
    job.result_message = result_message or ""
    job.status = Job.Status.SUCCESS if success else Job.Status.FAILURE

    # Successful jobs related to classifier history should persist in the DB.
    name = job.job_name
    if success and name in [
        'train_classifier',
        'reset_classifiers_for_source',
        'reset_backend_for_source',
    ]:
        job.persist = True

    job.save()

    if job.result_message:
        logger.info(f"Job [{job}]: {job.result_message}")

    if settings.ENABLE_PERIODIC_JOBS:
        # If it's a periodic job, schedule another run of it
        schedule = get_periodic_job_schedules().get(name, None)
        if schedule:
            interval, offset = schedule
            queue_job(name, delay=next_run_delay(interval, offset))


class JobDecorator:
    def __init__(
        self, job_name: str = None,
        interval: timedelta = None, offset: datetime = None,
        huey_interval_minutes: int = None,
    ):
        # This can be left unspecified if the task name works as the
        # job name.
        self.job_name = job_name

        # This should be present if the job is to be run periodically
        # through run_scheduled_jobs().
        # This is an interval for next_run_delay().
        if interval:
            self.interval = interval.total_seconds()
        else:
            self.interval = None

        # This is only looked at if interval is present.
        # This is an offset for next_run_delay().
        if offset:
            self.offset = offset.timestamp()
        else:
            self.offset = 0

        # This should be present if the job is to be run as a huey periodic
        # task.
        # Only minute-intervals are supported for simplicity.
        self.huey_interval_minutes = huey_interval_minutes

    def __call__(self, task_func):
        if not self.job_name:
            self.job_name = task_func.__name__

        if self.huey_interval_minutes:
            huey_decorator = db_periodic_task(
                # Cron-like specification for when huey should run the task.
                crontab(f'*/{self.huey_interval_minutes}'),
                # huey will discard the task run if it's this late.
                # Basically if huey falls behind 30 minutes, we don't need it
                # to run the same every-3-minutes task 10 times as makeup.
                expires=timedelta(minutes=self.huey_interval_minutes*2),
                name=self.job_name,
            )
        else:
            if self.interval:
                set_periodic_job_schedule(
                    self.job_name, self.interval, self.offset)
            huey_decorator = db_task(name=self.job_name)

        @huey_decorator
        def task_wrapper(*task_args):
            self.run_task_wrapper(task_func, task_args)

        set_job_run_function(self.job_name, task_wrapper)

        return task_wrapper

    def run_task_wrapper(self, task_func, task_args):
        raise NotImplementedError

    def report_unexpected_error(self):
        # Get the most recent exception's info.
        kind, info, data = sys.exc_info()

        # Email admins.
        error_data = '\n'.join(traceback.format_exception(kind, info, data))
        mail_admins(
            f"Error in job: {self.job_name}",
            f"{kind.__name__}: {info}\n\n{error_data}",
        )

        # Save an ErrorLog.
        error_html = ExceptionReporter(
            None, kind, info, data).get_traceback_html()
        error_log = instantiate_error_log(
            kind=kind.__name__,
            html=error_html,
            path=f"Task - {self.job_name}",
            info=info,
            data=error_data,
        )
        error_log.save()


class FullJobDecorator(JobDecorator):
    """
    Job is created as IN_PROGRESS at the start of the decorated task,
    and goes IN_PROGRESS -> SUCCESS/FAILURE at the end of it.
    """
    def run_task_wrapper(self, task_func, task_args):
        job = queue_job(
            self.job_name,
            *task_args,
            delay=timedelta(seconds=0),
            initial_status=Job.Status.IN_PROGRESS,
            # No usages are source-specific yet.
            source_id=None,
        )
        if not job:
            return

        success = False
        result_message = None
        try:
            # Run the task function (which isn't a huey task itself;
            # the result of this wrapper should be registered as a
            # huey task).
            result_message = task_func(*task_args)
            success = True
        except JobError as e:
            result_message = str(e)
        except Exception as e:
            # Non-JobError; a category of error we haven't expected here, and
            # likely needs fixing. Report it like a server error.
            self.report_unexpected_error()
            # Include the error class name, since some error types' messages
            # don't have enough context otherwise (e.g. a KeyError's message
            # is just the key that was tried).
            result_message = f'{type(e).__name__}: {e}'
        finally:
            # Regardless of error or not, mark job as done
            finish_job(job, success=success, result_message=result_message)


full_job = FullJobDecorator


class JobRunnerDecorator(JobDecorator):
    """
    Job status goes PENDING -> IN_PROGRESS at the start of the
    decorated task, and IN_PROGRESS -> SUCCESS/FAILURE at the end of it.
    """
    def run_task_wrapper(self, task_func, task_args):
        job = start_pending_job(
            job_name=self.job_name,
            arg_identifier=Job.args_to_identifier(task_args),
        )
        if not job:
            return

        success = False
        result_message = None
        try:
            result_message = task_func(*task_args)
            success = True
        except JobError as e:
            result_message = str(e)
        except Exception as e:
            # Non-JobError, likely needs fixing:
            # report it like a server error.
            self.report_unexpected_error()
            result_message = f'{type(e).__name__}: {e}'
        finally:
            # Regardless of error or not, mark job as done
            finish_job(job, success=success, result_message=result_message)


job_runner = JobRunnerDecorator


class JobStarterDecorator(JobDecorator):
    """
    Job status goes PENDING -> IN_PROGRESS at the start of the
    decorated task. No update is made at the end of the task
    (unless there's an error).
    """
    def run_task_wrapper(self, task_func, task_args):
        job = start_pending_job(
            job_name=self.job_name,
            arg_identifier=Job.args_to_identifier(task_args),
        )
        if not job:
            return

        try:
            task_func(*task_args, job_id=job.pk)
        except JobError as e:
            # JobError: job is considered done
            finish_job(job, success=False, result_message=str(e))
        except Exception as e:
            # Non-JobError, likely needs fixing:
            # job is considered done, and report it like a server error
            self.report_unexpected_error()
            result_message = f'{type(e).__name__}: {e}'
            finish_job(job, success=False, result_message=result_message)


job_starter = JobStarterDecorator


# Dict of functions which start each defined job.
_job_run_functions = dict()


def get_job_run_function(job_name):
    if job_name not in _job_run_functions:
        # Auto-discover.
        # 'Running' the tasks modules should populate the dict.
        #
        # Note: although the run_huey command also autodiscovers tasks,
        # that autodiscovery only applies to the huey thread; the results
        # are not available to the web server threads.
        autodiscover_modules('tasks')

    return _job_run_functions[job_name]


def set_job_run_function(name, task):
    _job_run_functions[name] = task


def run_job(job):
    starter_task = get_job_run_function(job.job_name)
    starter_task(*Job.identifier_to_args(job.arg_identifier))


_periodic_job_schedules = dict()


def get_periodic_job_schedules():
    if len(_periodic_job_schedules) == 0:
        # Auto-discover.
        # 'Running' the tasks modules should populate the dict.
        autodiscover_modules('tasks')

    return _periodic_job_schedules


def set_periodic_job_schedule(name, interval, offset):
    _periodic_job_schedules[name] = (interval, offset)


def next_run_delay(interval: int, offset: int = 0) -> timedelta:
    """
    Given a periodic job with a periodic interval of `interval` and a period
    offset of `offset`, find the time until the job is scheduled to run next.

    Both interval and offset are in seconds.
    Offset is defined from Unix timestamp 0. One can either treat is as purely
    relative (e.g. two 1-hour interval jobs, pass 0 offset for one job and
    1/2 hour offset for the other), or pass in a specific date's timestamp to
    induce runs at specific times of day / days of week.
    """
    now_timestamp = timezone.now().timestamp()
    interval_count = math.ceil((now_timestamp - offset) / interval)
    next_run_timestamp = offset + (interval_count * interval)
    delay_in_seconds = max(next_run_timestamp - now_timestamp, 0)
    return timedelta(seconds=delay_in_seconds)
