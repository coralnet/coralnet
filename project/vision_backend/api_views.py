from __future__ import unicode_literals

from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView

from images.models import Source


class Deploy(APIView):

    def post(self, request, source_id):
        try:
            # Limit to public sources for now
            source = get_object_or_404(
                Source, id=source_id, visibility=Source.VisibilityTypes.PUBLIC)
        except Http404:
            return Response(
                dict(errors=[
                    dict(title="No matching source found")
                ]),
                status=status.HTTP_404_NOT_FOUND,
            )

        data = dict(
            name=source.name
        )
        return Response(dict(data=data))
