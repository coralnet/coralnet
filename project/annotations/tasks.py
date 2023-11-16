from jobs.utils import job_runner
from .utils import cacheable_annotation_count


@job_runner(
    interval=cacheable_annotation_count.cache_update_interval,
)
def update_sitewide_annotation_count():
    count = cacheable_annotation_count.update()
    return f"Updated count to {count}"
