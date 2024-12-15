from django.conf import settings

from images.models import Metadata
from images.utils import get_aux_field_names, get_aux_label


def metadata_field_names_to_labels(source):
    """
    Get a dict of Metadata field names to field labels.
    e.g. 'photo_date': "Date", 'aux1': "Site", 'camera': "Camera", ...
    Note that dicts are sorted based on insertion order since Python 3.7.
    """
    d = dict(
        (field_name, Metadata._meta.get_field(field_name).verbose_name)
        for field_name
        in Metadata.EDIT_FORM_FIELDS
    )
    # Instead of "Aux1" for field aux1, use the source specified label,
    # e.g. "Site"
    for num, aux_field_name in enumerate(get_aux_field_names(), 1):
        d[aux_field_name] = get_aux_label(source, num)
    return d


def aux_label_name_collisions(source):
    """
    See if the given source's auxiliary metadata field labels have
    name collisions with (1) built-in metadata fields, or (2) each other.
    Return a list of the names which appear more than once.
    Comparisons are case insensitive.
    """
    field_names_to_labels = metadata_field_names_to_labels(source)
    field_labels_lower = [
        label.lower() for label in field_names_to_labels.values()]

    dupe_labels = [
        label for label in field_labels_lower
        if field_labels_lower.count(label) > 1
    ]
    return dupe_labels


def filter_out_test_sources(source_queryset):
    for possible_test_substring in settings.LIKELY_TEST_SOURCE_NAMES:
        source_queryset = source_queryset.exclude(name__icontains=possible_test_substring)
    return source_queryset
