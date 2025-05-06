from collections import defaultdict
import csv
import json
import urllib.parse

from django.conf import settings
from django.contrib import messages
from django.db import IntegrityError, transaction
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import render, get_object_or_404
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.http import require_POST

from easy_thumbnails.files import get_thumbnailer
import reversion
from reversion.revisions import create_revision
from reversion.models import Version, Revision

from accounts.utils import get_imported_user
from events.models import Event
from export.views import SourceCsvExportPrepView
from images.model_utils import PointGen
from images.models import Image, Point
from images.utils import (
    generate_points,
    get_date_and_aux_metadata_table,
    get_image_order_placement,
    get_next_image,
    get_prev_image,
)
from lib.decorators import (
    image_annotation_area_must_be_editable,
    image_labelset_required,
    image_permission_required,
    login_required_ajax,
    source_labelset_required,
    source_permission_required,
)
from lib.exceptions import FileProcessError
from lib.forms import get_one_form_error
from sources.models import Source
from sources.utils import metadata_field_names_to_labels
from upload.forms import CSVImportForm
from visualization.forms import HiddenForm, create_image_filter_form
from vision_backend.models import ClassifyImageEvent, Score
from vision_backend.utils import (
    get_label_scores_for_image,
    reset_features,
)
from .forms import (
    AnnotationForm,
    AnnotationAreaPixelsForm,
    AnnotationToolSettingsForm,
    AnnotationImageOptionsForm,
    ExportAnnotationsForm,
)
from .model_utils import AnnotationArea
from .models import (
    Annotation,
    AnnotationToolAccess,
    AnnotationToolSettings,
    AnnotationUploadEvent,
)
from .utils import (
    annotations_csv_to_dict,
    annotations_preview,
    apply_alleviate,
    get_annotation_version_user_display,
)


@image_permission_required('image_id', perm=Source.PermTypes.EDIT.code)
@image_annotation_area_must_be_editable('image_id')
def annotation_area_edit(request, image_id):
    """
    Edit an image's annotation area.
    """

    image = get_object_or_404(Image, id=image_id)
    source = image.source
    metadata = image.metadata

    old_annotation_area = metadata.annotation_area

    if request.method == 'POST':

        # Cancel
        cancel = request.POST.get('cancel', None)
        if cancel:
            messages.success(request, 'Edit cancelled.')
            return HttpResponseRedirect(
                reverse('image_detail', args=[image.id]))

        # Submit
        annotation_area_form = AnnotationAreaPixelsForm(
            request.POST, image=image)

        if annotation_area_form.is_valid():
            metadata.annotation_area = AnnotationArea(
                type=AnnotationArea.TYPE_PIXELS,
                **annotation_area_form.cleaned_data).db_value
            metadata.save()

            if metadata.annotation_area != old_annotation_area:
                generate_points(image, usesourcemethod=False)
                reset_features(image)

            messages.success(request, 'Annotation area successfully edited.')
            return HttpResponseRedirect(
                reverse('image_detail', args=[image.id]))
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        # Just reached this form page
        annotation_area_form = AnnotationAreaPixelsForm(image=image)

    # Scale down the image to have a max width of 800 pixels.
    MAX_DISPLAY_WIDTH = 800
    if image.original_width > MAX_DISPLAY_WIDTH:
        # Parameters into the easy_thumbnails template tag:
        # (specific width, height that keeps the aspect ratio)
        thumbnail_dimensions = (MAX_DISPLAY_WIDTH, 0)
        has_thumbnail = True
    else:
        # No thumbnail needed
        thumbnail_dimensions = None
        has_thumbnail = False

    # jQuery UI resizing with containment isn't subpixel-precise, so
    # the display height is rounded to an int.  Thus, need to track
    # width/height scaling factors separately for accurate calculations.
    display_width = min(MAX_DISPLAY_WIDTH, image.original_width)
    width_scale_factor = display_width / image.original_width
    display_height = int(round(image.original_height * width_scale_factor))
    height_scale_factor = display_height / image.original_height

    dimensions = dict(
        displayWidth=display_width,
        displayHeight=display_height,
        fullWidth=image.original_width,
        fullHeight=image.original_height,
        widthScaleFactor=width_scale_factor,
        heightScaleFactor=height_scale_factor,
    )

    return render(request, 'annotations/annotation_area_edit.html', {
        'source': source,
        'image': image,
        'dimensions': json.dumps(dimensions),
        'has_thumbnail': has_thumbnail,
        'thumbnail_dimensions': thumbnail_dimensions,
        'annotationAreaForm': annotation_area_form,
    })


@require_POST
@source_permission_required(
    'source_id', perm=Source.PermTypes.EDIT.code, ajax=True)
def batch_delete_annotations_ajax(request, source_id):
    source = get_object_or_404(Source, id=source_id)

    image_form = create_image_filter_form(request.POST, source)
    if not image_form:
        # It's not good to accidentally delete everything, and it's uncommon
        # to do it intentionally. So we'll play it safe.
        return JsonResponse(dict(
            error=(
                "You must first use the search form or select images on the"
                " page to use the delete function. If you really want to"
                " delete all images' annotations, first click 'Search' without"
                " changing any of the search fields."
            )
        ))
    if not image_form.is_valid():
        return JsonResponse(dict(
            error=(
                "There was an error with the form."
                " Nothing was deleted."
            )
        ))

    image_set = image_form.get_images()
    image_count = image_set.count()

    # Delete annotations.
    Annotation.objects.filter(image__in=image_set).delete_in_chunks()

    # This should appear on the next browse load.
    messages.success(
        request,
        f"The {image_count} selected images"
        f" have had their annotations deleted.")

    return JsonResponse(dict(success=True))


@image_permission_required('image_id', perm=Source.PermTypes.EDIT.code)
@image_labelset_required('image_id', message=(
    "You need to create a labelset for your source"
    " before you can annotate images."))
def annotation_tool(request, image_id):
    """
    View for the annotation tool.
    """
    image = get_object_or_404(Image, id=image_id)
    source = image.source
    metadata = image.metadata

    # The set of images we're annotating.
    # Ensure it has an unambiguous ordering.
    image_set = source.image_set.order_by('metadata__name', 'pk')
    hidden_image_set_form = None
    applied_search_display = None

    image_form = create_image_filter_form(request.POST, source)
    browse_query_args = None
    if image_form and image_form.is_valid():
        image_set = image_form.get_images()
        hidden_image_set_form = HiddenForm(forms=[image_form])
        applied_search_display = image_form.get_applied_search_display()
        browse_query_args = {
            k: v for k, v in request.POST.items()
            if k in image_form.cleaned_data
        }

    # Get the next and previous images in the image set.
    prev_image = get_prev_image(image, image_set, wrap=True)
    next_image = get_next_image(image, image_set, wrap=True)
    # Get the image's ordered placement in the image set, e.g. 5th.
    image_set_order_placement = get_image_order_placement(image, image_set)

    return_to_browse_link = reverse('browse_images', args=[source.pk])
    if browse_query_args:
        return_to_browse_link += (
            '?' + urllib.parse.urlencode(browse_query_args))

    # Get the settings object for this user.
    # If there is no such settings object, then populate the form with
    # the default settings.
    try:
        settings_obj = AnnotationToolSettings.objects.get(user=request.user)
    except AnnotationToolSettings.DoesNotExist:
        settings_obj = AnnotationToolSettings()
    settings_form = AnnotationToolSettingsForm(instance=settings_obj)

    # Get labels in the form
    # {'code': <short code>, 'group': <functional group>, 'name': <full name>}.
    labels = source.labelset.get_locals_ordered_by_group_and_code()
    labels = [
        dict(code=label.code, group=label.group.name, name=label.name)
        for label in labels
    ]

    # Get the machine's label scores, if applicable.
    label_scores = None

    if settings_obj.show_machine_annotations and image.score_set.exists():
        label_scores = get_label_scores_for_image(image_id)

        # Apply Alleviate.
        #
        # reversion's revision-creating context manager is active here if
        # the request is POST. If it's GET, it won't be active, and thus
        # we need to activate it ourselves. We check because we don't want
        # to double-activate it.
        # TODO: Ideally the request triggering Alleviate should always be
        # POST, since data-changing requests shouldn't be GET.
        # Accomplishing this may or may not involve moving Alleviate
        # to a separate request from the main annotation tool request.
        if reversion.is_active():
            apply_alleviate(image, label_scores)
        else:
            with create_revision():
                apply_alleviate(image, label_scores)

    # Form where you enter annotations' label codes
    form = AnnotationForm(
        image=image,
        show_machine_annotations=settings_obj.show_machine_annotations
    )

    # List of dicts containing point info
    points = Point.objects.filter(image=image) \
        .order_by('point_number') \
        .values('point_number', 'row', 'column')
    points = list(points)

    # Image tools form (brightness, contrast, etc.)
    image_options_form = AnnotationImageOptionsForm()

    # Info on full image and scaled image, if any.
    source_images = dict(full=dict(
        url=image.original_file.url,
        width=image.original_file.width,
        height=image.original_file.height,
    ))
    THUMBNAIL_WIDTH = 800
    if image.original_width > THUMBNAIL_WIDTH:
        # Set scaled image's dimensions
        # (Specific width, height that keeps the aspect ratio)
        thumbnail_dimensions = (THUMBNAIL_WIDTH, 0)

        # Generate the thumbnail if it doesn't exist,
        # and get the thumbnail's URL and dimensions.
        thumbnailer = get_thumbnailer(image.original_file)
        thumb = thumbnailer.get_thumbnail(dict(size=thumbnail_dimensions))
        source_images.update(dict(scaled=dict(
            url=thumb.url,
            width=thumb.width,
            height=thumb.height,
        )))

    # Record this access of the annotation tool page.
    access = AnnotationToolAccess(image=image, source=source, user=request.user)
    access.save()

    return render(request, 'annotations/annotation_tool.html', {
        'source': source,
        'image': image,
        'hidden_image_set_form': hidden_image_set_form,
        'next_image': next_image,
        'prev_image': prev_image,
        'image_set_size': image_set.count(),
        'image_set_order_placement': image_set_order_placement,
        'applied_search_display': applied_search_display,
        'return_to_browse_link': return_to_browse_link,
        'metadata': metadata,
        'image_meta_table': get_date_and_aux_metadata_table(image),
        'labels': labels,
        'form': form,
        'settings_form': settings_form,
        'image_options_form': image_options_form,
        'points': points,
        'label_scores': label_scores,
        'source_images': source_images,
    })


@image_permission_required(
    'image_id', perm=Source.PermTypes.EDIT.code, ajax=True)
def save_annotations_ajax(request, image_id):
    """
    Called via Ajax from the annotation tool, if the user clicked
    the Save button.

    Takes the annotation form contents, in request.POST.
    Saves annotation changes to the database.
    JSON response consists of:
      all_done: boolean, True if the image has all points confirmed
      error: error message if there was an error, otherwise not present
    """
    if request.method != 'POST':
        return JsonResponse(dict(
            error="Not a POST request"))

    image = get_object_or_404(Image, id=image_id)
    source = image.source

    # Get stuff from the DB in advance, should save DB querying time
    points_list = list(Point.objects.filter(image=image))
    points = dict([(p.point_number, p) for p in points_list])

    annotations_to_try_updating = []

    # Here we are basically doing form validation, but without a Form or
    # Formset.
    # TODO: This validation should be done in a formset class for
    # cleaner/clearer code. But this is important and nuanced functionality,
    # so change it only when we have integration tests (Django + Javascript
    # being tested together) for the annotation form.
    for point_num, point in points.items():

        label_code = request.POST.get('label_'+str(point_num), None)
        if label_code is None:
            return JsonResponse(
                dict(error="Missing label field for point %s." % point_num))
        if label_code == '':
            # Label code is blank; nothing to do. We don't allow deleting
            # existing annotations.
            continue

        is_unconfirmed_in_form_raw = request.POST.get('robot_'+str(point_num))
        if is_unconfirmed_in_form_raw is None:
            return JsonResponse(
                dict(error="Missing robot field for point %s." % point_num))
        if is_unconfirmed_in_form_raw == 'null':
            # This field uses null and false interchangeably, including on the
            # Javascript side. It's sloppy, but we have to handle it for now.
            # Possible future change in JS: if the user fills a blank label
            # field, then the JS should change robot from null to false.
            is_unconfirmed_in_form_raw = 'false'
        if is_unconfirmed_in_form_raw not in ['true', 'false']:
            return JsonResponse(dict(
                error="Invalid robot field value: {v}".format(
                    v=is_unconfirmed_in_form_raw)))
        # json-load result is True or False.
        # True means this point has a non-human-confirmed robot annotation
        # in the form.
        is_unconfirmed_in_form = json.loads(is_unconfirmed_in_form_raw)

        # Get the label that the form field value refers to.
        # Anticipate errors, even if we plan to check input with JS.
        label = source.labelset.get_global_by_code(label_code)
        if not label:
            return JsonResponse(dict(error=(
                "The labelset has no label with code %s." % label_code)))

        # We only save confirmed annotations with the annotation form.
        if not is_unconfirmed_in_form:
            # Prepare to save, but don't actually save yet.
            annotations_to_try_updating.append(dict(
                point=point, label=label,
                now_confirmed=(not is_unconfirmed_in_form),
                user_or_robot_version=request.user
            ))

    try:
        # If anything in this block gets an exception, we'll roll back
        # the DB changes. This way we don't have partial saves, which can be
        # confusing.
        with transaction.atomic():
            for annotation_kwargs in annotations_to_try_updating:
                Annotation.objects.update_point_annotation_if_applicable(
                    **annotation_kwargs)
    except IntegrityError:
        return JsonResponse(dict(error=(
            "Failed to save annotations. It's possible that the"
            " annotations changed at the same time that you submitted."
            " Try again and see if it works.")))

    return JsonResponse(dict(all_done=image.annoinfo.confirmed))


@image_permission_required(
    'image_id', perm=Source.PermTypes.VIEW.code, ajax=True)
def is_annotation_all_done_ajax(request, image_id):
    """
    :returns dict of:
      all_done: True if the image has all points confirmed, False otherwise
      error: Error message if there was an error
    """
    image = get_object_or_404(Image, id=image_id)
    return JsonResponse(dict(all_done=image.annoinfo.confirmed))


@login_required_ajax
def annotation_tool_settings_save(request):
    """
    Annotation tool Ajax: user clicks the settings Save button.
    Saves annotation tool settings changes to the database.

    :param request: request.POST contains the settings form values.
    :returns dict of:
      error: Error message if there was an error
    """

    if request.method != 'POST':
        return JsonResponse(dict(error="Not a POST request"))

    try:
        settings_obj = AnnotationToolSettings.objects.get(user=request.user)
        # If no exception, this user already has a settings object
        settings_form = AnnotationToolSettingsForm(
            request.POST, instance=settings_obj)
    except AnnotationToolSettings.DoesNotExist:
        # No settings object for this user yet; saving the form will create one
        settings_form = AnnotationToolSettingsForm(request.POST)

    if settings_form.is_valid():
        try:
            # Save the form, but don't commit to the DB yet
            settings_obj = settings_form.save(commit=False)
            # In the case of a new settings object, this assigns the user to
            # it. In the case of an existing settings object, this makes no
            # change.
            settings_obj.user = request.user
            # Now we commit to the DB
            settings_obj.save()
            return JsonResponse(dict())
        except IntegrityError:
            # This may indicate a race condition, in which the user just had a
            # settings object created in another thread.
            # Not the end of the world, it just means this save failed and the
            # user should try again if they didn't end up with the desired
            # settings.
            error_detail = "IntegrityError when trying to save the form"
    else:
        # Some form values weren't valid.
        # This can happen if the form's JavaScript input checking isn't
        # foolproof, or if the user messed with form values using FireBug.
        error_detail = get_one_form_error(settings_form)

    error_message = (
        "Settings form failed to save. Perhaps refresh the page and try"
        " again? If the problem persists, please report to the site admins."
        " (Error detail: \"{error_detail}\")").format(error_detail=error_detail)
    return JsonResponse(dict(error=error_message))


@image_permission_required('image_id', perm=Source.PermTypes.EDIT.code)
@image_labelset_required('image_id', message=(
    "This source doesn't have a labelset yet,"
    " so it can't have any annotations yet."))
# This is a potentially slow view that doesn't modify the database,
# so don't open a transaction for the view.
@transaction.non_atomic_requests
def annotation_history(request, image_id):
    """
    View for an image's annotation history.
    """
    image = get_object_or_404(Image, id=image_id)
    source = image.source

    annotations = Annotation.objects.filter(image=image)

    # Get the annotation Versions whose annotation PKs correspond to the
    # relevant image.
    # Version.object_id is a character-varying field, so we have to convert
    # integer primary keys to strings in order to compare with this field.
    #
    # This part is PERFORMANCE SENSITIVE. Historically, it has taken 1 second
    # to 10 minutes for the same data depending on the implementation. Re-test
    # on the staging server (which has a large Version table) after changing
    # anything here.
    annotation_id_strs = [
        str(pk) for pk in annotations.values_list('pk', flat=True)]
    versions = Version.objects.get_for_model(Annotation).filter(
        object_id__in=annotation_id_strs)

    # Get the Revisions associated with these annotation Versions.
    revisions = Revision.objects.filter(version__in=versions).distinct()

    labelset_dict = source.labelset.global_pk_to_code_dict()

    def version_to_point_number(v_):
        # We name the arg v_ to avoid shadowing the outer scope's v.
        return Annotation.objects.get(pk=v_.object_id).point.point_number

    event_log = []

    for rev in revisions:
        # Get Versions under this Revision
        rev_versions = versions.filter(revision=rev)

        # Sort by the point number of the annotation
        rev_versions = list(rev_versions)
        rev_versions.sort(key=version_to_point_number)

        # Create a log entry for this Revision
        events = []
        for v in rev_versions:
            point_number = version_to_point_number(v)
            global_label_pk = v.field_dict['label_id']
            label_display = Event.label_id_to_display(
                global_label_pk, labelset_dict)
            events.append("Point {num}: {label}".format(
                num=point_number, label=label_display))

        event_log.append(
            dict(
                date=rev.date_created,
                # Any Version will do
                user=get_annotation_version_user_display(
                    rev_versions[0], rev.date_created),
                events=events,
            )
        )

    # From CoralNet 1.15 onward, we no longer create django-reversion
    # Revisions/Versions for machine classification; this case is handled
    # by ClassifyImageEvents instead.
    event_objs = ClassifyImageEvent.objects.filter(
        image_id=image_id, date__gt=settings.CORALNET_1_15_DATE)
    for event_obj in event_objs:
        event_log.append(event_obj.annotation_history_entry(labelset_dict))

    # From CoralNet 1.18 onward, we track annotation uploads with Events
    # instead of django-reversion.
    event_objs = AnnotationUploadEvent.objects.filter(image_id=image_id)
    for event_obj in event_objs:
        event_log.append(event_obj.annotation_history_entry(labelset_dict))

    for access in AnnotationToolAccess.objects.filter(image=image):
        # Create a log entry for each annotation tool access
        event_str = "Accessed annotation tool"
        event_log.append(
            dict(
                date=access.access_date,
                user=access.user.username,
                events=[event_str],
            )
        )

    event_log.sort(key=lambda x: x['date'], reverse=True)

    return render(request, 'annotations/annotation_history.html', {
        'source': source,
        'image': image,
        'metadata': image.metadata,
        'image_meta_table': get_date_and_aux_metadata_table(image),
        'event_log': event_log,
    })


@source_permission_required('source_id', perm=Source.PermTypes.EDIT.code)
@source_labelset_required('source_id', message=(
    "You must create a labelset before uploading annotations."))
def upload_page(request, source_id):
    source = get_object_or_404(Source, id=source_id)

    csv_import_form = CSVImportForm()

    return render(request, 'annotations/upload.html', {
        'source': source,
        'csv_import_form': csv_import_form,
    })


@source_permission_required(
    'source_id', perm=Source.PermTypes.EDIT.code, ajax=True)
@source_labelset_required('source_id', message=(
    "You must create a labelset before uploading annotations."))
def upload_preview(request, source_id):
    """
    Add points/annotations to images by uploading a CSV file.

    This view takes the CSV file, processes it, saves the processed data
    to the session, and returns a preview table of the data to be saved.
    """
    if request.method != 'POST':
        return JsonResponse(dict(
            error="Not a POST request",
        ))

    source = get_object_or_404(Source, id=source_id)

    csv_import_form = CSVImportForm(request.POST, request.FILES)
    if not csv_import_form.is_valid():
        return JsonResponse(dict(
            error=csv_import_form.errors['csv_file'][0],
        ))

    try:
        csv_annotations = annotations_csv_to_dict(
            csv_import_form.get_csv_stream(), source)
    except FileProcessError as error:
        return JsonResponse(dict(
            error=str(error),
        ))

    preview_table, preview_details = \
        annotations_preview(csv_annotations, source)

    request.session['uploaded_annotations'] = csv_annotations

    return JsonResponse(dict(
        success=True,
        previewTable=preview_table,
        previewDetails=preview_details,
    ))


@method_decorator(
    [
        # Access control.
        source_permission_required(
            'source_id', perm=Source.PermTypes.EDIT.code, ajax=True),
        source_labelset_required('source_id', message=(
            "You must create a labelset before uploading annotations."))
    ],
    name='dispatch')
class AnnotationsUploadConfirmView(View):
    """
    This view gets the annotation data that was previously saved to the
    session by an upload-annotations-preview view. Then it saves the data
    to the database, while deleting all previous points/annotations for the
    images involved.
    """
    def post(self, request, source_id):
        source = get_object_or_404(Source, id=source_id)

        uploaded_annotations = request.session.pop('uploaded_annotations', None)
        if not uploaded_annotations:
            return JsonResponse(dict(
                error=(
                    "We couldn't find the expected data in your session."
                    " Please try loading this page again. If the problem"
                    " persists, let us know on the forum."
                ),
            ))

        self.extra_source_level_actions(request, source)

        for image_id, annotations_for_image in uploaded_annotations.items():

            img = Image.objects.get(pk=image_id, source=source)

            # Delete previous annotations and points for this image.
            # Calling delete() on these querysets is more efficient
            # than calling delete() on each of the individual objects.
            Annotation.objects.filter(image=img).delete()
            Point.objects.filter(image=img).delete()

            # Create new points and annotations.
            new_points = []
            new_annotations = []

            for num, point_dict in enumerate(annotations_for_image, 1):
                # Create a Point.
                point = Point(
                    row=point_dict['row'], column=point_dict['column'],
                    point_number=num, image=img)
                new_points.append(point)
            # Save to DB with an efficient bulk operation.
            Point.objects.bulk_create(new_points)

            # Mapping of newly-saved points.
            point_numbers_to_ids = dict(
                (p.point_number, p.pk) for p in new_points)
            point_ids_to_numbers = dict(
                (p.pk, p.point_number) for p in new_points)

            for num, point_dict in enumerate(annotations_for_image, 1):
                # The annotation-preview view should've processed annotation
                # data to just label IDs, not codes.
                label_id = point_dict.get('label_id')
                # Create an Annotation if a label is specified.
                if label_id:
                    new_annotations.append(Annotation(
                        point_id=point_numbers_to_ids[num],
                        image=img, source=source,
                        label_id=label_id, user=get_imported_user()))

            # Bulk-create bypasses the django-reversion signals,
            # which is what we want in this case (trying to obsolete
            # reversion for annotations).
            Annotation.objects.bulk_create(new_annotations)

            # Instead of a django-reversion revision, we'll create our
            # own Event.
            event_details = dict(
                point_count=len(new_points),
                first_point_id=new_points[0].pk,
                annotations=dict(
                    (point_ids_to_numbers[ann.point_id], ann.label_id)
                    for ann in new_annotations
                ),
            )
            event = AnnotationUploadEvent(
                source_id=source_id,
                image_id=image_id,
                creator_id=request.user.pk,
                details=event_details,
            )
            event.save()

            # Update relevant image/metadata fields.
            self.update_image_and_metadata_fields(img, new_points)

            reset_features(img)

        return JsonResponse(dict(
            success=True,
        ))

    def extra_source_level_actions(self, request, source):
        pass

    def update_image_and_metadata_fields(self, image, new_points):
        image.point_generation_method = PointGen(
            type=PointGen.Types.IMPORTED.value,
            points=len(new_points)).db_value
        # Clear previously-uploaded CPC info.
        image.cpc_content = ''
        image.cpc_filename = ''
        image.save()

        image.metadata.annotation_area = AnnotationArea(
            type=AnnotationArea.TYPE_IMPORTED).db_value
        image.metadata.save()


class ExportPrepView(SourceCsvExportPrepView):

    label_format: str
    labelset_dict: dict
    metadata_date_aux_fields: list
    metadata_field_labels: dict
    metadata_other_fields: list
    optional_columns: list[str]
    username_dict: dict
    writer: csv.DictWriter

    def get_export_filename(self, source, suffix='.csv'):
        return f'annotations{suffix}'

    def get_export_form(self, source, data):
        return ExportAnnotationsForm(data)

    def point_score_values_for_image(self, image):
        """
        Database values this view needs regarding an image's points.
        """
        point_fields = [
            'id',
            'point_number',
            'column',
            'row',
            'annotation',
            'annotation__label',
            'annotation__user',
        ]
        if 'annotator_info' in self.optional_columns:
            point_fields.extend([
                'annotation__annotation_date',
            ])
        point_set_values = (
            image.point_set
            .order_by('point_number')
            .values(*point_fields)
        )

        score_set_values = (
            Score.objects.filter(point__image=image)
            .order_by('point', '-score')
            .values('point', 'score', 'label')
        )
        score_set_values_per_point = defaultdict(list)
        for score_values in score_set_values:
            point_id = score_values['point']
            score_set_values_per_point[point_id].append(score_values)

        return point_set_values, score_set_values_per_point

    def write_csv(self, stream, source, image_set, export_form_data):
        # List of string keys indicating optional column sets to add.
        self.optional_columns = export_form_data['optional_columns']

        self.metadata_field_labels = metadata_field_names_to_labels(source)
        self.metadata_date_aux_fields = [
            'photo_date', 'aux1', 'aux2', 'aux3', 'aux4', 'aux5']
        self.metadata_other_fields = [
            f for f in self.metadata_field_labels.keys()
            if f not in [
                'name', 'photo_date', 'aux1', 'aux2', 'aux3', 'aux4', 'aux5']
        ]

        fieldnames = ["Name", "Row", "Column"]

        self.label_format = export_form_data['label_format']

        if self.label_format in ['code', 'both']:
            fieldnames.append("Label code")
        if self.label_format in ['id', 'both']:
            fieldnames.append("Label ID")

        self.labelset_dict = source.labelset.global_pk_to_code_dict()

        users_values = (
            Annotation.objects.filter(image__source=source)
            .values('user', 'user__username').distinct()
        )
        self.username_dict = dict(
            (v['user'], v['user__username']) for v in users_values)

        if 'annotator_info' in self.optional_columns:
            fieldnames.extend(["Annotator", "Date annotated"])

        if 'machine_suggestions' in self.optional_columns:
            for n in range(1, settings.NBR_SCORES_PER_ANNOTATION+1):
                fieldnames.extend([
                    "Machine suggestion {n}".format(n=n),
                    "Machine confidence {n}".format(n=n),
                ])

        if 'metadata_date_aux' in self.optional_columns:
            date_aux_labels = [
                self.metadata_field_labels[name]
                for name in self.metadata_date_aux_fields
            ]
            # Insert these columns before the Row column
            insert_index = fieldnames.index("Row")
            fieldnames = (
                fieldnames[:insert_index]
                + date_aux_labels
                + fieldnames[insert_index:])

        if 'metadata_other' in self.optional_columns:
            other_meta_labels = [
                self.metadata_field_labels[name]
                for name in self.metadata_other_fields
            ]
            # Insert these columns before the Row column
            insert_index = fieldnames.index("Row")
            fieldnames = (
                fieldnames[:insert_index]
                + other_meta_labels
                + fieldnames[insert_index:])

        self.writer = csv.DictWriter(stream, fieldnames)
        self.writer.writeheader()

        # One image at a time.
        for image in image_set:

            # point_set_values should be in point-number order (as ensured
            # by the method we call here).
            point_set_values, score_set_values_per_point = (
                self.point_score_values_for_image(image))

            for point_values in point_set_values:
                score_set_values = score_set_values_per_point[
                    point_values['id']]
                self.write_csv_one_point(
                    image, point_values, score_set_values)

    def write_csv_one_point(self, image, point_values, score_set_values):

        if not point_values['annotation']:
            # Only write a row for points with annotations.
            return

        # One row per annotation.
        row = {
            "Name": image.metadata.name,
            "Row": point_values['row'],
            "Column": point_values['column'],
        }

        if self.label_format in ['code', 'both']:
            row["Label code"] = (
                self.labelset_dict[point_values['annotation__label']])
        if self.label_format in ['id', 'both']:
            row["Label ID"] = point_values['annotation__label']

        if 'annotator_info' in self.optional_columns:
            # Truncate date precision at seconds
            annotation_date = point_values[
                'annotation__annotation_date']
            date_annotated = annotation_date.replace(
                microsecond=0)
            annotator = (
                self.username_dict[point_values['annotation__user']])
            row.update({
                "Annotator": annotator,
                "Date annotated": date_annotated,
            })

        if 'machine_suggestions' in self.optional_columns:
            # These scores should be in order from highest score
            # to lowest.
            for i in range(settings.NBR_SCORES_PER_ANNOTATION):
                try:
                    score_values = score_set_values[i]
                except IndexError:
                    # We might need to fill in some blank scores. For
                    # example, when the classification system hasn't
                    # annotated these points yet, or when the labelset
                    # has fewer than NBR_SCORES_PER_ANNOTATION labels.
                    label_code = ""
                    score = ""
                else:
                    label_code = self.labelset_dict[score_values['label']]
                    score = score_values['score']
                n = i + 1
                row.update({
                    f"Machine suggestion {n}": label_code,
                    f"Machine confidence {n}": score,
                })

        if 'metadata_date_aux' in self.optional_columns:
            label_value_tuples = []
            for field_name in self.metadata_date_aux_fields:
                label = self.metadata_field_labels[field_name]
                value = getattr(image.metadata, field_name)
                if value is None:
                    value = ""
                label_value_tuples.append((label, value))
            row.update(dict(label_value_tuples))

        if 'metadata_other' in self.optional_columns:
            label_value_tuples = []
            for field_name in self.metadata_other_fields:
                label = self.metadata_field_labels[field_name]
                value = getattr(image.metadata, field_name)
                if value is None:
                    value = ""
                label_value_tuples.append((label, value))
            row.update(dict(label_value_tuples))

        self.writer.writerow(row)
