from collections import Counter

from django.contrib.auth.decorators import permission_required
from django.db.models import Case, Count, Q, Value, When
from django.shortcuts import get_object_or_404, render

from api_core.models import ApiJob
from jobs.models import Job
from vision_backend_api.utils import deploy_request_json_as_strings


@permission_required('is_superuser')
def job_list(request):
    """
    Display a list of all API jobs.
    """
    jobs_values = (
        ApiJob.objects.all()
        .values('id', 'create_date', 'user__username', 'type')
        .annotate(
            total_units=Count('apijobunit'),
            pending_units=Count(
                'apijobunit',
                filter=Q(apijobunit__internal_job__status=Job.Status.PENDING)),
            in_progress_units=Count(
                'apijobunit',
                filter=Q(
                    apijobunit__internal_job__status=Job.Status.IN_PROGRESS)),
            failure_units=Count(
                'apijobunit',
                filter=Q(apijobunit__internal_job__status=Job.Status.FAILURE)),
            success_units=Count(
                'apijobunit',
                filter=Q(apijobunit__internal_job__status=Job.Status.SUCCESS)),
        )
        .annotate(
            overall_status=Case(
                # Done (all units success/failure).
                When(
                    pending_units=0,
                    in_progress_units=0,
                    then=Value(ApiJob.DONE),
                ),
                # Pending (all units pending).
                When(
                    in_progress_units=0,
                    then=Value(ApiJob.PENDING),
                ),
                # In progress (some other mix of statuses).
                default=Value(ApiJob.IN_PROGRESS),
            ),
        )
        .annotate(
            # How the job list should order jobs based on status.
            overall_status_order=Case(
                When(
                    overall_status=ApiJob.IN_PROGRESS,
                    then=1,
                ),
                When(
                    overall_status=ApiJob.PENDING,
                    then=2,
                ),
                default=3,
            ),
        )
        # Order by status, then latest first.
        .order_by('overall_status_order', '-id')
    )

    # Order jobs by progress status, then by decreasing primary key.
    status_counter = Counter([
        job_values['overall_status'] for job_values in jobs_values])

    return render(request, 'api_management/job_list.html', {
        'jobs': jobs_values,
        'in_progress_count': status_counter[ApiJob.IN_PROGRESS],
        'pending_count': status_counter[ApiJob.PENDING],
        'done_count': status_counter[ApiJob.DONE],
        'PENDING': ApiJob.PENDING,
        'IN_PROGRESS': ApiJob.IN_PROGRESS,
        'DONE': ApiJob.DONE,
    })


@permission_required('is_superuser')
def job_detail(request, job_id):
    """
    Display details of a particular job, including a table of its job units.
    """
    job = get_object_or_404(ApiJob, id=job_id)
    job_status = job.full_status()

    units = []
    for unit_obj in job.apijobunit_set.order_by('-order_in_parent'):

        # Here we assume it's a deploy job. If we expand the API to different
        # job types later, then this code has to become more flexible.
        request_json_strings = deploy_request_json_as_strings(unit_obj)

        units.append(dict(
            id=unit_obj.pk,
            type=unit_obj.internal_job.job_name,
            status=unit_obj.status,
            status_display=unit_obj.get_status_display(),
            request_json_strings=request_json_strings,
            result_message=unit_obj.internal_job.result_message,
        ))

    return render(request, 'api_management/job_detail.html', {
        'job': job,
        'job_status': job_status,
        'units': units,
        'PENDING': Job.Status.PENDING,
        'IN_PROGRESS': Job.Status.IN_PROGRESS,
        'SUCCESS': Job.Status.SUCCESS,
        'FAILURE': Job.Status.FAILURE,
    })
