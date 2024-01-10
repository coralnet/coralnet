from django.conf import settings
import numpy as np
from spacer.data_classes import ValResults
from spacer.extract_features import (
    DummyExtractor,
    EfficientNetExtractor,
    FeatureExtractor,
    VGG16CaffeExtractor,
)
from spacer.messages import DataLocation

from images.models import Point, Source
from jobs.utils import queue_job
from .common import Extractors
from .confmatrix import ConfMatrix
from .models import Score


def acc(gt, est):
    """
    Calculate the accuracy of (agreement between) two interger valued list.
    """
    if len(gt) < 1:
        return 1
    else:
        return sum([(g == e) for (g, e) in zip(gt, est)]) / len(gt)


def get_label_scores_for_point(point, ordered=False):
    """
    :param point: The Point object to get label scores for. Only the top
        NBR_SCORES_PER_ANNOTATION scores are available for each point.
    :param ordered: If True, return the scores in descending order of score
        value. If False, return in arbitrary order (for performance).
    :return: {'label': <label code>, 'score': <score number>} for each Score
        available for this Point.
    """
    scores = Score.objects.filter(point=point)
    if ordered:
        scores = scores.order_by('-score')
    return [
        {'label': score.label_code, 'score': score.score}
        for score in scores
    ]


def get_label_scores_for_image(image_id):
    """
    Return all the saved label scores for an image in this format:
    {1: [{'label': 'Acrop', 'score': 14},
         {'label': 'Porit', 'score': 21},
         ...],
     2: [...], ...}
    Where the top-level dict's keys are the point numbers.
    """
    lpdict = {}
    for point in Point.objects.filter(image_id=image_id).order_by('id'):
        lpdict[point.point_number] = get_label_scores_for_point(point)
    return lpdict


MAX_PLOT_POINTS = 250


def get_alleviate(estlabels, gtlabels, scores):
    """
    Calculate alleviation line-plot data based on the given
    classifier evaluation results.
    For various confidence thresholds x (up to MAX_PLOT_POINTS values)
    representative of `scores`, calculates:
    1. The classifier's accuracy among its predictions scored as
       x% or higher
    2. The ratio of predictions (over total predictions) scored as x% of higher
    """
    if not len(estlabels) == len(gtlabels) or \
            not len(estlabels) == len(scores):
        raise ValueError('all inputs must have the same length')

    if len(estlabels) == 0:
        raise ValueError('inputs must have length > 0')
    
    # convert to numpy for easy indexing
    scores = np.asarray(scores)
    gtlabels = np.asarray(gtlabels, dtype=int)
    estlabels = np.asarray(estlabels, dtype=int)
    
    # Figure out what confidence thresholds to add plot points for.

    ths = sorted(scores)

    # Include confidence thresholds slightly lower than the minimum
    # (a data point with 100% ratio of predictions) and slightly higher
    # than the maximum (a data point with 0% ratio of predictions).
    ths.insert(0, max(min(ths) - 0.01, 0))
    ths.append(min(max(ths) + 0.01, 1.00))

    # Convert back to numpy.
    ths = np.asarray(ths)
    # Cap at MAX_PLOT_POINTS, taking evenly-distributed points if there are
    # more than that.
    if len(ths) > MAX_PLOT_POINTS:
        ths = ths[np.linspace(0, len(ths) - 1, MAX_PLOT_POINTS, dtype=int)]
    
    # do the actual sweep.
    accs, ratios = [], []
    for th in ths:
        keep_ind = scores > th
        this_acc = acc(estlabels[keep_ind], gtlabels[keep_ind])
        accs.append(round(100 * this_acc, 1))
        ratios.append(round(100 * np.sum(keep_ind) / len(estlabels), 1))
    ths = [round(100 * th, 1) for th in ths]
    
    return accs, ratios, ths


def list_no_dupes_preserving_order(iterable):
    seen = set()
    lst = []
    for element in iterable:
        if element in seen:
            continue
        lst.append(element)
        seen.add(element)
    return lst


def map_labels(labellist, label_mapping):
    """
    Helper function to map integer labels to new labels.
    """
    old_labelset = list(label_mapping.keys())
    new_labelset = list_no_dupes_preserving_order(label_mapping.values())
    labelset_index_mapping = {
        old_labelset.index(old_label): new_labelset.index(new_label)
        for old_label, new_label in label_mapping.items()
    }

    labellist = np.asarray(labellist, dtype=int)
    newlist = -1 * np.ones(len(labellist), dtype=int)
    for key in labelset_index_mapping.keys():
        newlist[labellist == key] = labelset_index_mapping[key]
    return list(newlist)


def labelset_mapper(
        labelmode: str, labelset: list[int], source: Source) -> dict[int, str]:
    """
    Prepares mapping function and labelset names to inject in confusion matrix.
    labelset ordering is preserved in the returned mapping's ordering.
    """
    unordered_label_mapping = dict()

    if labelmode == 'full':
        # Use the label's full name (length-limited) with code in parentheses.

        labelset_values = source.labelset.locallabel_set.values(
            'global_label__id', 'global_label__name', 'code')

        for label_values in labelset_values:
            label_id = label_values['global_label__id']
            if label_id not in labelset:
                continue

            full_name = label_values['global_label__name']
            if len(full_name) > 30:
                display_name = full_name[:27] + '...'
            else:
                display_name = full_name
            short_code = label_values['code']
            unordered_label_mapping[label_id] = \
                f"{display_name} ({short_code})"

    elif labelmode == 'func':
        # Use functional groups.

        labelset_values = source.labelset.locallabel_set.values(
            'global_label__id', 'global_label__group__name')

        for label_values in labelset_values:
            label_id = label_values['global_label__id']
            if label_id not in labelset:
                continue

            unordered_label_mapping[label_id] = \
                label_values['global_label__group__name']
    
    else:
        raise ValueError(f"labelmode {labelmode} not recognized")

    # Restore the original ordering (dict ordering is defined by insertion
    # order).
    label_mapping = dict()
    for label_id in labelset:
        label_mapping[label_id] = unordered_label_mapping[label_id]

    return label_mapping


def confmatrix_from_valresults(
        valres: ValResults,
        # Mapping from integer-represented labels in valresults to
        # displayed labels on the confusion matrix.
        # This serves two purposes: human readability, and the option to
        # group multiple labels into a single confusion-matrix label.
        label_mapping: dict[int, str] = None,
        # Only include points where the prediction's confidence level
        # (0-100) is higher than this.
        confidence_threshold: int = 0,
        # Dimension size cap for the matrix.
        # If there are more confusion matrix labels than this, the remaining
        # ones are aggregated into an 'Other' label.
        max_display_labels: int = 50):

    if label_mapping:
        labelset = list_no_dupes_preserving_order(label_mapping.values())
        gt = map_labels(valres.gt, label_mapping)
        est = map_labels(valres.est, label_mapping)
    else:
        labelset = valres.classes
        gt = valres.gt
        est = valres.est

    # Initialize confusion matrix.
    cm = ConfMatrix(len(labelset), labelset=labelset)

    # Add data-points above the threshold.
    cm.add_select(gt, est, valres.scores, confidence_threshold / 100)

    # Sort by label frequency, highest first.
    cm.sort()

    if cm.nclasses > max_display_labels:
        cm.cut(max_display_labels)

    return cm


def myfmt(r):
    """Helper function to format numpy outputs"""
    return "%.0f" % (r,)


def confmatrix_to_csv(cm, csv_writer):
    vecfmt = np.vectorize(myfmt)
    for enu, classname in enumerate(cm.labelset):
        row = [classname]
        row.extend(vecfmt(cm.cm[enu, :]))
        csv_writer.writerow(row)


def clear_features(image):
    """
    Clears features for image. Call this after any change that affects
    the image point locations. E.g:
    Re-generate point locations.
    Change annotation area.
    Add new points.
    """
    image.refresh_from_db()

    features = image.features
    features.extracted = False
    features.save()


def reset_features(image):
    clear_features(image)
    # Try to re-extract features
    queue_source_check(image.source_id)


def queue_source_check(source_id, delay=None):
    """
    Site views should generally call this function if they want to initiate
    any feature extraction, training, or classification.
    They should not call those three tasks directly. Let check_source()
    decide what needs to be run in what order.

    Site views generally shouldn't worry about specifying a delay, since this
    check_source Job only becomes visible to huey tasks when the view
    finishes its transaction. However, if desired, they can specify a delay.
    """
    return queue_job(
        'check_source',
        source_id,
        source_id=source_id,
        delay=delay,
    )


def get_extractor(extractor_choice: Extractors) -> FeatureExtractor:
    """
    For simplicity, the only extractor files supported here are the ones
    living in S3. So if not using AWS credentials, then need to use the
    dummy extractor.
    """
    match extractor_choice:
        case Extractors.EFFICIENTNET.value:
            return EfficientNetExtractor(
                data_locations=dict(
                    weights=DataLocation(
                        storage_type='s3',
                        key='efficientnet_b0_ver1.pt',
                        bucket_name=settings.EXTRACTORS_BUCKET,
                    ),
                ),
                data_hashes=dict(
                    weights='c3dc6d304179c6729c0a0b3d4e60c728'
                            'bdcf0d82687deeba54af71827467204c',
                ),
            )
        case Extractors.VGG16.value:
            return VGG16CaffeExtractor(
                data_locations=dict(
                    definition=DataLocation(
                        storage_type='s3',
                        key='vgg16_coralnet_ver1.deploy.prototxt',
                        bucket_name=settings.EXTRACTORS_BUCKET,
                    ),
                    weights=DataLocation(
                        storage_type='s3',
                        key='vgg16_coralnet_ver1.caffemodel',
                        bucket_name=settings.EXTRACTORS_BUCKET,
                    ),
                ),
                data_hashes=dict(
                    definition='7e0d1f6626da0dcfd00cbe62291b2c20'
                               '626eb7dacf2ba08c5eafa8a6539fad19',
                    weights='fb83781de0e207ded23bd42d7eb6e75c'
                            '1e915a6fbef74120f72732984e227cca',
                ),
            )
        case Extractors.DUMMY.value:
            return DummyExtractor()
        case _:
            assert f"{extractor_choice} isn't a supported extractor"
