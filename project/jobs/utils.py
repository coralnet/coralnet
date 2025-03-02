from collections import defaultdict
from datetime import datetime, timedelta, timezone
import functools
import inspect
from logging import getLogger
import math
import random
import sys
import traceback
from typing import Callable
import uuid

from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import mail_admins
from django.db import transaction
from django.db.models import Aggregate, DurationField
from django.utils.module_loading import autodiscover_modules
from django.views.debug import ExceptionReporter
from django_huey import db_periodic_task, db_task
from huey import crontab

from errorlogs.utils import instantiate_error_log
from lib.utils import context_scoped_cache
from .exceptions import JobError, UnrecognizedJobNameError
from .models import Job

logger = getLogger(__name__)
task_logger = getLogger('coralnet_tasks')


MANY_FAILURES = 5


def get_or_create_job(
    name: str,
    *task_args,
    source_id: int = None,
    user: User = None,
) -> tuple[Job, bool]:
    """
    Create a pending Job, or get a matching incomplete Job.
    Return the Job, and a bool saying whether it was just created or not.

    The get_or_create() call will be atomic due to our uniqueness
    constraint on incomplete Jobs. This means we won't have
    race conditions where two incomplete Jobs have the same name+args.
    https://docs.djangoproject.com/en/4.2/ref/models/querysets/#get-or-create
    But with this in mind, it's best to ensure this isn't called within a
    larger transaction. So, views should always pair this with
    transaction.on_commit().
    """

    arg_identifier = Job.args_to_identifier(task_args)
    job_lookup_kwargs = dict(
        job_name=name,
        arg_identifier=arg_identifier,
    )

    # See if an incomplete Job exists with the lookup kwargs. If so, get it
    # (guaranteed to be unique due to a DB-level uniqueness constraint).
    # Else, create a new Job with the lookup kwargs and defaults.
    job, created = Job.objects.incomplete().get_or_create(
        **job_lookup_kwargs,
        defaults=dict(
            source_id=source_id,
            status=Job.Status.PENDING,
            user=user if user and user.is_authenticated else None,
        )
    )

    if created:
        # Set the new Job's attempt number.

        attempt_number = 1

        # See if the same job failed last time (if there was a last time).
        # If so, set the attempt count accordingly.
        try:
            last_completed_job = (
                Job.objects.completed()
                .filter(**job_lookup_kwargs)
                .latest('pk')
            )
        except Job.DoesNotExist:
            pass
        else:
            if last_completed_job.status == Job.Status.FAILURE:
                attempt_number = last_completed_job.attempt_number + 1

                if attempt_number > MANY_FAILURES:
                    # Notify admins on repeated failure.
                    mail_admins(
                        f"Job has been failing repeatedly:"
                        f" {last_completed_job}",
                        f"Error info:\n\n{last_completed_job.result_message}",
                    )

        job.attempt_number = attempt_number
        job.save()

    return job, created


def random_job_delay():
    # Use a random amount of jitter to slightly space out jobs that are
    # being submitted in quick succession.
    return timedelta(seconds=random.randrange(5, 30))


def schedule_job(
    name: str,
    *task_args,
    source_id: int = None,
    user: User = None,
    delay: timedelta = None,
) -> tuple[Job, bool]:
    """
    Create a pending Job, or get a matching incomplete Job and update its
    schedule if applicable.
    Return the Job, and a bool saying whether it was just created or not.
    """

    job, created = get_or_create_job(
        name, *task_args, source_id=source_id, user=user)

    if delay is None:
        delay = random_job_delay()
    now = datetime.now(timezone.utc)
    scheduled_start_date = now + delay

    if created:
        # Set the new Job's scheduled start date.
        if job.attempt_number > MANY_FAILURES:
            # Make sure it doesn't retry too quickly until the failure
            # situation's manually resolved.
            three_days_from_now = now + timedelta(days=3)
            if scheduled_start_date < three_days_from_now:
                scheduled_start_date = three_days_from_now

        job.scheduled_start_date = scheduled_start_date
        job.save()
    else:
        if (
            job.status == Job.Status.PENDING
            and job.attempt_number <= MANY_FAILURES
        ):
            # Update the existing Job's scheduled start date
            # if an earlier date was just requested (or if there
            # is no scheduled date yet).
            if (
                job.scheduled_start_date is None
                or scheduled_start_date < job.scheduled_start_date
            ):
                job.scheduled_start_date = scheduled_start_date
                job.save()

    return job, created


def schedule_job_on_commit(name: str, *args, **kwargs) -> None:
    """
    Call schedule_job() after the current transaction commits,
    thus allowing get_or_create_job() to effectively prevent
    race conditions.
    """
    transaction.on_commit(
        functools.partial(schedule_job, name, *args, **kwargs))


def bulk_create_jobs(
    name: str,
    tasks_args: list[list],
) -> list[Job]:
    """
    Create many pending Jobs efficiently.
    NOTE: This does not watch for job-existence race conditions.
    ONLY use this when the Jobs don't have any possibility of
    conflicting with other existing Jobs. For example, deploy API
    classify-image Jobs.
    Non-example: classification Jobs for sources, since it's possible
    for multiple threads to "know" about a given image in a source, so
    multiple threads might try to queue classification for that image
    at the same time.
    """
    now = datetime.now(timezone.utc)

    jobs = [
        Job(
            job_name=name,
            arg_identifier=Job.args_to_identifier(task_args),
            scheduled_start_date=now+random_job_delay(),
        )
        for task_args in tasks_args
    ]
    Job.objects.bulk_create(jobs)
    return jobs


def start_job(job: Job) -> bool:
    """
    Immediately add an existing Job to huey's queue.

    The Job's JobDecorator (part of the 'run function') will
    presumably take care of updating the Job's status/fields.

    Return True if the job was actually started, else False.
    """
    job_details = get_job_details(job.job_name)

    if job_details['start_condition'] is not None:
        if not job_details['start_condition'](job.pk):
            return False

    starter_task = job_details['run_function']
    starter_task(*Job.identifier_to_args(job.arg_identifier))
    return True


def finish_job(
    job: Job,
    success: bool = False,
    result_message: str = None,
) -> None:
    """
    Update Job status to SUCCESS/FAILURE, and do associated bookkeeping.
    """

    # This field doesn't take None; no message is set as an empty string.
    job.result_message = result_message or ""
    job.status = Job.Status.SUCCESS if success else Job.Status.FAILURE
    job.save()

    name = job.job_name

    if settings.ENABLE_PERIODIC_JOBS:
        # If it's a periodic job, schedule another run of it
        schedule = get_periodic_job_schedules().get(name, None)
        if schedule:
            interval, offset = schedule
            schedule_job(name, delay=next_run_delay(interval, offset))


def abort_job(job_id: int):
    job = Job.objects.get(pk=job_id)
    finish_job(job, success=False, result_message="Aborted manually")


def finish_jobs(jobs_details: list[dict]):
    jobs = []
    now = datetime.now(timezone.utc)

    for job_details in jobs_details:
        job = job_details['job']
        job.result_message = job_details['result_message'] or ""
        job.status = (
            Job.Status.SUCCESS if job_details['success']
            else Job.Status.FAILURE)
        # auto_now fields like modify_date don't get auto-updated by
        # bulk_update(); so we set it explicitly here.
        # https://docs.djangoproject.com/en/4.2/ref/models/fields/#django.db.models.DateField.auto_now
        job.modify_date = now
        jobs.append(job)
    Job.objects.bulk_update(jobs, ['result_message', 'status', 'modify_date'])

    # No periodic-job case. Periodic jobs should use finish_job() instead.


class JobDecorator:
    def __init__(
        self, job_name: str = None, job_display_name: str = None,
        interval: timedelta = None, offset: datetime = None,
        huey_interval_minutes: int = None,
        task_queue_name: str = None,
        atomic: bool = False,
        start_condition: Callable[[int], bool] = None,
        after_finishing_job: Callable[[int], None] = None,
    ):
        # This can be left unspecified if the task name works as the
        # job name.
        self.job_name = job_name

        # This can be left unspecified if the task name in its 'readable'
        # form works as the job display name.
        self.job_display_name = job_display_name

        # Default to the django-huey default queue setting.
        # Although django-huey itself can apply the default when the task is
        # queued, we apply it here anyway for our bookkeeping.
        self.task_queue_name = (
            task_queue_name or settings.DJANGO_HUEY['default'])

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

        # If True, we're database-atomic from just after starting the job
        # until just after the task function + after_finishing_job.
        self.atomic = atomic

        # Optional callable that's called at the start of start_job()
        # (if applicable to the task decorator); if it returns True, then
        # the job is allowed to start. Takes the Job ID as an argument.
        self.start_condition = start_condition

        # Optional callable that's called after finish_job() (if applicable to
        # the task decorator) and takes the Job ID as an argument.
        self.after_finishing_job = after_finishing_job

    @staticmethod
    def log_debug(tokens):
        message = ';'.join(str(token) for token in tokens)
        task_logger.debug(message)

    def __call__(self, task_func):
        if not self.job_name:
            self.job_name = task_func.__name__
        if not self.job_display_name:
            self.job_display_name = (
                self.job_name.capitalize().replace('_', ' '))

        if self.huey_interval_minutes:
            huey_decorator = db_periodic_task(
                # Cron-like specification for when huey should run the task.
                crontab(f'*/{self.huey_interval_minutes}'),
                # huey will discard the task run if it's this late.
                # Basically if huey falls behind 30 minutes, we don't need it
                # to run the same every-3-minutes task 10 times as makeup.
                expires=timedelta(minutes=self.huey_interval_minutes*2),
                name=self.job_name,
                queue=self.task_queue_name,
            )
        else:
            if self.interval:
                _set_periodic_job_schedule(
                    self.job_name, self.interval, self.offset)
            huey_decorator = db_task(
                name=self.job_name,
                queue=self.task_queue_name,
            )

        @huey_decorator
        def task_wrapper(*task_args):
            # Log a message before task entry.
            # Columns are supposed to correspond to the ones in
            # lib.middleware.ViewLoggingMiddleware.
            task_id = str(uuid.uuid4())
            self.log_debug([
                task_id,
                'task',
                'start',
                '',
                task_func.__name__,
                '',
                '',
                '',
                task_args,
            ])
            start_time = datetime.now()

            with context_scoped_cache():
                self.run_task_wrapper(task_func, task_args)

            # Log a message after task exit.
            elapsed_seconds = (
                datetime.now() - start_time).total_seconds()
            self.log_debug([
                task_id,
                'task',
                'end',
                elapsed_seconds,
                task_func.__name__,
                '',
                '',
                '',
                task_args,
            ])

        task_parameters = inspect.signature(task_func).parameters
        is_source_job = (
            'source_id' in task_parameters
            or 'image_id' in task_parameters)
        _register_job(
            self.job_name,
            display_name=self.job_display_name,
            run_function=task_wrapper,
            is_source_job=is_source_job,
            task_queue_name=self.task_queue_name,
            start_condition=self.start_condition,
        )

        return task_wrapper

    def run_task_wrapper(self, task_func, task_args):
        raise NotImplementedError

    def run_entire_task_wrapper(self, job, task_func, task_args):
        """
        Wrapper for a task function which consists of the job spec
        in its entirety. Thus, it's just started as we enter here,
        and this wrapper should mark it finished.
        """
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

            if self.after_finishing_job:
                self.after_finishing_job(job.pk)

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

    @staticmethod
    def update_pending_job_to_in_progress(
        name: str,
        *task_args,
    ) -> Job | None:
        """
        Get the specified pending Job and update it to in-progress.
        If there's no matching pending Job, return None.
        """
        arg_identifier = Job.args_to_identifier(task_args)
        job_lookup_kwargs = dict(
            job_name=name,
            arg_identifier=arg_identifier,
        )

        try:
            job = Job.objects.get(
                status=Job.Status.PENDING, **job_lookup_kwargs)
        except Job.DoesNotExist:
            return None

        job.status = Job.Status.IN_PROGRESS
        job.start_date = datetime.now(timezone.utc)
        job.save()
        return job

    @staticmethod
    def create_in_progress_job(
        name: str,
        *task_args,
        source_id: int = None,
        user: User = None,
    ) -> Job | None:
        """
        Create the specified Job as in-progress.
        If there's already a matching incomplete Job, don't do anything with it
        and return None.
        """

        job, created = get_or_create_job(
            name, *task_args, source_id=source_id, user=user)

        if created:
            job.status = Job.Status.IN_PROGRESS
            job.start_date = datetime.now(timezone.utc)
            job.save()
            return job
        else:
            return None


class FullJobDecorator(JobDecorator):
    """
    Job is created as IN_PROGRESS at the start of the decorated task,
    and goes IN_PROGRESS -> SUCCESS/FAILURE at the end of it.

    This decorator is only meant for the 'top-level' jobs which schedule other
    jobs. This is the only type of Job we want scheduled periodically by huey.
    We don't use huey's periodic-task construct for most kinds of tasks/jobs
    because:

    - It doesn't let us easily report when the next run of a particular job is.
    - The logic isn't great for infrequent jobs on an unstable server: if we
      have a daily job, and huey's cron doesn't get to run on the particular
      minute that the job's scheduled for, then the job has to wait another day
      before trying again.

    However, we do depend on huey to begin the process of scheduling and
    running jobs in the first place.

    Note that huey periodic tasks can't have args.
    https://huey.readthedocs.io/en/latest/guide.html#periodic-tasks
    """
    def run_task_wrapper(self, task_func, task_args):
        job = self.create_in_progress_job(
            self.job_name,
            *task_args,
        )
        if job is None:
            return

        if self.atomic:
            # Note that the above job creation isn't atomic with
            # this part, otherwise we'd never see the job status
            # until the job's done (at which point it's marked completed).
            with transaction.atomic():
                self.run_entire_task_wrapper(job, task_func, task_args)
        else:
            self.run_entire_task_wrapper(job, task_func, task_args)


full_job = FullJobDecorator


class JobRunnerDecorator(JobDecorator):
    """
    Job status goes PENDING -> IN_PROGRESS at the start of the
    decorated task, and IN_PROGRESS -> SUCCESS/FAILURE at the end of it.
    """
    def run_task_wrapper(self, task_func, task_args):
        job = self.update_pending_job_to_in_progress(
            self.job_name,
            *task_args,
        )
        if job is None:
            return

        if self.atomic:
            # Note that the above update to in-progress isn't atomic with
            # this part, otherwise we'd never see the in-progress status
            # until the job's done (at which point it's marked completed).
            with transaction.atomic():
                self.run_entire_task_wrapper(job, task_func, task_args)
        else:
            self.run_entire_task_wrapper(job, task_func, task_args)


job_runner = JobRunnerDecorator


class JobStarterDecorator(JobDecorator):
    """
    Job status goes PENDING -> IN_PROGRESS at the start of the
    decorated task. No update is made at the end of the task
    (unless there's an error).
    """
    def run_task_wrapper(self, task_func, task_args):
        job = self.update_pending_job_to_in_progress(
            self.job_name,
            *task_args,
        )
        if job is None:
            return

        if self.atomic:
            with transaction.atomic():
                self.run_task_start_wrapper(job, task_func, task_args)
        else:
            self.run_task_start_wrapper(job, task_func, task_args)

    def run_task_start_wrapper(self, job, task_func, task_args):
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


_registered_jobs: dict[str, dict] = dict()


_ran_autodiscover = False


def autodiscover_jobs_if_needed():
    global _ran_autodiscover
    if not _ran_autodiscover:
        # Auto-discover.
        # 'Running' the tasks modules should populate the dict.
        #
        # Note: although the run_huey command also autodiscovers tasks,
        # that autodiscovery only applies to the huey thread; the results
        # are not available to the web server threads.
        autodiscover_modules('tasks')
        _ran_autodiscover = True


def get_job_details(job_name):
    autodiscover_jobs_if_needed()
    if job_name not in _registered_jobs:
        raise UnrecognizedJobNameError
    return _registered_jobs[job_name]


def _register_job(
    name, display_name, run_function, is_source_job, task_queue_name,
    start_condition=None,
):
    _registered_jobs[name] = dict(
        display_name=display_name,
        run_function=run_function,
        is_source_job=is_source_job,
        task_queue_name=task_queue_name,
        start_condition=start_condition,
    )


def get_source_job_names():
    autodiscover_jobs_if_needed()
    return [
        job_name
        for job_name, job_details in _registered_jobs.items()
        if job_details['is_source_job']
    ]


def get_non_source_job_names():
    autodiscover_jobs_if_needed()
    return [
        job_name
        for job_name, job_details in _registered_jobs.items()
        if not job_details['is_source_job']
    ]


def get_job_names_by_task_queue():
    autodiscover_jobs_if_needed()
    d = defaultdict(list)
    for job_name, job_details in _registered_jobs.items():
        d[job_details['task_queue_name']].append(job_name)
    return d


_periodic_job_schedules: dict[str, tuple[float, float]] = dict()


def get_periodic_job_schedules():
    autodiscover_jobs_if_needed()
    return _periodic_job_schedules


def _set_periodic_job_schedule(name, interval: float, offset: float):
    _periodic_job_schedules[name] = (interval, offset)


def next_run_delay(interval: float, offset: float = 0) -> timedelta:
    """
    Given a periodic job with a periodic interval of `interval` and a period
    offset of `offset`, find the time until the job is scheduled to run next.

    Both interval and offset are in seconds.
    Offset is defined from Unix timestamp 0. One can either treat is as purely
    relative (e.g. two 1-hour interval jobs, pass 0 offset for one job and
    1/2 hour offset for the other), or pass in a specific date's timestamp to
    induce runs at specific times of day / days of week.
    """
    now_timestamp = datetime.now(timezone.utc).timestamp()
    interval_count = math.ceil((now_timestamp - offset) / interval)
    next_run_timestamp = offset + (interval_count * interval)
    delay_in_seconds = max(next_run_timestamp - now_timestamp, 0)
    return timedelta(seconds=delay_in_seconds)


class Time10Percentile(Aggregate):
    function = 'PERCENTILE_CONT'
    name = 'percentile10'
    output_field = DurationField()
    template = '%(function)s(0.1) WITHIN GROUP (ORDER BY %(expressions)s)'


class Time90Percentile(Aggregate):
    function = 'PERCENTILE_CONT'
    name = 'percentile90'
    output_field = DurationField()
    template = '%(function)s(0.9) WITHIN GROUP (ORDER BY %(expressions)s)'
