from django import template
from django.templatetags.static import static
from django.utils.safestring import mark_safe

from ..utils import label_popularity

register = template.Library()


@register.simple_tag
def popularity_bar(label, short=False):
    if label_popularity(label.pk) >= 30:
        color = 'green'
    else:
        color = 'red'

    if short:
        meter_class = 'meter short'
    else:
        meter_class = 'meter'

    # float -> int to truncate decimal, then int -> str
    bar_width = str(int(label_popularity(label.pk))) + '%'
    return mark_safe(
        '<div class="{meter_class}" title="{bar_width}">'
        '  <span class="{color}" style="width: {bar_width};"></span>'
        '</div>'.format(
            meter_class=meter_class, color=color, bar_width=bar_width)
    )


@register.simple_tag
def popularity_value(label):
    # We display popularity values with the decimal part truncated.
    return int(label_popularity(label.pk))


@register.simple_tag
def status_icon(label):
    if label.verified:
        icon_relative_path = 'img/label-icon-verified__16x16.png'
        alt_text = "Verified"
        title_text = "Verified"
    elif label.duplicate is not None:
        icon_relative_path = 'img/label-icon-duplicate__16x16.png'
        alt_text = "Duplicate"
        title_text = "Duplicate of {name}".format(name=label.duplicate.name)
    else:
        # This blank icon ensures that:
        # - The calcification icons line up well on the label list page.
        # - The 'label box' on add/remove labels is a consistent size.
        icon_relative_path = 'img/label-icon-neutral__16x16.png'
        alt_text = ""
        title_text = ""

    # Call the 'static' template tag's code to get the full path.
    icon_full_path = static(icon_relative_path)

    return mark_safe(
        '<img class="label-status-image" src="{src}" alt="{alt}"'
        ' title="{title}" />'.format(
            src=icon_full_path, alt=alt_text, title=title_text))
