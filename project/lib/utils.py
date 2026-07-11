# General utility functions and classes can go here.

from contextlib import ContextDecorator
from contextvars import ContextVar
import datetime
from functools import cached_property
import random
import string
from typing import Any, Callable
import urllib.parse

from django.core.cache import cache
from django.core.paginator import Page, Paginator, EmptyPage, InvalidPage
from django.template.defaultfilters import date as date_template_filter
from django.utils import timezone

scoped_cache_context_var = ContextVar('scoped_cache', default=None)


class ContextScopedCache:
    """
    In-memory cache (key-value store) intended to last for the duration of a
    view, a task, or potentially some other context.
    Serves as an intermediary between application code and the disk-based
    Django cache, to reduce disk accesses.
    """
    def __init__(self):
        self._dict = dict()
        self._written_keys = dict()

    def get(self, key):
        if key not in self._dict:
            # Get value from the Django cache
            self._dict[key] = cache.get(key)
        return self._dict[key]

    def set(self, key, value, timeout):
        self._dict[key] = value
        # Should be written out to the Django cache at the end of the view
        self._written_keys[key] = timeout

    def write_to_django_cache(self):
        for key, timeout in self._written_keys.items():
            cache.set(key, self._dict[key], timeout=timeout)


class context_scoped_cache(ContextDecorator):
    def __enter__(self):
        # Initialize the cache
        self.token = scoped_cache_context_var.set(ContextScopedCache())

    def __exit__(self, *exc):
        # Write any updates from context scoped cache to Django cache
        scoped_cache = scoped_cache_context_var.get()
        scoped_cache.write_to_django_cache()

        # Revert to pre-token state
        scoped_cache_context_var.reset(self.token)


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
        # Function that recomputes the value.
        # Should take no args and return the value.
        compute_function: Callable[[], Any],
        # This interval (in seconds) determines when the cached value is
        # invalidated, thus forcing an on-demand computation if that's allowed.
        # If cache_update_interval is used and is smaller than this interval,
        # then invalidation won't happen unless the periodic job is having
        # trouble running on time.
        cache_timeout_interval: int,
        # Interval (in seconds) defining how often the value should be
        # updated through a periodic job.
        # This is just a bookkeeping field; this class does not actually
        # set up the periodic job. That must be done separately in a
        # tasks.py file (where it can be found by job auto-discovery).
        cache_update_interval: int | None = None,
        # If False, then on a cache miss, get() just returns None instead of
        # attempting to compute, and it's up to the caller to deal with the
        # lack of value accordingly. This should be False when on-demand
        # computing would be unreasonably long for a page that uses the value.
        on_demand_computation_ok: bool = True,
        # Cache in memory (with a ContextVar) for the duration of the
        # view or task to reduce repeat fetches from the Django cache.
        use_context_scoped_cache: bool = False,
    ):
        self.cache_key = cache_key
        self.compute_function = compute_function
        self.cache_timeout_interval = cache_timeout_interval

        if cache_update_interval is not None:
            self.cache_update_interval = datetime.timedelta(
                seconds=cache_update_interval)
        else:
            self.cache_update_interval = None
        self.on_demand_computation_ok = on_demand_computation_ok
        self.use_context_scoped_cache = use_context_scoped_cache

    def update(self):
        value = self.compute_function()
        if self.use_context_scoped_cache:
            scoped_cache = scoped_cache_context_var.get()
            scoped_cache.set(
                self.cache_key, value, self.cache_timeout_interval)
            scoped_cache_context_var.set(scoped_cache)
        else:
            # Use Django cache directly
            cache.set(
                key=self.cache_key, value=value,
                timeout=self.cache_timeout_interval,
            )

        return value

    def get(self):
        if self.use_context_scoped_cache:
            # We assume the context-scoped cache is active. There is
            # no silent non-cache fallback, because not using the
            # cache could have serious implications for performance.
            scoped_cache = scoped_cache_context_var.get()
            value = scoped_cache.get(self.cache_key)
        else:
            # Use Django cache directly
            value = cache.get(self.cache_key)

        if value is None and self.on_demand_computation_ok:
            # Compute value
            value = self.update()

        return value


# Cache intervals are commonly some number of days, so this constant can be
# useful when specifying intervals.
ONE_DAY_IN_SECONDS = 60*60*24


def date_display(dt):
    return date_template_filter(timezone.localtime(dt))


def datetime_display(dt):
    """
    Format string reference:
    https://docs.djangoproject.com/en/dev/ref/templates/builtins/#date
    """
    return date_template_filter(timezone.localtime(dt), 'N j, Y, P')


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


class ViewPage(Page):

    def __init__(self, args_besides_page, *args, **kwargs):
        # Request arguments besides 'page'. We'll preserve these in the
        # previous/next links.
        self.args_besides_page = args_besides_page
        super().__init__(*args, **kwargs)

    def previous_page_link(self):
        """Can use this in templates."""
        args = self.args_besides_page | {'page': self.previous_page_number()}
        return '?' + urllib.parse.urlencode(args)

    def next_page_link(self):
        """Can use this in templates."""
        args = self.args_besides_page | {'page': self.next_page_number()}
        return '?' + urllib.parse.urlencode(args)


class CustomPaginator(Paginator):

    def __init__(self, request_args, *args, count_limit=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.args_besides_page = {
            k: v for k, v in request_args.items() if k != 'page'}

        self.count_limit = count_limit

    def _get_page(self, *args, **kwargs):
        return ViewPage(self.args_besides_page, *args, **kwargs)

    @cached_property
    def count(self):
        c = getattr(self.object_list, "count", None)
        # See if we have a QuerySet, using conditional logic similar to
        # that of Paginator.count().
        if callable(c):
            if self.count_limit:
                queryset_to_count = self.object_list
                # Clear any ordering that was previously applied to this
                # QuerySet. It seems that having an ordering slows down the
                # counting process when it's a subquery that's being counted,
                # which may be the case when we apply a count limit.
                #
                # For example, at this point, queryset_to_count.query may be:
                # SELECT ... FROM "annotations_annotation"
                # WHERE "annotations_annotation"."image_id" IN (
                #   SELECT U0."id" FROM "images_image" U0 INNER JOIN
                #   "images_metadata" U2 ON (U0."id" = U2."image_id")
                #   WHERE (U0."source_id" = 13
                #   AND UPPER(U2."aux1"::text) = UPPER(Site1)))
                # ORDER BY ... ASC
                queryset_to_count = queryset_to_count.order_by()
                # Optimize by telling the database to stop counting
                # past a certain limit. We can use this in situations where
                # the user probably won't be too bothered about not knowing
                # the full count.
                queryset_to_count = queryset_to_count[:self.count_limit]
                return queryset_to_count.count()
        # If not a QuerySet, or no count limit, defer to superclass.
        return super().count

    def count_limit_reached(self):
        return self.count_limit and self.count == self.count_limit


def paginate(results, items_per_page, request_args, count_limit=None):
    """
    Helper for paginated views.
    Assumes the page number is in the GET parameter 'page'.
    """
    paginator = CustomPaginator(
        request_args, results, items_per_page, count_limit=count_limit)
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

    return page_results


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
