from jobs.utils import job_runner
from .utils import cacheable_map_sources


@job_runner(
    interval=cacheable_map_sources.cache_update_interval,
)
def update_map_sources():
    sources = cacheable_map_sources.update()
    return f"Updated with {len(sources)} map source(s)"
