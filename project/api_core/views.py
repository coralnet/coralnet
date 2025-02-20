from django.contrib.auth.models import User
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework.authtoken.views import (
    ObtainAuthToken as DefaultObtainAuthToken)
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView

from .models import ApiJob
from .parsers import JSONAPIParser
from .renderers import JSONAPIRenderer
from .utils import (
    BurstRateThrottle, get_max_active_jobs, SustainedRateThrottle)


class ObtainAuthToken(DefaultObtainAuthToken):
    """
    Subclass of rest-framework's token view, in order to:
    1. Add throttling, since the view doesn't have throttling by default:
    https://www.django-rest-framework.org/api-guide/authentication/#by-exposing-an-api-endpoint
    2. Use our custom parser, since the view defaults to DRF's JSON
    parser instead of using our parser settings.
    3. Use our custom renderer, since the view defaults to DRF's JSON
    renderer instead of using our renderer settings.
    """
    throttle_classes = [BurstRateThrottle, SustainedRateThrottle]
    parser_classes = [JSONAPIParser]
    renderer_classes = [JSONAPIRenderer]


class UserShow(APIView):
    """
    Show details for a user.
    """
    def get(self, request, username):
        # The user must exist and they must have been the requester.
        try:
            user = get_object_or_404(User, username=username)
            if user.pk != request.user.pk:
                raise Http404
        except Http404:
            detail = "You can only see details for the user you're logged in as"
            return Response(
                dict(errors=[dict(detail=detail)]),
                status=status.HTTP_404_NOT_FOUND)

        max_active_jobs = get_max_active_jobs(request.user)
        active_job_ids = (
            ApiJob.objects.active_for_user(request.user)
            .values_list('pk', flat=True)
        )

        recently_completed_max_shown = max_active_jobs * 2
        recently_completed_job_ids = (
            ApiJob.objects.recently_completed_for_user(request.user)
            .values_list('pk', flat=True)[:recently_completed_max_shown]
        )

        data = dict(
            active_jobs=[
                dict(type='jobs', id=str(job_id))
                for job_id in active_job_ids
            ],
            recently_completed_jobs=[
                dict(type='jobs', id=str(job_id))
                for job_id
                in recently_completed_job_ids
            ],
        )
        meta = dict(max_active_jobs=max_active_jobs)
        return Response(
            dict(data=data, meta=meta),
            status=status.HTTP_200_OK)
