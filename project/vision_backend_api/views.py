from django.conf import settings
from django.http import Http404, UnreadablePostError
from django.shortcuts import get_object_or_404
from django.urls import reverse
from rest_framework.exceptions import ParseError
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView

from api_core.exceptions import ApiRequestDataError
from api_core.models import ApiJob, ApiJobUnit, UserApiLimits
from jobs.models import Job
from jobs.utils import schedule_job
from vision_backend.models import Classifier
from .forms import validate_deploy


class Deploy(APIView):
    """
    Request a classifier deployment on a specified set of images.
    """
    def post(self, request, classifier_id):

        # Check to see if we should throttle based on already-active jobs.

        active_job_ids = ApiJob.objects.active_ids_for_user(request.user)
        # Evaluate.
        active_job_ids = list(active_job_ids)

        try:
            # See if there's a user-specific limit.
            max_active_jobs = UserApiLimits.objects.get(
                user=request.user).max_active_jobs
        except UserApiLimits.DoesNotExist:
            # Else, use the default.
            max_active_jobs = settings.USER_DEFAULT_MAX_ACTIVE_API_JOBS

        if len(active_job_ids) >= max_active_jobs:
            ids = ', '.join([
                str(pk) for pk in active_job_ids[:max_active_jobs]])
            detail = (
                f"You already have {max_active_jobs} jobs active"
                f" (IDs: {ids})."
                f" You must wait until one of them finishes"
                f" before requesting another job."
            )
            return Response(
                dict(errors=[dict(detail=detail)]),
                status=status.HTTP_429_TOO_MANY_REQUESTS)

        # Check for invalid JSON.
        try:
            request.data
        except (ParseError, UnreadablePostError) as e:
            return Response(
                dict(errors=[dict(detail=str(e))]),
                status=status.HTTP_400_BAD_REQUEST)

        # The classifier must exist and be visible to the user.
        try:
            classifier = get_object_or_404(Classifier, id=classifier_id)
            if not classifier.source.visible_to_user(request.user):
                raise Http404
        except Http404:
            detail = "This classifier doesn't exist or is not accessible"
            return Response(
                dict(errors=[dict(detail=detail)]),
                status=status.HTTP_404_NOT_FOUND)

        try:
            images_data = validate_deploy(request.data)
        except ApiRequestDataError as e:
            return Response(
                dict(errors=[e.error_dict]),
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Create a deploy job object, which can be queried via DeployStatus.
        deploy_job = ApiJob(
            type='deploy',
            user=request.user)
        deploy_job.save()

        # Create job units to make it easier to track all the separate deploy
        # operations (one per image).
        for image_number, image_json in enumerate(images_data, 1):

            internal_job, _ = schedule_job(
                'classify_image', deploy_job.pk, image_number)
            job_unit = ApiJobUnit(
                parent=deploy_job,
                order_in_parent=image_number,
                internal_job=internal_job,
                request_json=dict(
                    classifier_id=int(classifier_id),
                    url=image_json['url'],
                    points=image_json['points'],
                ),
                # Size for deploy job units is the point count.
                size=len(image_json['points']),
            )
            job_unit.save()

        # Respond with the status endpoint's URL.
        return Response(
            status=status.HTTP_202_ACCEPTED,
            headers={
                'Location': reverse('api:deploy_status', args=[deploy_job.pk]),
            },
        )


class DeployStatus(APIView):
    """
    Check the status of an existing deployment job.
    """
    def get(self, request, job_id):
        # The job must exist and it must have been requested by the user.
        try:
            deploy_job = get_object_or_404(ApiJob, id=job_id, type='deploy')
            if deploy_job.user.pk != request.user.pk:
                raise Http404
        except Http404:
            detail = "This deploy job doesn't exist or is not accessible"
            return Response(
                dict(errors=[dict(detail=detail)]),
                status=status.HTTP_404_NOT_FOUND)

        job_status = deploy_job.full_status()

        if job_status['overall_status'] == ApiJob.DONE:
            return Response(
                status=status.HTTP_303_SEE_OTHER,
                headers={
                    'Location': reverse('api:deploy_result', args=[job_id]),
                },
            )
        else:
            data = [
                dict(
                    type="job",
                    id=str(job_id),
                    attributes=dict(
                        status=job_status['overall_status'],
                        successes=job_status['success_units'],
                        failures=job_status['failure_units'],
                        total=job_status['total_units']))]
            return Response(dict(data=data), status=status.HTTP_200_OK)


class DeployResult(APIView):
    """
    Check the result of a finished deployment job.
    """
    def get(self, request, job_id):
        # The job must exist and it must have been requested by the user.
        try:
            deploy_job = get_object_or_404(ApiJob, id=job_id, type='deploy')
            if deploy_job.user.pk != request.user.pk:
                raise Http404
        except Http404:
            detail = "This deploy job doesn't exist or is not accessible"
            return Response(
                dict(errors=[dict(detail=detail)]),
                status=status.HTTP_404_NOT_FOUND)

        if deploy_job.status == ApiJob.DONE:
            images_json = []

            # Report images in the same order that they were originally given
            # in the deploy request.
            for unit in deploy_job.apijobunit_set.order_by('order_in_parent'):

                if unit.status == Job.Status.SUCCESS:
                    # This has 'url' and 'points'
                    attributes = unit.result_json
                else:
                    # Error
                    attributes = dict(
                        url=unit.request_json['url'],
                        errors=[unit.result_message],
                    )

                images_json.append(dict(
                    type='image',
                    id=unit.request_json['url'],
                    attributes=attributes,
                ))

            data = dict(data=images_json)

            return Response(data, status=status.HTTP_200_OK)
        else:
            return Response(
                dict(errors=[
                    dict(detail="This job isn't finished yet")]),
                status=status.HTTP_409_CONFLICT)
