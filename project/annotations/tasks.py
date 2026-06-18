from jobs.utils import job_runner
from .model_utils import cacheable_annotation_hash_salt, scrambled_sort_hash
from .models import Annotation
from .utils import cacheable_annotation_count


@job_runner(
    interval=cacheable_annotation_count.cache_update_interval,
)
def update_sitewide_annotation_count():
    count = cacheable_annotation_count.update()
    return f"Updated count to {count}"


# Django default for QuerySet.iterator() chunk size.
ANNOTATION_CHUNK_SIZE = 2000


@job_runner(
    interval=cacheable_annotation_hash_salt.cache_update_interval,
)
def update_annotation_scrambled_sort_keys():
    salt = cacheable_annotation_hash_salt.update()

    # Update scrambled_sort_key of all Annotations.
    # We retrieve Annotations in chunks (not all at once) to avoid OOM,
    # and update them in chunks (not individually) for speed.
    anno_chunk = []
    count = 0

    for anno in Annotation.objects.all().iterator(
        chunk_size=ANNOTATION_CHUNK_SIZE
    ):
        anno.scrambled_sort_key = scrambled_sort_hash(anno)
        anno_chunk.append(anno)
        if len(anno_chunk) >= ANNOTATION_CHUNK_SIZE:
            num_updated = Annotation.objects.bulk_update(
                anno_chunk, ['scrambled_sort_key'])
            count += num_updated
            anno_chunk = []

    if len(anno_chunk) > 0:
        # Last chunk
        num_updated = Annotation.objects.bulk_update(
            anno_chunk, ['scrambled_sort_key'])
        count += num_updated

    return (
        f"Updated annotation scrambled-sort salt to {salt},"
        f" and updated {count} scrambled_sort_key values"
    )
