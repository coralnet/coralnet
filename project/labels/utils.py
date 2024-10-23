import math
import re

from django.conf import settings

from lib.utils import CacheableValue
from sources.models import Source
from .models import Label


def search_labels_by_text(search_value):
    # Replace non-letters/digits with spaces
    search_value = re.sub(r'[^A-Za-z0-9]', ' ', search_value)
    # Strip whitespace from both ends
    search_value = search_value.strip()
    # Replace multi-spaces with one space
    search_value = re.sub(r'\s{2,}', ' ', search_value)
    # Get space-separated tokens
    search_tokens = search_value.split(' ')
    # Discard blank tokens
    search_tokens = [t for t in search_tokens if t != '']

    if len(search_tokens) == 0:
        # No tokens of letters/digits. Return no results.
        return Label.objects.none()

    # Get the labels where the name has ALL of the search tokens.
    labels = Label.objects
    for token in search_tokens:
        labels = labels.filter(name__icontains=token)
    return labels


def is_label_editable_by_user(label, user):
    if user.has_perm('labels.change_label'):
        # Labelset committee members and superusers can edit all labels
        return True

    if label.verified:
        # Only committee/superusers can edit verified labels
        return False

    sources_using_label = \
        Source.objects.filter(labelset__locallabel__global_label=label) \
        .distinct()
    if not sources_using_label:
        # Labels not in any source can only be edited by the committee.
        # It's probably a corner case, but it's likely confusing for users
        # if they see they're able to edit such a label. And it's best if
        # free-for-all edit situations aren't even possible.
        return False

    for source in sources_using_label:
        if not user.has_perm(Source.PermTypes.ADMIN.code, source):
            # This label is used by a source that this user isn't an
            # admin of; therefore, can't edit the label
            return False

    # The user is admin of all 1+ sources using this label, and the label
    # isn't verified; OK to edit
    return True


def compute_label_details():
    """
    Details (which are worth caching) for all labels, including annotation
    counts and popularities.
    As of 2023/11, this may take 1.5 hours to run in production.

    Annotation count can take several seconds to compute for a single
    widely-used label.

    Caching the first page of random patches is good for two reasons:
    1) On the label detail page, random patch generation involves computing
    the page count of the entire annotation set, and thus involves at least
    computing the annotation count.
    2) We don't have to generate different patch images for different
    visitors of the label detail page, in most cases. Most folks will only
    look at the first page of patches (if anything).
    """
    labels = Label.objects.all()
    details = dict()

    for label in labels:

        source_count = label.locallabel_set.count()
        confirmed_annotation_count = label.annotation_set.confirmed().count()

        # This popularity formula accounts for:
        # - The number of sources using the label
        # - The number of confirmed annotations using the label
        #
        # Overall, it's not too nuanced, and could use further tinkering
        # at some point.
        raw_score = (
            source_count * math.sqrt(confirmed_annotation_count)
        )
        if raw_score == 0:
            popularity = 0
        else:
            # Map to a 0-100 scale.
            # The exponent determines the "shape" of the mapping.
            # -0.15 maps raw score of 10 to 29%, 100 to 50%,
            # 10000 to 75%, and 10000000 to 91%.
            popularity = 100 * (1 - raw_score**(-0.15))

        # List of annotation IDs to use for the first page of random patches
        # on the label detail page.
        random_patches_page_1 = list(
            label.annotation_set
            .order_by('?')
            .values_list('pk', flat=True)
            [:settings.LABEL_EXAMPLE_PATCHES_PER_PAGE]
        )

        details[label.pk] = dict(
            source_count=source_count,
            confirmed_annotation_count=confirmed_annotation_count,
            popularity=popularity,
            random_patches_page_1=random_patches_page_1,
        )

    return details


cacheable_label_details = CacheableValue(
    cache_key='label_details',
    compute_function=compute_label_details,
    cache_update_interval=60*60*24*7,
    cache_timeout_interval=60*60*24*30,
    on_demand_computation_ok=False,
    use_context_scoped_cache=True,
)


def label_confirmed_annotation_count(label_id):
    label_details = cacheable_label_details.get()
    if not label_details or label_id not in label_details:
        return 0
    return label_details[label_id]['confirmed_annotation_count']


def label_popularity(label_id):
    label_details = cacheable_label_details.get()
    if not label_details or label_id not in label_details:
        return 0
    return label_details[label_id]['popularity']
