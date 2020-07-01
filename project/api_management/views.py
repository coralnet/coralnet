from __future__ import unicode_literals

from django.contrib.auth.decorators import permission_required
from django.shortcuts import get_object_or_404, render

from api_core.models import ApiJob, ApiJobUnit
from vision_backend_api.utils import deploy_request_json_as_strings


@permission_required('is_superuser')
def job_list(request):
    """
    Display a list of all API jobs.
    """
    pending_jobs = []
    in_progress_jobs = []
    done_jobs = []

    # Order jobs by progress status, then by decreasing primary key.
    for job in ApiJob.objects.all().order_by('-pk'):
        job_info = job.full_status()
        job_info['id'] = job.pk
        job_info['create_date'] = job.create_date
        job_info['user'] = job.user
        job_info['type'] = job.type

        if job_info['overall_status'] == ApiJob.PENDING:
            pending_jobs.append(job_info)
        elif job_info['overall_status'] == ApiJob.IN_PROGRESS:
            in_progress_jobs.append(job_info)
        else:
            done_jobs.append(job_info)

    return render(request, 'api_management/job_list.html', {
        'jobs': in_progress_jobs + pending_jobs + done_jobs,
        'in_progress_count': len(in_progress_jobs),
        'pending_count': len(pending_jobs),
        'done_count': len(done_jobs),
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
    for unit_obj in job.apijobunit_set.all().order_by('-pk'):

        # Here we assume it's a deploy job. If we expand the API to different
        # job types later, then this code has to become more flexible.
        request_json_strings = deploy_request_json_as_strings(unit_obj)

        if unit_obj.result_json:
            error_display = unit_obj.result_json.get('error', '')
        else:
            error_display = ''

        units.append(dict(
            id=unit_obj.pk,
            type=unit_obj.type,
            status=unit_obj.status,
            status_display=unit_obj.get_status_display(),
            request_json_strings=request_json_strings,
            error_display=error_display,
        ))

    return render(request, 'api_management/job_detail.html', {
        'job': job,
        'job_status': job_status,
        'units': units,
        'PENDING': ApiJobUnit.PENDING,
        'IN_PROGRESS': ApiJobUnit.IN_PROGRESS,
        'SUCCESS': ApiJobUnit.SUCCESS,
        'FAILURE': ApiJobUnit.FAILURE,
    })
