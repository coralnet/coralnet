# General utility functions and classes can go here.

import datetime
import random
import string
from typing import Any, Callable
import urllib.parse

from django.core.cache import cache
from django.core.paginator import Paginator, EmptyPage, InvalidPage


class CacheableValue:
    """
    A value that's managed with the Django cache.
    Recommended to use this class for values that take a while to compute,
    especially if they're needed on commonly-visited pages.
    """
    def __init__(
        self,
        # The value's key to index into the Django cache.
        cache_key: str,
        # Interval (in seconds) defining how often the value should be
        # updated through a periodic job.
        # This is just a bookkeeping field; this class does not actually
        # set up the periodic job. That must be done separately in a
        # tasks.py file (where it can be found by job auto-discovery).
        cache_update_interval: int,
        # In case the periodic job is having trouble completing on time,
        # this interval (in seconds) determines when we'll force an update
        # of the value on-demand.
        cache_timeout_interval: int,
        # Function that recomputes the value.
        # Should take no args and return the value.
        compute_function: Callable[[], Any],
    ):
        self.cache_key = cache_key
        self.cache_update_interval = datetime.timedelta(
            seconds=cache_update_interval)
        self.cache_timeout_interval = cache_timeout_interval
        self.compute_function = compute_function

    def update(self):
        value = self.compute_function()
        cache.set(
            key=self.cache_key, value=value,
            timeout=self.cache_timeout_interval,
        )
        return value

    def get(self):
        value = cache.get(self.cache_key)
        if value is None:
            value = self.update()
        return value


def filesize_display(num_bytes):
    """
    Return a human-readable filesize string in B, KB, MB, or GB.

    TODO: We may want an option here for number of decimal places or
    sig figs, since it's used for filesize limit displays. As a limit
    description, '30 MB' makes more sense than '30.00 MB'.
    """
    KILO = 1024
    MEGA = 1024 * 1024
    GIGA = 1024 * 1024 * 1024

    if num_bytes < KILO:
        return "{n} B".format(n=num_bytes)
    if num_bytes < MEGA:
        return "{n:.2f} KB".format(n=num_bytes / KILO)
    if num_bytes < GIGA:
        return "{n:.2f} MB".format(n=num_bytes / MEGA)
    return "{n:.2f} GB".format(n=num_bytes / GIGA)


def paginate(results, items_per_page, request_args):
    """
    Helper for paginated views.
    Assumes the page number is in the GET parameter 'page'.
    """
    paginator = Paginator(results, items_per_page)
    request_args = request_args or dict()

    # Make sure page request is an int. If not, deliver first page.
    try:
        page = int(request_args.get('page', '1'))
    except ValueError:
        page = 1

    # If page request is out of range, deliver last page of results.
    try:
        page_results = paginator.page(page)
    except (EmptyPage, InvalidPage):
        page_results = paginator.page(paginator.num_pages)

    # We'll often want a string of the other query args for building the
    # next/previous page links.
    other_args = {k: v for k, v in request_args.items() if k != 'page'}
    query_string = urllib.parse.urlencode(other_args)

    return page_results, query_string


def rand_string(num_of_chars):
    """
    Generates a string of lowercase letters and numbers.

    If we generate filenames randomly, it's harder for people to guess
    filenames and type in their URLs directly to bypass permissions.
    With 10 characters for example, we have 36^10 = 3 x 10^15 possibilities.
    """
    return ''.join(
        random.choice(string.ascii_lowercase + string.digits)
        for _ in range(num_of_chars))


def save_session_data(session, key, data):
    """
    Save data to session, then return a timestamp. This timestamp should be
    sent to the server by any subsequent request which wants to get this
    session data. Generally, the key verifies which page the session data is
    for, and the timestamp verifies that it's for a particular visit/request
    on that page. This ensures that nothing chaotic happens if a single user
    opens multiple browser tabs on session-using pages.

    An example use of sessions in CoralNet is to do a GET non-Ajax file-serve
    after a POST Ajax processing step. Lengthy processing is better as Ajax
    for browser responsiveness, and file serving is more natural as non-Ajax.
    """
    timestamp = str(datetime.datetime.now().timestamp())
    session[key] = dict(data=data, timestamp=timestamp)
    return timestamp
