from collections import defaultdict
from io import StringIO
import json
from pathlib import PureWindowsPath

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import QuerySet
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.http import require_GET, require_POST

from accounts.utils import get_robot_user
from annotations.model_utils import AnnotationArea
from export.utils import get_request_images
from images.models import Image
from lib.decorators import (
    login_required_ajax,
    session_key_required,
    source_permission_required,
    source_labelset_required,
)
from lib.exceptions import FileProcessError
from lib.forms import get_one_form_error
from lib.utils import save_session_data
from sources.models import Source
from upload.utils import annotations_preview, text_file_to_unicode_stream
from upload.views import AnnotationsUploadConfirmView
from vision_backend.models import Score
from .forms import (
    CpcBatchEditCpcsForm,
    CpcBatchEditSpecForm,
    CpcExportForm,
    CpcImportForm,
)
from .utils import (
    annotations_cpcs_to_dict,
    CpcFileContent,
    cpc_editor_csv_to_dicts,
    cpc_edit_labels,
    create_zipped_cpcs_stream_response,
)


@source_permission_required('source_id', perm=Source.PermTypes.EDIT.code)
@source_labelset_required('source_id', message=(
    "You must create a labelset before uploading annotations."))
def upload_page(request, source_id):
    source = get_object_or_404(Source, id=source_id)

    cpc_import_form = CpcImportForm(source)

    return render(request, 'cpce/upload.html', {
        'source': source,
        'cpc_import_form': cpc_import_form,
    })


@source_permission_required(
    'source_id', perm=Source.PermTypes.EDIT.code, ajax=True)
@source_labelset_required('source_id', message=(
    "You must create a labelset before uploading annotations."))
@require_POST
def upload_preview_ajax(request, source_id):
    """
    Add points/annotations to images by uploading Coral Point Count files.

    This view takes multiple .cpc files, processes them, saves the processed
    data to the session, and returns a preview table of the data to be saved.
    """
    source = get_object_or_404(Source, id=source_id)

    cpc_import_form = CpcImportForm(source, request.POST, request.FILES)
    if not cpc_import_form.is_valid():
        return JsonResponse(dict(
            error=cpc_import_form.errors['cpc_files'][0],
        ))

    try:
        cpc_info = annotations_cpcs_to_dict(
            cpc_import_form.get_cpc_names_and_streams(),
            source,
            cpc_import_form.cleaned_data['label_mapping'],
        )
    except FileProcessError as error:
        return JsonResponse(dict(
            error=str(error),
        ))

    annotations = dict((c['image_id'], c['annotations']) for c in cpc_info)
    preview_table, preview_details = \
        annotations_preview(annotations, source)

    cpc_files = dict(
        (c['image_id'],
         dict(filename=c['filename'], cpc_content=c['cpc_content']))
        for c in cpc_info
    )
    request.session['uploaded_annotations'] = annotations
    request.session['cpc_files'] = cpc_files

    return JsonResponse(dict(
        success=True,
        previewTable=preview_table,
        previewDetails=preview_details,
    ))


class CpcAnnotationsUploadConfirmView(AnnotationsUploadConfirmView):
    cpc_info = None

    def extra_source_level_actions(self, request, source):
        self.cpc_files = request.session.pop('cpc_files', None)

        # Save some defaults for future CPC exports. Here we get the code
        # filepath and image dir from any one of the uploaded CPCs.
        # Chances are they'll be the same for all uploaded CPCs, or they
        # might not - either way, this is just a default and doesn't have
        # to be perfect.
        image_id, cpc_file_dict = next(iter(self.cpc_files.items()))

        cpc = CpcFileContent.from_stream(
            StringIO(cpc_file_dict['cpc_content'], newline=''))

        source.cpce_code_filepath = cpc.code_filepath
        source.cpce_image_dir = cpc.get_image_dir(image_id)
        source.save()

    def update_image_and_metadata_fields(self, image, new_points):
        super().update_image_and_metadata_fields(image, new_points)

        # Save uploaded CPC contents for future CPC exports.
        # Note: Since cpc_files went through session serialization,
        # the integer dict keys became stringified.
        image.cpc_content = self.cpc_files[str(image.pk)]['cpc_content']
        image.cpc_filename = self.cpc_files[str(image.pk)]['filename']
        image.save()


decorators = [
    source_permission_required(
        'source_id', perm=Source.PermTypes.EDIT.code, ajax=True)]
@method_decorator(decorators, name='dispatch')
class ExportPrepareAjaxView(View):
    """
    This is the first view after requesting a CPC export.
    Process the request fields, create the requested CPCs, and save them
    to the session. If there are any errors, report them with JSON.
    """
    confidence_threshold: float
    cpc_prefs: dict
    image_set: QuerySet
    labelset_dict: dict

    def post(self, request, source_id):
        source = get_object_or_404(Source, id=source_id)

        try:
            self.image_set, _ = get_request_images(request, source)
        except ValidationError as e:
            return JsonResponse(dict(
                error=e.message
            ))

        cpc_export_form = CpcExportForm(source, self.image_set, request.POST)
        if not cpc_export_form.is_valid():
            return JsonResponse(dict(
                error=get_one_form_error(cpc_export_form),
            ))

        self.cpc_prefs = cpc_export_form.cleaned_data
        self.labelset_dict = source.labelset.global_pk_to_code_dict()
        self.confidence_threshold = source.confidence_threshold
        # Create a dict of filenames to CPC-file-content strings
        cpc_strings = self.create_cpc_strings()
        # Save CPC prefs to the database for use next time
        source.cpce_code_filepath = self.cpc_prefs['local_code_filepath']
        source.cpce_image_dir = self.cpc_prefs['local_image_dir']
        source.save()

        session_data_timestamp = save_session_data(
            request.session, 'cpc_export', cpc_strings)

        return JsonResponse(dict(
            session_data_timestamp=session_data_timestamp,
            success=True,
        ))

    def create_cpc_strings(self):
        # Dict mapping from cpc filenames to cpc file contents as strings.
        cpc_strings = dict()

        for img in self.image_set:
            # Write .cpc contents to a stream.
            cpc_stream = StringIO()

            if img.cpc_content and img.cpc_filename:
                # A CPC file was uploaded for this image before.
                self.write_annotations_cpc_based_on_prev_cpc(cpc_stream, img)
                # Use the same CPC filename that was used for this image before.
                cpc_filename = img.cpc_filename
            else:
                # No CPC file was uploaded for this image before.
                self.write_annotations_cpc(cpc_stream, img)
                # Make a CPC filename based on the image filename, like CPCe does.
                # PWP ensures that both forward slashes and backslashes are counted
                # as path separators.
                cpc_filename = self.image_filename_to_cpc_filename(
                    PureWindowsPath(img.metadata.name).name)

            # If the image name seems to be a relative path (not just a filename),
            # then use those path directories on the CPC .zip filepath as well.
            image_parent = PureWindowsPath(img.metadata.name).parent
            # If it's a relative path, this appends the directories, else this
            # appends nothing.
            cpc_filepath = str(PureWindowsPath(image_parent, cpc_filename))
            # We've used Windows paths for path-separator flexibility up to this
            # point. Now that we're finished with path manipulations, we'll make
            # sure all separators are forward slashes for .zip export purposes.
            # This makes zip directory tree structures work on every OS. Forward
            # slashes are also required by the .ZIP File Format Specification.
            # https://superuser.com/a/1382853/
            cpc_filepath = cpc_filepath.replace('\\', '/')

            # Convert the stream contents to a string.
            # TODO: If cpc_filepath is already in the cpc_strings dict, then we
            # have a name conflict and need to warn / disambiguate.
            cpc_strings[cpc_filepath] = cpc_stream.getvalue()

        return cpc_strings

    def write_annotations_cpc(self, cpc_stream: StringIO, img: Image):
        """
        Write a CPC from scratch.
        """
        code_filepath = self.cpc_prefs['local_code_filepath']
        image_filepath = str(PureWindowsPath(
            self.cpc_prefs['local_image_dir'], img.metadata.name))

        # Image dimensions. CPCe typically operates in units of 1/15th of a
        # pixel. If a different DPI setting is used in an older version of CPCe
        # (like CPCe 3.5), it can be something else like 1/12th. But we'll
        # assume 1/15th for export.
        image_width = img.original_width * 15
        image_height = img.original_height * 15

        # This seems to be the display width/height that the image
        # was opened at in CPCe. Last opened? Initially opened? Not sure.
        # Is this ever even used when opening the CPC file? As far as we know,
        # no. We'll just arbitrarily set this to 960x720.
        # The CPCe documentation says CPCe works best with 1024x768 resolution
        # and above, so displaying the image itself at 960x720 is roughly
        # around there.
        display_width = 960 * 15
        display_height = 720 * 15

        # Annotation area bounds.
        # <x from left>,<y from top> in units of 1/15th of a pixel.
        # Order: Bottom left, bottom right, top right, top left.
        # Get from the image model if present, otherwise make it the whole image.

        anno_area = AnnotationArea.from_db_value(img.metadata.annotation_area)
        try:
            anno_area = AnnotationArea.to_pixels(
                anno_area, width=img.original_width, height=img.original_height)
        except ValueError:
            # Unspecified pixels (i.e. imported); just use the whole image
            anno_area = AnnotationArea(
                type=AnnotationArea.TYPE_PIXELS,
                min_x=0, max_x=img.max_column,
                min_y=0, max_y=img.max_row)

        bound_left = str(anno_area.min_x * 15)
        bound_right = str(anno_area.max_x * 15)
        bound_top = str(anno_area.min_y * 15)
        bound_bottom = str(anno_area.max_y * 15)
        annotation_area = dict(
            bottom_left=[bound_left, bound_bottom],
            bottom_right=[bound_right, bound_bottom],
            top_right=[bound_right, bound_top],
            top_left=[bound_left, bound_top],
        )

        # Points.

        point_set_values, score_set_values_per_point = (
            self.point_score_values_for_image(img))

        points = []

        for point_values in point_set_values:

            # Point positions, as ints.
            # <x from left, y from top> of each point in numerical order,
            # seemingly using the x15 scaling.
            # CPCe point positions are on a scale of 15 units = 1 pixel, and
            # the positions start from 0.
            point_left = point_values['column'] * 15
            point_top = point_values['row'] * 15

            # Point identification.
            # "<point number/letter>","<label code>","Notes","<notes code>"

            label_code = self.point_to_cpc_export_label_code(
                point_values,
                score_set_values_per_point[point_values['id']],
            )

            if self.cpc_prefs['label_mapping'] == 'id_and_notes' and '+' in label_code:
                # Assumption: label code in CoralNet source's labelset
                # == {ID}+{Notes} in the .cpc file (case insensitive),
                # and {ID} does not have a + character in it.
                cpc_id, cpc_notes = label_code.split('+', maxsplit=1)
            else:
                # Assumption: label code in CoralNet source's labelset
                # == ID code in the .cpc file (case insensitive).
                cpc_id = label_code
                cpc_notes = ''

            points.append(dict(
                x=point_left,
                y=point_top,
                number_label=str(point_values['point_number']),
                id=cpc_id,
                notes=cpc_notes,
            ))

        # Header fields. CPCe 4.1 has empty strings by default. Other versions
        # have ' ' by default. Still other versions, like 3.5, have no header
        # lines at all. We'll go with CPCe 4.1 (latest) behavior.
        headers = ['']*28

        cpc = CpcFileContent(
            code_filepath,
            image_filepath,
            image_width,
            image_height,
            display_width,
            display_height,
            annotation_area,
            points,
            headers,
        )
        cpc.write_cpc(cpc_stream)

    def write_annotations_cpc_based_on_prev_cpc(
            self, cpc_stream: StringIO, img: Image):

        cpc = CpcFileContent.from_stream(StringIO(img.cpc_content, newline=''))

        if self.cpc_prefs['override_filepaths'] == 'yes':
            # Set environment info from cpc prefs.
            cpc.code_filepath = self.cpc_prefs['local_code_filepath']
            cpc.image_filepath = str(PureWindowsPath(
                self.cpc_prefs['local_image_dir'], img.metadata.name))

        # Points: Replace the ID codes (and notes, if applicable)
        # with the data from CoralNet's DB.

        # point_set_values should be in point-number order (as ensured
        # by the method we call here).
        point_set_values, score_set_values_per_point = (
            self.point_score_values_for_image(img))

        for point_index, point_values in enumerate(point_set_values):
            point = cpc.points[point_index]
            label_code = self.point_to_cpc_export_label_code(
                point_values,
                score_set_values_per_point[point_values['id']],
            )

            if self.cpc_prefs['label_mapping'] == 'id_and_notes':
                # Get ID + Notes from CoralNet's label codes.
                if '+' in label_code:
                    point['id'], point['notes'] = label_code.split('+', maxsplit=1)
                else:
                    point['id'] = label_code
                    point['notes'] = ''
            else:
                # Only get ID from CoralNet's label codes. Leave Notes unchanged.
                point['id'] = label_code

        cpc.write_cpc(cpc_stream)

    @staticmethod
    def point_score_values_for_image(image):
        """
        Database values this view needs regarding an image's points.
        """
        point_set_values = image.point_set.order_by('point_number').values(
            'id',
            'point_number',
            'column',
            'row',
            'annotation',
            'annotation__label',
            'annotation__user',
        )

        score_set_values = Score.objects.filter(point__image=image).values(
            'point',
            'score',
        )
        score_set_values_per_point = defaultdict(list)
        for score_values in score_set_values:
            point_id = score_values['point']
            score_set_values_per_point[point_id].append(score_values)

        return point_set_values, score_set_values_per_point

    def point_to_cpc_export_label_code(
            self,
            point_values: dict,
            score_set_values: list[dict]) -> str:
        """
        Normally, annotation export will export ALL annotations, including
        machine annotations of low confidence. This is usually okay because,
        if users want to exclude Unconfirmed annotations when exporting,
        they can filter images to just Confirmed and then export from there.

        However, this breaks down in CPC export's use case: CPC import,
        add confident machine annotations, and then CPC export to continue
        annotating in CPCe. These users will expect to only export the
        confident machine annotations, and confidence is on a per-point
        basis, not per-image. So we need to filter the annotations on a
        point basis. That's what this method is for.

        CPC export's annotation_filter option controls which annotations
        to accept:
        'confirmed_only' to denote that only Confirmed annotations are
        accepted.
        'confirmed_and_confident' to denote that Unconfirmed annotations
        above the source's confidence threshold are also accepted.
        Normally, these annotations will become Confirmed when you enter the
        annotation tool for that image... but if you're planning to annotate
        in CPCe, there's no other reason to enter the annotation tool!

        :param point_values: values() of a Point model instance.
        :param score_set_values: values() of the Score model instances
          corresponding to the Point.
        :return: Label short code string of the point's annotation, if there is
          an annotation which is accepted by the annotation_filter. Otherwise, ''.
        """
        if point_values['annotation']:
            if point_values['annotation__user'] == get_robot_user().pk:
                annotation_status = 'unconfirmed'
            else:
                annotation_status = 'confirmed'
        else:
            annotation_status = 'unclassified'

        if annotation_status == 'confirmed':

            # Confirmed annotations are always included.
            return self.point_to_label_code(point_values)

        elif (self.cpc_prefs['annotation_filter'] == 'confirmed_and_confident'
              and annotation_status == 'unconfirmed'):

            # With this annotation_filter, Unconfirmed annotations are
            # included IF they're above the source's confidence threshold.
            if len(score_set_values) > 0:
                machine_confidence = max(s['score'] for s in score_set_values)
                if machine_confidence >= self.confidence_threshold:
                    return self.point_to_label_code(point_values)

        # The annotation filter rejects this annotation, or there is no
        # annotation
        return ''

    def point_to_label_code(self, point_values: dict) -> str:
        if point_values['annotation']:
            return self.labelset_dict[point_values['annotation__label']]
        return ''

    @staticmethod
    def image_filename_to_cpc_filename(image_filename):
        """
        Take an image filename string and convert to a cpc filename according
        to CPCe's rules. As far as we can tell, it's simple: strip extension,
        add '.cpc'. Examples:
        IMG_0001.JPG -> IMG_0001.cpc
        img 0001.jpg -> img 0001.cpc
        my_image.bmp -> my_image.cpc
        another_image.gif -> another_image.cpc
        """
        cpc_filename = PureWindowsPath(image_filename).stem + '.cpc'
        return cpc_filename


@source_permission_required('source_id', perm=Source.PermTypes.EDIT.code)
@require_GET
@session_key_required(
    key='cpc_export',
    error_redirect=['browse_images', 'source_id'],
    error_prefix="Export failed")
@transaction.non_atomic_requests
def export_serve(request, source_id, session_data):
    """
    This is the second view after requesting a CPC export.
    Grab the previously crafted CPCs from the session, and serve them in a
    zip file.
    """
    return create_zipped_cpcs_stream_response(
        session_data, 'annotations_cpc.zip')


@login_required
def cpc_batch_editor(request):
    return render(request, 'cpce/cpc_batch_editor.html', {
        'process_form': CpcBatchEditSpecForm(),
    })


@login_required_ajax
@require_POST
def cpc_batch_editor_process_ajax(request):
    cpcs_form = CpcBatchEditCpcsForm(request.POST, request.FILES)
    spec_form = CpcBatchEditSpecForm(request.POST, request.FILES)

    if not cpcs_form.is_valid():
        return JsonResponse(dict(
            error=get_one_form_error(cpcs_form),
        ))
    if not spec_form.is_valid():
        return JsonResponse(dict(
            error=get_one_form_error(spec_form),
        ))

    spec_fields_option = spec_form.cleaned_data['label_spec_fields']
    try:
        label_spec = cpc_editor_csv_to_dicts(
            text_file_to_unicode_stream(
                spec_form.cleaned_data['label_spec_csv']),
            spec_fields_option,
        )
    except FileProcessError as error:
        return JsonResponse(dict(
            error=str(error),
        ))

    cpc_files = cpcs_form.cleaned_data['cpc_files']
    filepath_lookup = json.loads(cpcs_form.cleaned_data['cpc_filepaths'])
    cpc_strings = dict()
    preview_details = dict(
        num_files=len(cpc_files),
        label_spec=label_spec,
    )
    for cpc_file in cpc_files:
        # Read in a cpc file
        cpc_stream = text_file_to_unicode_stream(cpc_file)
        # Edit the cpc file
        filepath = filepath_lookup[cpc_file.name]
        cpc_strings[filepath] = cpc_edit_labels(
            cpc_stream, label_spec, spec_fields_option)

    session_data_timestamp = save_session_data(
        request.session, 'cpc_batch_editor', cpc_strings)

    return JsonResponse(dict(
        session_data_timestamp=session_data_timestamp,
        preview_details=preview_details,
        success=True,
    ))


@login_required
@require_GET
@session_key_required(
    key='cpc_batch_editor',
    error_redirect='cpce:cpc_batch_editor',
    error_prefix="Batch edit failed")
def cpc_batch_editor_file_serve(request, session_data):
    return create_zipped_cpcs_stream_response(
        session_data, 'edited_cpcs.zip')
