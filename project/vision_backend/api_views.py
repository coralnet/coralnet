from __future__ import unicode_literals

from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404

from images.models import Source


def deploy(request, source_id):

    try:
        # Limit to public sources for now
        source = get_object_or_404(
            Source, id=source_id, visibility=Source.VisibilityTypes.PUBLIC)
    except Http404:
        return JsonResponse(
            dict(errors=[
                dict(title="No matching source found")
            ]),
            status=404
        )

    if request.method == 'GET':

        data = dict(
            name=source.name
        )
        return JsonResponse(dict(data=data))

    else:

        return JsonResponse(
            dict(errors=[
                dict(title="Unsupported request method")
            ]),
            status=400
        )
