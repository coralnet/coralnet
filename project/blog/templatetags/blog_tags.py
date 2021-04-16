from django import template

from ..models import BlogPost

register = template.Library()


@register.simple_tag
def blog_latest_entries(count):
    """
    Return the <count> latest published blog entries, ordered latest-first.
    """
    return BlogPost.objects.get_published()[:count]
