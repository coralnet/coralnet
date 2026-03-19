import datetime
import random

from django.conf import settings
from django.db.models import Count, Expression, F, OrderBy, Q, Value
from django.db.models.lookups import Exact, GreaterThan, IsNull, LessThan

from accounts.utils import get_alleviate_user
from annotations.model_utils import AnnotationArea
from lib.utils import CacheableValue
from sources.models import Source
from .model_utils import PointGen
from .models import Image, Metadata, Point


def find_dupe_image(source, image_name):
    """
    Sees if the given source already has an image with this name.

    If a duplicate image was found, returns that duplicate.
    If no duplicate was found, returns None.
    """
    try:
        # Case insensitive name search.
        metadata = Metadata.objects.get(
            source=source, name__iexact=image_name)
    except Metadata.DoesNotExist:
        return None
    else:
        return metadata.image


def _get_next_objects_queryset(current_object, queryset):
    """
    Get the object that are ordered after current_object, based on the
    queryset's ordering.
    """
    queryset_model_class = queryset.model
    assert isinstance(
        current_object, queryset_model_class), "Don't mix and match models"

    # Start this Q object out as 'always False' because we want to make this
    # the starting value of an 'OR' reduce chain.
    filter_q = Q(Value(False))
    # Start this Q object out as 'always True' because we want to make this
    # the starting value of an 'AND' reduce chain.
    previous_args_equal_q = Q(Value(True))

    # query.order_by example: ['metadata__name', 'pk']
    #
    # The query we want gets more complicated depending on the number of
    # order_by args:
    # 1 arg: arg1 greater
    # 2 args: arg1 greater OR (arg1 equal AND arg2 greater)
    # 3 args: arg1 greater OR (arg1 equal AND arg2 greater)
    #   OR (arg1 equal AND arg2 equal AND arg3 greater)
    # Etc.
    for ordering_arg in queryset.query.order_by:

        if isinstance(ordering_arg, Expression):
            if isinstance(ordering_arg, OrderBy):
                # OrderBy Expression
                descending = ordering_arg.descending
                ordering_expr = ordering_arg.expression
            else:
                # Other Expression
                descending = False
                ordering_expr = ordering_arg
        else:
            # str
            descending = ordering_arg.startswith('-')
            ordering_field = ordering_arg.lstrip('-')
            # Convert to Expression
            ordering_expr = F(ordering_field)

        if not queryset.query.standard_ordering:
            # The queryset's reverse() method was called.
            descending = not descending

        current_object_ordering_value = (
            queryset_model_class.objects.filter(pk=current_object.pk)
            .values_list(ordering_expr, flat=True)[0]
        )

        if current_object_ordering_value is None:
            # Nullable fields have a complication: we can't specify
            # `...__gt=None` as a filter kwarg. That gets
            # `ValueError: Cannot use None as a query value`.
            # So instead we'll use the fact that None is ordered after all
            # non-None values. Thus, 'greater than None' means no possible
            # values, and 'less than None' means all non-None values.
            if descending:
                # 'less than None' (all non-None values)
                current_arg_after_q = Q(IsNull(ordering_expr, False))
            else:
                # 'greater than None' (always False)
                current_arg_after_q = Q(Value(False))

            current_arg_equal_q = Q(IsNull(ordering_expr, True))
        else:
            if descending:
                # 'less than current value'
                current_arg_after_q = Q(
                    LessThan(ordering_expr, current_object_ordering_value))
            else:
                # 'greater than current value' (greater value or None)
                current_arg_after_q = (
                    Q(GreaterThan(ordering_expr, current_object_ordering_value))
                    |
                    Q(IsNull(ordering_expr, True)))

            current_arg_equal_q = Q(
                Exact(ordering_expr, current_object_ordering_value))

        filter_q = filter_q | (previous_args_equal_q & current_arg_after_q)

        previous_args_equal_q = previous_args_equal_q & current_arg_equal_q

    return queryset.filter(filter_q)


def get_next_object(current_object, queryset, wrap=False):
    """
    Get the next object in the queryset, relative to current_object.
    queryset should already be ordered, with an unambiguous ordering
    (no ties).

    If wrap is True, then the definition of 'next' is extended to allow
    wrapping from the last object to the first.

    If there is no next object, return None.
    """
    next_objects = _get_next_objects_queryset(current_object, queryset)

    if next_objects.exists():
        return next_objects[0]
    elif wrap:
        # No matching objects after this object, so we wrap around
        # to the first object. Assuming we're not AT the first object.
        first_object = queryset[0]
        if first_object.pk == current_object.pk:
            return None
        else:
            return first_object
    else:
        # No matching objects after this object, and we're not allowed to wrap.
        return None


def get_prev_object(current_object, queryset, wrap=False):
    """
    Get the previous object in the queryset, relative to current_object.
    """
    # Finding the previous object is equivalent to
    # finding the next object in the reverse queryset.
    return get_next_object(current_object, queryset.reverse(), wrap)


def get_image_order_placement(current_image, image_queryset):
    prev_images = _get_next_objects_queryset(
        current_image, image_queryset.reverse())

    # e.g. if there's 4 images that are ordered before the current image,
    # then we return 5
    return prev_images.count() + 1


def metadata_obj_to_dict(metadata):
    """
    Go from Metadata DB object to metadata dict.
    """
    return dict((k, getattr(metadata, k)) for k in Metadata.EDIT_FORM_FIELDS)


def delete_images(image_queryset):
    """
    Delete Image objects, and return the number that were actually deleted.

    We DON'T delete the original image file just yet, because if we did,
    then a subsequent exception in this request/response cycle would leave
    us in an inconsistent state. Leave original image deletion to a
    management command or cronjob.

    It would be reasonable to delete easy-thumbnails' image thumbnails now,
    but best left for later again, for better user-end responsiveness.
    """
    # We call delete() on the queryset rather than the individual
    # objects for faster performance.
    _, num_objects_deleted = image_queryset.delete()
    delete_count = num_objects_deleted.get('images.Image', 0)

    return delete_count


def delete_image(img: Image):
    img.delete()


def calculate_points(annotation_area, point_gen_spec):
    """
    Calculate points for an image. This doesn't actually
    insert anything in the database; it just generates the
    row, column for each point number.

    Returns the points as a list of dicts; each dict
    represents a point, and has keys "row", "column",
    and "point_number".
    """

    points = []

    annoarea_min_col = annotation_area.min_x
    annoarea_max_col = annotation_area.max_x
    annoarea_min_row = annotation_area.min_y
    annoarea_max_row = annotation_area.max_y

    annoarea_height = annoarea_max_row - annoarea_min_row + 1
    annoarea_width = annoarea_max_col - annoarea_min_col + 1


    if point_gen_spec.type == PointGen.Types.SIMPLE.value:

        simple_random_points = []

        for i in range(point_gen_spec.points):
            row = random.randint(annoarea_min_row, annoarea_max_row)
            column = random.randint(annoarea_min_col, annoarea_max_col)

            simple_random_points.append({'row': row, 'column': column})

        # To make consecutive points appear reasonably close to each other,
        # impose cell rows and cols, then make consecutive points fill the
        # cells one by one.
        cell_rows_for_numbering = 5
        cell_columns_for_numbering = 5
        cell = dict()
        for r in range(cell_rows_for_numbering):
            cell[r] = dict()
            for c in range(cell_columns_for_numbering):
                cell[r][c] = []

        for p in simple_random_points:
            # Assign each random point to the cell it belongs in.
            # This is all int math, so no floor(), int(), etc. needed.
            # But remember to not divide until the end.
            r = ((p['row'] - annoarea_min_row)
                 * cell_rows_for_numbering) // annoarea_height
            c = ((p['column'] - annoarea_min_col)
                 * cell_columns_for_numbering) // annoarea_width

            cell[r][c].append(p)

        point_num = 1
        for r in range(cell_rows_for_numbering):
            for c in range(cell_columns_for_numbering):
                for p in cell[r][c]:

                    points.append(dict(
                        row=p['row'], column=p['column'],
                        point_number=point_num,
                    ))
                    point_num += 1

    elif point_gen_spec.type == PointGen.Types.STRATIFIED.value:

        point_num = 1

        # Each pixel of the annotation area goes in exactly one cell.
        # Cell widths and heights are within one pixel of each other.
        for row_num in range(0, point_gen_spec.cell_rows):
            row_min = ((row_num * annoarea_height)
                       // point_gen_spec.cell_rows) + annoarea_min_row
            row_max = (((row_num+1) * annoarea_height)
                       // point_gen_spec.cell_rows) + annoarea_min_row - 1

            for col_num in range(0, point_gen_spec.cell_columns):
                col_min = (
                    (col_num * annoarea_width)
                    // point_gen_spec.cell_columns) + annoarea_min_col
                col_max = (
                    ((col_num+1) * annoarea_width)
                    // point_gen_spec.cell_columns) + annoarea_min_col - 1

                for cell_point_num in range(0, point_gen_spec.per_cell):
                    row = random.randint(row_min, row_max)
                    column = random.randint(col_min, col_max)

                    points.append(dict(
                        row=row, column=column, point_number=point_num,
                    ))
                    point_num += 1

    elif point_gen_spec.type == PointGen.Types.UNIFORM.value:

        point_num = 1

        for row_num in range(0, point_gen_spec.cell_rows):
            row_min = ((row_num * annoarea_height)
                       // point_gen_spec.cell_rows) + annoarea_min_row
            row_max = (((row_num+1) * annoarea_height)
                       // point_gen_spec.cell_rows) + annoarea_min_row - 1
            row_mid = (row_min+row_max) // 2

            for col_num in range(0, point_gen_spec.cell_columns):
                col_min = (
                    (col_num * annoarea_width)
                    // point_gen_spec.cell_columns) + annoarea_min_col
                col_max = (
                    ((col_num+1) * annoarea_width)
                    // point_gen_spec.cell_columns) + annoarea_min_col - 1
                col_mid = (col_min+col_max) // 2

                points.append(dict(
                    row=row_mid, column=col_mid, point_number=point_num,
                ))
                point_num += 1

    return points


def generate_points(img, usesourcemethod=True):
    """
    Generate annotation points for the Image img,
    and delete any points that had previously existed.

    Does nothing if the image already has human annotations,
    because we don't want to delete any human work.
    """

    # If there are any human annotations for this image,
    # abort point generation.
    human_annotations = img.annotation_set.confirmed().exclude(
        user=get_alleviate_user())
    if human_annotations:
        return

    # Find the annotation area, expressed in pixels.
    anno_area = AnnotationArea.from_db_value(img.metadata.annotation_area)
    anno_area = AnnotationArea.to_pixels(
        anno_area, width=img.original_width, height=img.original_height)

    # Calculate points.
    if usesourcemethod:
        point_gen_method = img.source.default_point_generation_method
    else:
        point_gen_method = img.point_generation_method
    
    new_points = calculate_points(
        annotation_area=anno_area,
        point_gen_spec=PointGen.from_db_value(point_gen_method),
    )

    # Delete old points for this image, if any.
    old_points = Point.objects.filter(image=img)
    for old_point in old_points:
        old_point.delete()

    # Any CPC (Coral Point Count file) we had saved previously no longer has
    # the correct point positions, so we'll just discard the CPC.
    img.cpc_content = ''
    img.cpc_filename = ''
    img.save()

    # Save the newly calculated points.
    for new_point in new_points:
        Point(row=new_point['row'],
              column=new_point['column'],
              point_number=new_point['point_number'],
              image=img,
        ).save()


def get_carousel_images():
    """
    Get images for the front page carousel.

    We randomly pick <image_count> images out of a pool. The pool is specified
    in settings, and should be hand-picked from public sources.
    """
    image_count = settings.CAROUSEL_IMAGE_COUNT
    image_pks = random.sample(settings.CAROUSEL_IMAGE_POOL, image_count)
    return Image.objects.filter(pk__in=image_pks)


# Functions to encapsulate the auxiliary metadata
# field details.

def get_aux_label_field_name(aux_field_number):
    return 'key'+str(aux_field_number)
def get_aux_field_name(aux_field_number):
    return 'aux'+str(aux_field_number)

def get_aux_label(source, aux_field_number):
    return getattr(source, get_aux_label_field_name(aux_field_number))

def get_num_aux_fields():
    return 5

def get_aux_label_field_names():
    return [
        get_aux_label_field_name(n)
        for n in range(1, get_num_aux_fields()+1)]

def get_aux_field_names():
    return [
        get_aux_field_name(n)
        for n in range(1, get_num_aux_fields()+1)]

def get_aux_labels(source):
    return [
        get_aux_label(source, aux_field_number)
        for aux_field_number in range(1, get_num_aux_fields()+1)]

def get_aux_metadata_form_choices(source, aux_field_number):
    # On using distinct(): http://stackoverflow.com/a/2468620/
    distinct_aux_values = Metadata.objects.filter(image__source=source) \
        .values_list(get_aux_field_name(aux_field_number), flat=True) \
        .distinct()
    return [(v,v) for v in distinct_aux_values if v != '']

def get_aux_metadata_str_for_image(image, aux_field_number):
    return getattr(image.metadata, get_aux_field_name(aux_field_number))


# Other auxiliary metadata related functions.

def get_date_and_aux_metadata_table(image):
    """
    Get the year and aux metadata for display as a 2 x n table.
    """
    cols = []

    if image.metadata.photo_date:
        date_str = datetime.datetime.strftime(
            image.metadata.photo_date, "%Y-%m-%d")
    else:
        date_str = "-"
    cols.append(("Date", date_str))

    for n in range(1, get_num_aux_fields()+1):
        aux_label = get_aux_label(image.source, n)
        aux_value = get_aux_metadata_str_for_image(image, n)
        if aux_value == "":
            aux_value = "-"
        cols.append((aux_label, aux_value))

    # Transpose
    rows = dict(
        keys=[c[0] for c in cols],
        values=[c[1] for c in cols],
    )
    return rows


# Image counts.

def compute_sitewide_image_count():
    """
    Count of total images on the entire site. As of
    coralnet 1.25, this may take about 2 seconds to run in production.
    """
    return Image.objects.all().count()


# We don't update this with a periodic job, because it's not too bad
# to recompute on-demand every so often.
seconds_in_one_day = 60*60*24
cacheable_image_count = CacheableValue(
    cache_key='sitewide_image_count',
    cache_timeout_interval=seconds_in_one_day,
    compute_function=compute_sitewide_image_count,
)


def compute_per_source_image_counts():
    source_values = (
        Source.objects.all()
        .annotate(image_count=Count('image'))
        .values('pk', 'image_count')
    )
    image_counts_dict = {v['pk']: v['image_count'] for v in source_values}
    return image_counts_dict


# We don't update this with a periodic job, because it's not too bad
# to recompute on-demand every so often (probably).
#
# Sometimes the most up-to-date image count for a source is more
# important, like when viewing a page in the source itself; other
# times it's not as important, like when viewing all sources on the
# front page. This cacheable value is appropriate for cases like the
# latter.
cacheable_source_image_counts = CacheableValue(
    cache_key='per_source_image_counts',
    cache_timeout_interval=seconds_in_one_day,
    compute_function=compute_per_source_image_counts,
)
