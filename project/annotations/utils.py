import datetime
import operator

from django.contrib.auth.models import User
from django.utils import timezone
from accounts.utils import is_robot_user, get_alleviate_user
from images.model_utils import PointGen
from lib.utils import CacheableValue
from .models import Annotation


def image_has_any_confirmed_annotations(image):
    """
    Return True if the image has at least one confirmed Annotation.
    Return False otherwise.
    """
    return image.annotation_set.confirmed().exists()


def image_annotation_area_is_editable(image):
    """
    Returns True if the image's annotation area is editable; False otherwise.
    The annotation area is editable only if:
    (1) there are no confirmed annotations for the image yet, and
    (2) the points are not imported.
    """
    point_gen_method = PointGen.db_to_args_format(image.point_generation_method)
    return (
        (not image_has_any_confirmed_annotations(image))
        and
        (point_gen_method['point_generation_type'] != PointGen.Types.IMPORTED)
    )


def label_ids_with_confirmed_annotations_in_source(source):
    """
    Get an iterable of label IDs which have at least one confirmed annotation
    in the given source.
    """
    values = source.annotation_set.confirmed().values_list(
        'label_id', flat=True).distinct()
    return list(values)


def get_annotation_user_display(anno):
    """
    anno - an annotations.Annotation model.

    Returns a string representing the user who made the annotation.
    """
    if not anno.user:
        return "(Unknown user)"

    elif is_robot_user(anno.user):
        if not anno.robot_version:
            return "(Robot, unknown version)"
        return "Robot {v}".format(v=anno.robot_version)

    else:
        return anno.user.username


def get_annotation_version_user_display(anno_version, date_created):
    """
    anno_version - a reversion.Version model; a previous or current version
    of an annotations.Annotation model.
    date_created - creation date of the Version.

    Returns a string representing the user who made the annotation.
    """
    user_id = anno_version.field_dict['user_id']
    user = User.objects.get(pk=user_id)

    if not user:
        return "(Unknown user)"

    elif is_robot_user(user):
        # This check may be needed because Annotation didn't
        # originally save robot versions.
        if 'robot_version_id' not in anno_version.field_dict:
            return "(Robot, unknown version)"

        robot_version_id = anno_version.field_dict['robot_version_id']
        if not robot_version_id:
            return "(Robot, unknown version)"

        # On this date/time in UTC, CoralNet alpha had ended and CoralNet beta
        # robot runs had not yet started.
        beta_start_dt_naive = datetime.datetime(2016, 11, 20, 2)
        beta_start_dt = timezone.make_aware(
            beta_start_dt_naive, datetime.timezone.utc)

        if date_created < beta_start_dt:
            # Alpha
            return "Robot alpha-{v}".format(v=robot_version_id)

        # Beta (versions had reset, hence the need for alpha/beta distinction)
        return "Robot {v}".format(v=robot_version_id)

    else:
        return user.username


def apply_alleviate(img, label_scores_all_points):
    """
    Apply alleviate to a particular image: auto-accept top machine suggestions
    based on the source's confidence threshold.

    :param img: the Image to apply Alleviate to.
    :param label_scores_all_points: the machine's assigned label scores for
      each point of the image. These are confidence scores out of 100,
      like the source's confidence threshold.
    :return: nothing.
    """
    source = img.source
    
    if source.confidence_threshold > 99:
        return

    alleviate_was_applied = False

    for anno in img.annotation_set.unconfirmed():
        pt_number = anno.point.point_number
        label_scores = label_scores_all_points[pt_number]
        descending_scores = sorted(
            label_scores, key=operator.itemgetter('score'), reverse=True)
        top_score = descending_scores[0]['score']
        top_confidence = top_score

        if top_confidence >= source.confidence_threshold:
            # Save the annotation under the username Alleviate, so that it's no
            # longer a robot annotation.
            anno.user = get_alleviate_user()
            anno.save()
            alleviate_was_applied = True

    if alleviate_was_applied:
        # Ensure that the last-annotation display on the page is up to date.
        img.annoinfo.refresh_from_db()


def compute_sitewide_annotation_count():
    """
    Count of total annotations on the entire site. As of
    2018.08.15, this may take about 35 seconds to run in production.
    """
    return Annotation.objects.all().count()


cacheable_annotation_count = CacheableValue(
    cache_key='sitewide_annotation_count',
    cache_update_interval=60*60*24*1,
    cache_timeout_interval=60*60*24*30,
    compute_function=compute_sitewide_annotation_count,
)
