from __future__ import unicode_literals

from django import template
from django.utils.safestring import mark_safe
from markdownx.utils import markdownify

register = template.Library()


@register.filter(name='markdown_to_html')
def markdown_to_html(input_markdown):
    """Convert the given markdown to HTML."""
    return mark_safe(markdownify(input_markdown))
