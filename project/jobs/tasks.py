from datetime import timedelta
from logging import getLogger

from django.conf import settings
from django.core.mail import mail_admins
from django.utils import timezone
import django_huey

from config.constants import SpacerJobSpec
from .exceptions import UnrecognizedJobNameError
from .models import Job
from .utils import (
    finish_job,
    full_job,
    get_periodic_job_schedules,
    job_runner,
    next_run_delay,
    schedule_job,
    start_job,
)


logger = getLogger(__name__)


def get_scheduled_jobs():
    jobs = (
        Job.objects.filter(status=Job.Status.PENDING)
        # Ensure that jobs scheduled to start first get processed first.
        # For jobs with no scheduled start date, tiebreak by pk for
        # consistency. (TODO: Test)
        .order_by('scheduled_start_date', 'pk')
    )
    # We'll run any pending jobs immediately if django-huey's default queue
    # is configured to act similarly.
    if not django_huey.get_queue(settings.DJANGO_HUEY['default']).immediate:
        jobs = jobs.filter(scheduled_start_date__lt=timezone.now())
    return jobs


@full_job(huey_interval_minutes=2)
def run_scheduled_jobs():
    """
    Add scheduled jobs to the huey queue.

    This task itself gets job-tracking as well, to enforce that only one
    thread runs this task at a time. That way, no job looped through in this
    task can get started in huey multiple times.
    """
    start = timezone.now()
    wrap_up_time = start + timedelta(minutes=settings.JOB_MAX_MINUTES)
    timed_out = False

    jobs_to_run = get_scheduled_jobs()
    example_jobs = []
    jobs_ran = 0

    for job in jobs_to_run:
        try:
            start_job(job)
        except UnrecognizedJobNameError:
            finish_job(
                job, success=False, result_message="Unrecognized job name")
            continue

        jobs_ran += 1
        if jobs_ran <= 3:
            example_jobs.append(job)
        if (
            jobs_ran % 10 == 0
            and timezone.now() > wrap_up_time
        ):
            timed_out = True
            break

    # Build result message

    if jobs_ran > 3:
        if timed_out:
            message = f"Ran {jobs_ran} jobs (timed out), including:"
        else:
            message = f"Ran {jobs_ran} jobs, including:"
    elif jobs_ran > 0:
        message = f"Ran {jobs_ran} job(s):"
    else:
        # 0
        message = f"Ran {jobs_ran} jobs"

    for job in example_jobs:
        message += f"\n{job.pk}: {job}"

    return message


def run_scheduled_jobs_until_empty():
    """
    For testing purposes, it's convenient to schedule + run jobs, and
    then also run the jobs which have been scheduled by those jobs,
    using just one call.

    However, this is a prime candidate for infinite looping if something is
    wrong with jobs/tasks. So we have a safety guard for that.
    """
    iterations = 0
    while get_scheduled_jobs().exists():
        run_scheduled_jobs()

        iterations += 1
        if iterations > 100:
            raise RuntimeError("Jobs are probably failing to run.")


@job_runner(interval=timedelta(days=1))
def clean_up_old_jobs():
    current_time = timezone.now()
    x_days_ago = current_time - timedelta(days=settings.JOB_MAX_DAYS)

    # Clean up Jobs which are old enough since last modification,
    # don't have the persist flag set,
    # and are not tied to an ApiJobUnit.
    # The API-related Jobs should get cleaned up some time after
    # their ApiJobUnits get cleaned up.
    jobs_to_clean_up = Job.objects.filter(
        modify_date__lt=x_days_ago,
        persist=False,
        apijobunit__isnull=True,
    )
    count = jobs_to_clean_up.count()
    jobs_to_clean_up.delete()

    if count > 0:
        return f"Cleaned up {count} old job(s)"
    else:
        return "No old jobs to clean up"


# We'll consider most jobs stuck after 3 days of no status progression.
DEFAULT_STUCK_DAYS = 3
# Long AWS Batch jobs may run up to 7 days (depending on our AWS Batch config),
# so consider these jobs stuck after 8.
HIGH_SPEC_STUCK_DAYS = 8


@job_runner(interval=timedelta(days=1))
def report_stuck_jobs():
    """
    Report in-progress Jobs that haven't progressed since a certain
    number of days.
    """
    stuck_categories = [
        (Job.objects.exclude(batchjob__spec_level=SpacerJobSpec.HIGH),
         DEFAULT_STUCK_DAYS),
        (Job.objects.filter(batchjob__spec_level=SpacerJobSpec.HIGH),
         HIGH_SPEC_STUCK_DAYS),
    ]

    stuck_jobs_to_report = Job.objects.none()

    for job_queryset, threshold in stuck_categories:

        # This task runs every day, and we don't issue repeat warnings for
        # the same jobs on subsequent days. So, only grab jobs whose last
        # progression was between STUCK days and STUCK+1 days ago.
        stuck_days_ago = timezone.now() - timedelta(days=threshold)
        stuck_plus_one_days_ago = stuck_days_ago - timedelta(days=1)
        stuck_jobs_to_report |= (
            job_queryset.filter(
                status=Job.Status.IN_PROGRESS,
                modify_date__lt=stuck_days_ago,
                modify_date__gt=stuck_plus_one_days_ago,
            )
            # Oldest listed first
            .order_by('modify_date', 'pk')
        )

    if not stuck_jobs_to_report.exists():
        return "No stuck jobs detected"

    stuck_job_count = stuck_jobs_to_report.count()
    subject = f"{stuck_job_count} job(s) haven't progressed in a while"

    message = f"The following job(s) haven't progressed in a while:\n"
    for job in stuck_jobs_to_report:
        message += f"\n{job} - since {job.modify_date}"

    mail_admins(subject, message)

    return subject


@full_job(huey_interval_minutes=5)
def schedule_periodic_jobs():
    """
    Schedule periodic jobs as needed. This ensures that every defined periodic
    job has 1 pending or in-progress run.

    When a periodic job finishes, it should schedule another run of that same
    job. So this task is mainly for initialization and then acts as a fallback,
    e.g. if a periodic job crashes.
    """
    periodic_job_schedules = get_periodic_job_schedules()
    scheduled = 0

    for name, schedule in periodic_job_schedules.items():
        interval, offset = schedule
        job, created = schedule_job(
            name, delay=next_run_delay(interval, offset))
        if created:
            scheduled += 1

    if scheduled > 0:
        return f"Scheduled {scheduled} periodic job(s)"
    else:
        return "All periodic jobs are already scheduled"
