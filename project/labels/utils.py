import re

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
