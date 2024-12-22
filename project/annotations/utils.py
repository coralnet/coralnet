from collections import defaultdict
from io import StringIO
import operator

from django.conf import settings
from django.urls import reverse

from accounts.utils import get_alleviate_user, get_robot_user, is_robot_user
from events.models import Event
from images.model_utils import PointGen
from images.models import Image
from lib.exceptions import FileProcessError
from lib.utils import CacheableValue
from sources.models import Source
from upload.utils import csv_to_dicts
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
    point_gen_type = PointGen.from_db_value(image.point_generation_method).type
    return (
        (not image_has_any_confirmed_annotations(image))
        and
        (point_gen_type != PointGen.Types.IMPORTED.value)
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
    user_id = int(anno_version.field_dict['user_id'])

    if get_robot_user().pk == user_id:

        # This check may be needed because Annotation didn't
        # originally save robot versions.
        if 'robot_version_id' not in anno_version.field_dict:
            return "(Robot, unknown version)"

        robot_version_id = anno_version.field_dict['robot_version_id']
        if not robot_version_id:
            return "(Robot, unknown version)"

        return Event.get_robot_display(robot_version_id, date_created)

    return Event.get_user_display(user_id)


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


def at_most_one_label_column(accepted_columns):
    label_columns = [
        c for c in accepted_columns
        if c in ["Label code", "Label ID", "Label"]]
    if len(label_columns) > 1:
        raise FileProcessError(
            f"CSV cannot have multiple columns specifying the label"
            f" ({', '.join(label_columns)})")


def annotations_csv_to_dict(
        csv_stream: StringIO, source: Source) -> dict[int, list[dict]]:
    """
    Returned dict has keys = image ids, and
    values = lists of dicts with keys row, column, (opt.) label).
    """
    row_dicts = csv_to_dicts(
        csv_stream,
        required_columns=dict(
            name="Name",
            row="Row",
            column="Column",
        ),
        # Two ways to specify the label: code or ID.
        # For backward compatibility with older CoralNet exports, the header
        # "Label" is also accepted, and interpreted the same as "Label code".
        optional_columns=dict(
            label_code="Label code",
            label_id="Label ID",
            label="Label",
        ),
        # Dupe point locations are allowed.
        unique_keys=[],
        # Don't specify the labels in more than one way.
        more_column_checks=at_most_one_label_column,
    )

    csv_annotations = defaultdict(list)

    for row_dict in row_dicts:
        # If 'label' exists, replace that legacy column name with the
        # current name 'label_code'.
        if 'label' in row_dict:
            row_dict['label_code'] = row_dict.pop('label')

        image_name = row_dict.pop('name')
        csv_annotations[image_name].append(row_dict)

    # So far we've checked the CSV formatting. Now check the validity
    # of the contents.
    csv_annotations = annotations_csv_verify_contents(csv_annotations, source)

    return csv_annotations


def annotations_csv_verify_contents(csv_annotations, source):
    """
    Argument dict is indexed by image name. We'll create a new dict indexed
    by image id, while verifying image existence, row, column, and label.
    """
    annotations = dict()

    labelset_ids_to_codes = source.labelset.global_pk_to_code_dict()
    labelset_codes_to_ids = source.labelset.code_to_global_pk_dict()

    for image_name, annotations_for_image in csv_annotations.items():
        try:
            img = Image.objects.get(metadata__name=image_name, source=source)
        except Image.DoesNotExist:
            # This filename isn't in the source. Just skip it
            # without raising an error. It could be an image the user is
            # planning to upload later, or an image they're not planning
            # to upload but are still tracking in their records.
            continue

        point_count = len(annotations_for_image)
        if point_count > settings.MAX_POINTS_PER_IMAGE:
            raise FileProcessError(
                f"For image {image_name}:"
                f" Found {point_count} points, which exceeds the"
                f" maximum allowed of {settings.MAX_POINTS_PER_IMAGE}")

        for point_number, point_dict in enumerate(annotations_for_image, 1):

            # Check that row/column are integers within the image dimensions.

            point_error_prefix = \
                f"For image {image_name}, point {point_number}:"

            row_str = point_dict['row']
            try:
                row = int(row_str)
                if row < 0:
                    raise ValueError
            except ValueError:
                raise FileProcessError(
                    point_error_prefix +
                    f" Row should be a non-negative integer, not {row_str}")

            column_str = point_dict['column']
            try:
                column = int(column_str)
                if column < 0:
                    raise ValueError
            except ValueError:
                raise FileProcessError(
                    point_error_prefix +
                    f" Column should be a non-negative integer,"
                    f" not {column_str}")

            if row > img.max_row:
                raise FileProcessError(
                    point_error_prefix +
                    f" Row value is {row}, but"
                    f" the image is only {img.original_height} pixels high"
                    f" (accepted values are 0~{img.max_row})")

            if column > img.max_column:
                raise FileProcessError(
                    point_error_prefix +
                    f" Column value is {column}, but"
                    f" the image is only {img.original_width} pixels wide"
                    f" (accepted values are 0~{img.max_column})")

            if point_dict.get('label_id'):
                try:
                    label_id = int(point_dict['label_id'])
                except ValueError:
                    raise FileProcessError(
                        point_error_prefix +
                        f" Label ID should be a positive integer,"
                        f" not {point_dict['label_id']}")

                if label_id not in labelset_ids_to_codes:
                    raise FileProcessError(
                        point_error_prefix +
                        f" No label of ID {label_id} found"
                        f" in this source's labelset")
            elif point_dict.get('label_code'):
                label_code = point_dict.pop('label_code')

                if label_code.lower() not in labelset_codes_to_ids:
                    raise FileProcessError(
                        point_error_prefix +
                        f" No label of code {label_code} found"
                        f" in this source's labelset")
                # We want point dicts with label_id instead of label_code
                # from here on out.
                point_dict['label_id'] = (
                    labelset_codes_to_ids[label_code.lower()])

        annotations[img.pk] = annotations_for_image

    if len(annotations) == 0:
        raise FileProcessError("No matching image names found in the source")

    return annotations


def annotations_preview(
        csv_annotations: dict[int, list],
        source: Source,
) -> tuple[list, dict]:

    table = []
    details = dict()
    total_csv_points = 0
    total_csv_annotations = 0
    num_images_with_existing_annotations = 0

    for image_id, points_list in csv_annotations.items():

        img = Image.objects.get(pk=image_id, source=source)
        preview_dict = dict(
            name=img.metadata.name,
            link=reverse('annotation_tool', kwargs=dict(image_id=img.pk)),
        )

        num_csv_points = len(points_list)
        total_csv_points += num_csv_points
        num_csv_annotations = sum(
            1 for point_dict in points_list
            if point_dict.get('label_id'))
        total_csv_annotations += num_csv_annotations
        preview_dict['createInfo'] = (
            f"Will create {num_csv_points} points,"
            f" {num_csv_annotations} annotations")

        num_existing_annotations = img.annotation_set.confirmed().count()
        if num_existing_annotations > 0:
            preview_dict['deleteInfo'] = (
                f"Will delete {num_existing_annotations} existing annotations")
            num_images_with_existing_annotations += 1

        table.append(preview_dict)

    details['numImages'] = len(csv_annotations)
    details['totalPoints'] = total_csv_points
    details['totalAnnotations'] = total_csv_annotations
    details['numImagesWithExistingAnnotations'] = \
        num_images_with_existing_annotations

    return table, details


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
