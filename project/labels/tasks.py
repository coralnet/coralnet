from jobs.utils import job_runner
from .utils import cacheable_label_details


@job_runner(interval=cacheable_label_details.cache_update_interval)
def update_label_details():
    label_details = cacheable_label_details.update()
    return f"Updated details for all {len(label_details)} label(s)"
