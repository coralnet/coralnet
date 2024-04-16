from django.conf import settings
from django.db.models import Count
from django.urls import reverse

from images.models import Source
from lib.utils import CacheableValue
from sources.utils import filter_out_test_sources


def compute_map_sources() -> list[dict[str, str|int]]:
    """
    As of 2023.11.15, this may take 2-4 seconds to run in production.
    """
    # Get all sources that have both latitude and longitude specified.
    # (In other words, leave out the sources that have either of them
    # blank, or both exactly 0.)
    map_sources_qs = (
        Source.objects
        .exclude(latitude='')
        .exclude(longitude='')
        .exclude(latitude='0', longitude='0')
    )
    # Skip test sources.
    map_sources_qs = filter_out_test_sources(map_sources_qs)
    # Skip small sources.
    map_sources_qs = map_sources_qs.annotate(image_count=Count('image'))
    map_sources_qs = map_sources_qs.exclude(
        image_count__lt=settings.MAP_IMAGE_COUNT_TIERS[0])

    map_sources = []

    for source in map_sources_qs:
        if source.is_public():
            source_type = 'public'
        else:
            source_type = 'private'

        if source.image_count < settings.MAP_IMAGE_COUNT_TIERS[1]:
            size = 1
        elif source.image_count < settings.MAP_IMAGE_COUNT_TIERS[2]:
            size = 2
        else:
            size = 3

        map_sources.append(dict(
            sourceId=source.id,
            latitude=source.latitude,
            longitude=source.longitude,
            type=source_type,
            size=size,
            detailBoxUrl=reverse('source_detail_box', args=[source.id]),
        ))

    return map_sources


cacheable_map_sources = CacheableValue(
    cache_key='map_sources',
    cache_update_interval=60*60*6,
    cache_timeout_interval=60*60*24*1,
    compute_function=compute_map_sources,
)
