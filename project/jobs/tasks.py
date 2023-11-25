from datetime import timedelta
import logging

from django.conf import settings
from django.core.mail import mail_admins
from django.utils import timezone
from huey.contrib.djhuey import HUEY

from .exceptions import UnrecognizedJobNameError
from .models import Job
from .utils import (
    finish_job,
    full_job,
    get_periodic_job_schedules,
    job_runner,
    next_run_delay,
    queue_job,
    run_job,
)


logger = logging.getLogger(__name__)


def get_scheduled_jobs():
    jobs = Job.objects.filter(status=Job.Status.PENDING).order_by('pk')
    # We'll run any pending jobs immediately if huey is configured to act
    # similarly.
    if not HUEY.immediate:
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
            run_job(job)
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


@job_runner(interval=timedelta(days=1))
def report_stuck_jobs():
    """
    Report non-completed Jobs that haven't progressed since a certain
    number of days.
    """
    # When a non-completed Job hasn't been modified in this many days,
    # we'll consider it to be stuck.
    STUCK = 3

    # This task runs every day, and we don't issue repeat warnings for
    # the same jobs on subsequent days. So, only grab jobs whose last
    # progression was between STUCK days and STUCK+1 days ago.
    stuck_days_ago = timezone.now() - timedelta(days=STUCK)
    stuck_plus_one_days_ago = stuck_days_ago - timedelta(days=1)
    stuck_jobs_to_report = (
        Job.objects.filter(
            modify_date__lt=stuck_days_ago,
            modify_date__gt=stuck_plus_one_days_ago,
        )
        .exclude(status__in=[Job.Status.SUCCESS, Job.Status.FAILURE])
        # Oldest listed first
        .order_by('modify_date', 'pk')
    )

    if not stuck_jobs_to_report.exists():
        return "No stuck jobs detected"

    stuck_job_count = stuck_jobs_to_report.count()
    subject = f"{stuck_job_count} job(s) haven't progressed in {STUCK} days"

    message = f"The following job(s) haven't progressed in {STUCK} days:\n"
    for job in stuck_jobs_to_report:
        message += f"\n{job}"

    mail_admins(subject, message)

    return subject


@full_job(huey_interval_minutes=5)
def queue_periodic_jobs():
    """
    Queue periodic jobs as needed. This ensures that every defined periodic job
    has 1 pending or in-progress run.

    When a periodic job finishes, it should queue up another run of that same
    job. So this task is mainly for initialization and then acts as a fallback,
    e.g. if a periodic job crashes.

    We don't use huey's periodic-task construct for most kinds of tasks/jobs
    because:
    - It doesn't let us easily report when the next run of a particular job is.
    - The logic isn't great for infrequent jobs on an unstable server: if we
      have a daily job, and huey's cron doesn't get to run on the particular
      minute that the job's scheduled for, then the job has to wait another day
      before trying again.

    However, we do depend on huey to begin the process of queueing and running
    jobs in the first place.
    """
    periodic_job_schedules = get_periodic_job_schedules()
    queued = 0

    for name, schedule in periodic_job_schedules.items():
        interval, offset = schedule
        job = queue_job(name, delay=next_run_delay(interval, offset))
        if job:
            queued += 1

    if queued > 0:
        return f"Queued {queued} periodic job(s)"
    else:
        return "All periodic jobs are already queued"
