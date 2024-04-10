import functools

from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from lib.utils import context_scoped_cache
from .exceptions import MediaRequestDenied
from .utils import AsyncMediaBatch


@require_POST
def start_media_generation_ajax(request):
    """
    Request generating a batch of thumbnails/patches.

    A key should have been provided by a previous view to identify this
    batch of media to be generated. Checking the key prevents us from
    getting DOSed by arbitrary generation requests.

    That previous view could have been a GET, and generating media should be
    done in a POST, which is why this separate view is responsible for
    kicking off media generation.
    """
    media_batch_key = request.POST.get('media_batch_key')
    if not media_batch_key:
        return JsonResponse(dict(error="No media batch key provided."))

    try:
        batch = AsyncMediaBatch.get_existing(media_batch_key, request)
    except MediaRequestDenied as e:
        return JsonResponse(dict(error=f"Media request denied: {e}"))

    if batch.has_started_media_generation:
        # Already started generation. Using the browser's Back button
        # could lead to this case. Whatever the cause, we don't need to
        # generate again. Return the media that have been generated thus far.
        return JsonResponse(dict(
            code='already_started_generating',
            mediaResults=batch.get_previous_media_results()))

    # Anything related to creating and starting Jobs should be done outside of
    # the view's transaction.
    # (non_atomic_requests() would've been simpler than on_commit(), but for
    # some reason the former wasn't working on this view.)
    transaction.on_commit(
        context_scoped_cache()(
            functools.partial(batch.start_media_generation, request.user)))

    return JsonResponse(dict(code='success'))


@require_GET
def media_poll_ajax(request):
    """
    A key should have been provided by a previous view to identify this
    batch of media to be generated. Checking the key ensures that people
    can't craft requests to get other people's private images.
    """
    media_batch_key = request.GET.get('media_batch_key')
    if not media_batch_key:
        return JsonResponse(dict(error="No media batch key provided."))

    try:
        batch = AsyncMediaBatch.get_existing(media_batch_key, request)
    except MediaRequestDenied as e:
        return JsonResponse(dict(error=f"Media request denied: {e}"))

    if len(batch.media) == 0:
        return JsonResponse(dict(
            error=f"Media request has already been collected"))

    results = batch.check_media_jobs()

    return JsonResponse(dict(mediaResults=results))
