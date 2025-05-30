from abc import ABC
import collections
import csv
from io import BytesIO, StringIO

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
import pyexcel

from annotations.model_utils import ImageAnnoStatuses
from lib.decorators import (
    login_required_ajax,
    source_labelset_required,
    source_visibility_required,
)
from lib.forms import get_one_form_error
from lib.sessions import (
    get_session_data, save_session_data, session_error_response, SessionError)
from sources.models import Source
from sources.utils import metadata_field_names_to_labels
from .forms import ExportImageCoversForm
from .utils import (
    create_csv_stream_response,
    create_stream_response,
    create_zip_stream_response,
    file_to_session_data,
    get_request_images,
    session_data_to_file,
    write_labelset_csv,
)


# TODO: Use this View class to improve DRY among more of the export views.

decorators = [
    # Access control.
    source_visibility_required('source_id', ajax=True),
    # Most/all of these exports require annotations, which require a
    # labelset.
    source_labelset_required(
        'source_id', ajax=True,
        message="You must create a labelset before exporting data."),
    # These exports can be resource intensive, so no bots allowed.
    login_required_ajax,
    # This is a potentially slow view that doesn't modify the database
    # in a time-sensitive way.
    # So don't open a transaction for the view.
    transaction.non_atomic_requests]
@method_decorator(decorators, name='dispatch')
class SourceCsvExportPrepView(View, ABC):
    """
    Data export on a subset of an source's images.
    """
    def get_export_filename(self, source, suffix='.csv'):
        raise NotImplementedError

    def get_export_form(self, source, data):
        raise NotImplementedError

    def write_csv(self, stream, source, image_set, export_form_data):
        """
        Write CSV data to the given stream. Return the number of images in the
        CSV data (this may not necessarily match the size of the passed
        image_set - for example, if unannotated images are not applicable to
        the export subclass).
        """
        raise NotImplementedError

    def finish_workbook(self, book, source):
        """
        Finish the contents of the pyexcel.Book, and return the book.
        If an export subclass has nothing specific to add, then just
        return the book and do nothing else.
        """
        return book

    def post(self, request, source_id):
        """
        We define these views as POST, not GET, because we want to save
        database stats for some of the source-level exports.

        Also, none of the advantages of GET particularly apply to these
        export views (bookmarking the URL, bots indexing the response,
        avoiding browser resend warnings on Back/Refresh, etc.)
        """
        source = get_object_or_404(Source, id=source_id)

        try:
            image_set, applied_search_display = get_request_images(
                request, source)
        except ValidationError as e:
            return JsonResponse(dict(
                error=e.message,
            ))

        export_form = self.get_export_form(source, request.POST)
        if not export_form.is_valid():
            return JsonResponse(dict(
                error=get_one_form_error(export_form),
            ))

        if export_form.cleaned_data.get('export_format') == 'excel':

            # Excel with meta information in additional sheet(s)
            book = pyexcel.Book()

            csv_stream = StringIO()
            num_images_in_export = self.write_csv(
                csv_stream, source, image_set, export_form.cleaned_data)
            data_sheet = pyexcel.get_sheet(
                file_type='csv', file_content=csv_stream.getvalue())
            data_sheet.name = "Data"
            book += data_sheet

            meta_contents = [
                ["Source name", source.name],
                ["Image search method", applied_search_display],
                ["Images in export", num_images_in_export],
                ["Images in source", source.image_set.count()],
                ["Export date", timezone.now().isoformat()],
            ]
            meta_sheet = pyexcel.get_sheet(array=meta_contents)
            meta_sheet.name = "Meta"
            book += meta_sheet

            book = self.finish_workbook(book, source)

            # For some reason, pyexcel can't seem to accept HttpResponse as
            # a stream, so we give it a BytesIO instead.
            excel_stream = BytesIO()
            book.save_to_memory('xlsx', stream=excel_stream)
            session_data = file_to_session_data(
                filename=self.get_export_filename(source, '.xlsx'),
                io_stream=excel_stream,
                is_binary=True,
            )

        else:

            # CSV
            csv_stream = StringIO()
            self.write_csv(
                csv_stream, source, image_set, export_form.cleaned_data)
            session_data = file_to_session_data(
                filename=self.get_export_filename(source),
                io_stream=csv_stream,
                is_binary=False,
            )

        session_data_timestamp = save_session_data(
            request.session, 'export', session_data)

        return JsonResponse(dict(
            session_data_timestamp=session_data_timestamp,
            success=True,
        ))


class ExportServeView(View, ABC):

    session_key = 'export'
    session_error_redirect: list | str
    session_error_prefix: str

    def dispatch(self, request, *args, **kwargs):
        # Getting session data with a direct call instead of a decorator
        # allows defining the redirect and prefix with class variables,
        # which in turn allows subclasses to override those details.
        try:
            session_data = get_session_data(
                key=self.session_key, request=request)
        except SessionError as error:
            return session_error_response(
                error=error,
                request=request,
                redirect_spec=self.session_error_redirect,
                prefix=self.session_error_prefix,
                view_kwargs=kwargs,
            )

        # get() or post() must expect a session_data arg.
        return super().dispatch(
            request, *args, session_data=session_data, **kwargs)

    def get(self, request, session_data, **kwargs):
        filename, content = session_data_to_file(session_data)

        if filename.endswith('.csv'):
            response = create_csv_stream_response(filename)
        elif filename.endswith('.xlsx'):
            response = create_stream_response(
                'application/'
                'vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                filename)
        elif filename.endswith('.zip'):
            response = create_zip_stream_response(filename)
        else:
            raise ValueError(f"Unsupported filetype: {filename}")

        response.content = content
        return response


decorators = [
    source_visibility_required('source_id'),
    login_required,
]
@method_decorator(decorators, name='dispatch')
class SourceExportServeView(ExportServeView):
    """
    Serve an export prepared at the Browse Images page.
    """
    session_error_redirect = ['browse_images', 'source_id']
    session_error_prefix = "Export failed"


class ImageStatsExportPrepView(SourceCsvExportPrepView, ABC):
    """
    Stats export where each row pertains to a single image's annotation data.
    """

    def finish_fieldnames_and_image_loop_prep(
            self, fieldnames, export_form_data):
        raise NotImplementedError

    def image_loop_main_body(
            self, row, label_counter, num_annotations_in_image):
        raise NotImplementedError

    def finish_summary_row(self, summary_row, num_annotated_images):
        raise NotImplementedError

    @staticmethod
    def float_format(flt):
        """Limit decimal places in the CSV's final numbers."""

        # Always 3 decimal places (even if the trailing places are 0).
        s = format(flt, '.3f')
        if s == '-0.000':
            # Python has negative 0, but we don't care for that here.
            return '0.000'
        return s

    def write_csv(self, stream, source, image_set, export_form_data):

        # Make a dict of global label IDs to string displays for the
        # source's labelset. The form of the string display depends on the
        # export form's data.
        # The dict is ordered by functional group and then name/code
        # (note that regular dicts remember insertion order in Python 3.6+).
        if export_form_data['label_display'] == 'name':
            self.label_ids_to_displays = {
                global_label.pk: global_label.name
                for global_label
                in source.labelset.get_globals().order_by('group', 'name')
            }
        else:
            # 'code'
            self.label_ids_to_displays = {
                local_label.global_label.pk: local_label.code
                for local_label
                in source.labelset.get_locals_ordered_by_group_and_code()
            }

        # Header row.
        fieldnames = ["Image ID", "Image name", "Annotation status", "Points"]
        fieldnames = self.finish_fieldnames_and_image_loop_prep(
            fieldnames, export_form_data)

        num_annotated_images = 0

        writer = csv.DictWriter(stream, fieldnames)
        writer.writeheader()

        # Unannotated or partially annotated images probably
        # won't be useful to export, and they'll skew the summary
        # stats as well.
        image_set = image_set.exclude(
            annoinfo__status=ImageAnnoStatuses.UNCLASSIFIED.value)

        # One row per image
        for image in image_set \
                .select_related('annoinfo', 'features', 'metadata') \
                .annotate(num_points=Count('point')):

            num_annotated_images += 1

            # Counter for annotations of each label. Initialize by giving each
            # label a 0 count.
            label_counter = collections.Counter({
                label_id: 0
                for label_id in self.label_ids_to_displays.keys()
            })

            # This runs one database query per image, but there doesn't seem to
            # be a way to avoid that without blowing up the export's memory
            # requirements (i.e. loading all annotations at once).
            annotation_labels = image.annotation_set.values_list(
                'label_id', flat=True)
            annotation_labels = [pk for pk in annotation_labels]
            label_counter.update(annotation_labels)
            num_annotations_in_image = len(annotation_labels)

            row = {
                "Image ID": image.pk,
                "Image name": image.metadata.name,
                "Annotation status": image.annoinfo.status_display,
                "Points": image.num_points,
            }
            row = self.image_loop_main_body(
                row, label_counter, num_annotations_in_image)
            writer.writerow(row)

        if num_annotated_images > 1:

            summary_row = {
                "Image ID": "ALL IMAGES",
                "Image name": "",
                "Annotation status": "",
                "Points": "",
            }
            summary_row = self.finish_summary_row(
                summary_row, num_annotated_images)
            writer.writerow(summary_row)

        return num_annotated_images


@source_visibility_required('source_id')
@login_required
@transaction.non_atomic_requests
def export_metadata(request, source_id):
    source = get_object_or_404(Source, id=source_id)

    try:
        image_set, _ = get_request_images(request, source)
    except ValidationError as e:
        messages.error(request, e.message)
        return HttpResponseRedirect(
            reverse('browse_images', args=[source_id]))

    response = create_csv_stream_response('metadata.csv')
    writer = csv.writer(response)

    # Get the metadata fields that we'll write CSV for.
    field_names_to_labels = metadata_field_names_to_labels(source)

    # Header row
    writer.writerow(field_names_to_labels.values())

    # Metadata, one row per image
    for image in image_set:
        row = []
        for field_name in field_names_to_labels.keys():
            # Use getattr on the Metadata model object to get the
            # metadata values. If the value is None, write ''.
            value = getattr(image.metadata, field_name)
            if value is None:
                value = ''
            row.append(value)
        writer.writerow(row)

    return response


class ImageCoversExportPrepView(ImageStatsExportPrepView):

    def get_export_filename(self, source, suffix='.csv'):
        return f'percent_covers{suffix}'

    def get_export_form(self, source, data):
        return ExportImageCoversForm(data)

    def finish_fieldnames_and_image_loop_prep(
            self, fieldnames, export_form_data):

        # One column per label
        fieldnames.extend(self.label_ids_to_displays.values())

        self.coverage_sums = collections.defaultdict(float)

        return fieldnames

    def image_loop_main_body(
            self, row, label_counter, num_annotations_in_image):

        for label_id, count in label_counter.items():

            label_display = self.label_ids_to_displays[label_id]

            coverage_fraction = count / num_annotations_in_image
            coverage_percent_str = self.float_format(
                coverage_fraction * 100.0)
            row[label_display] = coverage_percent_str

            # Add to summary stats computation
            self.coverage_sums[label_display] += coverage_fraction

        return row

    def finish_summary_row(self, summary_row, num_annotated_images):

        for label_display in self.label_ids_to_displays.values():
            summary_row[label_display] = self.float_format(
                100.0 * self.coverage_sums[label_display]
                / num_annotated_images)

        return summary_row


@source_visibility_required('source_id')
@transaction.non_atomic_requests
def export_labelset(request, source_id):
    source = get_object_or_404(Source, id=source_id)

    response = create_csv_stream_response('labelset.csv')
    writer = csv.writer(response)
    write_labelset_csv(writer, source)

    return response
