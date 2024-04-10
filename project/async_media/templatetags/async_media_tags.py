import re

from django import template
from django.template.exceptions import TemplateSyntaxError
from django.templatetags.static import static as to_static_path
from django.utils.html import escape

from ..utils import AsyncMediaBatch, AsyncPatch, AsyncThumbnail

register = template.Library()


RE_SIZE = re.compile(r'(\d+)x(\d+)$')


def parse_size(size):
    """
    Size variable can be either a tuple/list of two integers or a
    valid string.
    This is similar to how easy-thumbnails' template tag parses size.
    """
    if isinstance(size, str):
        m = RE_SIZE.match(size)
        if m:
            size = (int(m.group(1)), int(m.group(2)))
        else:
            raise TemplateSyntaxError(f"{size} is not a valid size.")
    return size


def media_async(media_item, media_batch_key, request):
    url = media_item.get_url()
    if url:
        # Media exists already.
        return dict(src=escape(url))

    # The media doesn't exist. Prepare to generate it asynchronously.
    batch = AsyncMediaBatch.get_existing(media_batch_key, request)
    batch.add_media_item(media_item)

    # Display a 'loading' image to begin with.
    src = to_static_path(
        f'img/placeholders/media-loading'
        f'__{media_item.width}x{media_item.height}.png')
    return dict(src=src, media_key=media_item.media_key)


@register.simple_tag
def async_media_batch_key(request):
    media_batch_key = AsyncMediaBatch.create(request).key
    return media_batch_key


@register.simple_tag
def patch_async(point, media_batch_key, request):
    """
    Image patch for an annotation point.
    """
    media_item = AsyncPatch(point_id=point.pk)
    return media_async(media_item, media_batch_key, request)


@register.simple_tag
def thumbnail_async(original_file, size, media_batch_key, request):
    """
    Alternate-size version of a media image.
    """
    size = parse_size(size)

    media_item = AsyncThumbnail(filepath=original_file.name, size=size)
    return media_async(media_item, media_batch_key, request)
