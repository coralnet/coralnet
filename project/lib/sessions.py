import datetime

from django.contrib import messages
from django.http import HttpResponseRedirect
from django.urls import reverse


class SessionError(Exception):
    pass


def save_session_data(session, key, data):
    """
    Save data to session, then return a timestamp. This timestamp should be
    sent to the server by any subsequent request which wants to get this
    session data. Generally, the key verifies which page the session data is
    for, and the timestamp (which should have microsecond resolution)
    verifies that it's for a particular visit/request on that page.
    This ensures that nothing chaotic happens if a single user
    opens multiple browser tabs on session-using pages.

    An example use of sessions in CoralNet is to do a GET non-Ajax file-serve
    after a POST Ajax processing step. Lengthy processing is better as Ajax
    for browser responsiveness, and file serving is more natural as non-Ajax.
    """
    timestamp = str(datetime.datetime.now().timestamp())
    session[key] = dict(data=data, timestamp=timestamp)
    return timestamp


def get_session_data(key: str, request):
    """
    Requirements: session data must exist at `key`, and the timestamp
    stored there must match with the timestamp request arg.
    Returns the requested session data (and validates that it exists).
    """
    timestamp = request.GET.get('session_data_timestamp', None)
    # Can be None, or can be '' if it's from a form field that
    # didn't get filled in.
    if not timestamp:
        raise SessionError(
            "Request data doesn't have a session_data_timestamp."
            " This might be a bug."
            " If the problem persists, let us know on the forum."
        )

    session_value = request.session.pop(key, None)
    if not session_value:
        raise SessionError(
            "We couldn't find the expected data in your session."
            " Please try again."
            " If the problem persists, let us know on the forum."
        )

    if session_value['timestamp'] != timestamp:
        raise SessionError(
            "Session data timestamp didn't match."
            " Please try again."
            " If the problem persists, let us know on the forum."
        )

    return session_value['data']


def session_error_response(
        error, request, redirect_spec, prefix, view_kwargs):

    if isinstance(redirect_spec, str):
        error_url_name = redirect_spec
        url_args = []
    else:
        # list
        error_url_name, object_id_view_arg = redirect_spec
        url_args = [view_kwargs[object_id_view_arg]]
    error_redirect_url = reverse(error_url_name, args=url_args)

    messages.error(
        request,
        f"{prefix}: {str(error)}"
    )
    return HttpResponseRedirect(error_redirect_url)
