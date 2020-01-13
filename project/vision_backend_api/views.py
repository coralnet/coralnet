from __future__ import unicode_literals

from django.http import Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView

from vision_backend.models import Classifier
from api_core.exceptions import ApiRequestDataError
from api_core.models import ApiJob, ApiJobUnit
from .forms import validate_deploy
from .tasks import deploy_extract_features


class Deploy(APIView):
    """
    Request a classifier deployment on a specified set of images.
    """
    throttle_scope = 'deploy'

    def post(self, request, classifier_id):
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
            cleaned_data = validate_deploy(request.POST)
        except ApiRequestDataError as e:
            return Response(
                dict(errors=[e.error_dict]),
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Create a deploy job object, which can be queried via DeployStatus.
        images_json = cleaned_data['images']
        deploy_job = ApiJob(
            type='deploy',
            user=request.user)
        deploy_job.save()

        # Create job units to make it easier to track all the separate deploy
        # operations (one per image).
        for image_index, image_json in enumerate(images_json):

            features_job_unit = ApiJobUnit(
                job=deploy_job,
                type='deploy_extract_features',
                request_json=dict(
                    classifier_id=int(classifier_id),
                    url=image_json['url'],
                    points=image_json['points'],
                    image_order=image_index))
            features_job_unit.save()

            deploy_extract_features.delay(features_job_unit.pk)

        # Return the status endpoint's URL.
        data = dict(
            links=dict(
                self=reverse('api:deploy_status', args=[deploy_job.pk])))
        return Response(dict(data=data), status=status.HTTP_202_ACCEPTED)


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

        job_units = deploy_job.apijobunit_set
        success_count = job_units.filter(
            type='deploy_classify', status=ApiJobUnit.SUCCESS).count()
        failure_count = job_units.filter(
            type='deploy_classify', status=ApiJobUnit.FAILURE).count()
        total_image_count = job_units.filter(
            type='deploy_extract_features').count()

        if not job_units.exclude(status=ApiJobUnit.PENDING).exists():
            # All units are still pending, so the job as a whole is pending
            job_status = ApiJob.PENDING
        elif success_count + failure_count < total_image_count:
            # Some units haven't finished yet, so the job isn't done yet
            job_status = ApiJob.WORKING
        else:
            job_status = ApiJob.DONE

        data = dict(
            status=job_status,
            classify_successes=success_count,
            classify_failures=failure_count,
            total=total_image_count)

        if job_status == ApiJob.DONE:
            data['location'] = reverse('api:deploy_result', args=[job_id])
            return Response(dict(data=data), status=status.HTTP_303_SEE_OTHER)
        else:
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

        classify_units = deploy_job.apijobunit_set.filter(
            type='deploy_classify')
        # If classify units were created, and none of them are pending/working,
        # then the job is done.
        job_done = (
            classify_units.exists()
            and
            not classify_units.filter(
                status__in=[ApiJobUnit.PENDING, ApiJobUnit.WORKING]).exists()
        )

        if job_done:
            images_json = []

            # Report images in the same order that they were originally given
            # in the deploy request.
            def sort_key(unit_):
                return unit_.request_json['image_order']

            for unit in sorted(classify_units, key=sort_key):
                images_json.append(unit.result_json)

            data = dict(images=images_json)

            return Response(dict(data=data), status=status.HTTP_200_OK)
        else:
            return Response(
                dict(errors=[
                    dict(detail="This job isn't finished yet")]),
                status=status.HTTP_409_CONFLICT)
