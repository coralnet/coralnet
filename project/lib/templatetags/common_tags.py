# General-use custom template tags and filters.

import datetime
import json

from django import template
from django.conf import settings
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.utils.timesince import timesince

register = template.Library()


@register.simple_tag
def field_visibility_attrs(widget):
    """
    The passed widget may have attrs defining that its visibility
    toggles when a certain field is a certain value.
    This template tag echoes those attrs so that another element can
    use the same visibility logic.
    If neither attr is present, this just produces an empty string.
    """
    if hasattr(widget, 'attrs'):
        # Standard Widget
        widget_attrs = widget.attrs
    else:
        # Template context representation of a MultiWidget
        widget_attrs = widget['attrs']

    return mark_safe(' '.join([
        f'{attr_name}="{widget_attrs[attr_name]}"'
        for attr_name in [
            'data-visibility-control-field',
            'data-visibility-activating-values',
        ]
        if attr_name in widget_attrs
    ]))


# Usage: {% get_form_media form as form_media %}
@register.simple_tag
def get_form_media(form):
    return dict(js=form.media._js, css=form.media._css)


# jsonify
#
# Turn a Django template variable into a JSON string and return the result.
# mark_safe() is used to prevent escaping of quote characters
# in the JSON (so they stay as quotes, and don't become &quot;).
#
# Usage: <script> AnnotationToolHelper.init({{ labels|jsonify }}); </script>
#
# Basic idea from:
# http://djangosnippets.org/snippets/201/
@register.filter
def jsonify(obj):
    return mark_safe(json.dumps(obj))


@register.simple_tag
def get_maintenance_details():
    try:
        with open(settings.MAINTENANCE_DETAILS_FILE_PATH, 'r') as json_file:
            params = json.load(json_file)
            return dict(
                time=datetime.datetime.fromtimestamp(
                    params['timestamp'], datetime.timezone.utc),
                message=params['message'],
            )
    except IOError:
        return None


@register.filter
def time_is_past(datetime_obj):
    return datetime_obj < timezone.now()


@register.filter
def timedelta_display(delta: datetime.timedelta):
    """
    Display a timedelta using the same logic as the built-in timesince
    and timeuntil filters.
    Unfortunately that logic isn't isolated in a function, so we copy from
    the Django code.
    """
    arbitrary_date = datetime.datetime(2000, 1, 1, 0, 0, 0)
    return timesince(arbitrary_date, now=arbitrary_date+delta)


@register.filter
def truncate_float(f):
    """
    Truncate a float to an int.

    This filter is useful because:
    1. The default `floatformat` template filter only does rounding,
    not truncation
    2. f.__int__ in the template gets a TemplateSyntaxError:
    "Variables and attributes may not begin with underscores"
    """
    return int(f)
