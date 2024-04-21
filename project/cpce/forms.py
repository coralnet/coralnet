from django.core.exceptions import ValidationError
from django.forms import Form
from django.forms.fields import CharField, ChoiceField
from django.forms.widgets import FileInput, HiddenInput, RadioSelect, TextInput
from django.utils.safestring import mark_safe

from sources.models import Source
from upload.forms import CsvFileField, MultipleFileField
from upload.utils import text_file_to_unicode_stream
from .utils import get_previous_cpcs_status, labelset_has_plus_code


class CpcFilesField(MultipleFileField):
    default_error_messages = {
        'required': "Please select one or more CPC files.",
    }

    def clean(self, data, initial=None):
        """
        Check for extensions of .cpc. This isn't foolproof, but it can
        catch simple file selection mistakes.
        """
        for cpc_file in data:
            if not cpc_file.name.endswith('.cpc'):
                raise ValidationError(
                    "This is not a CPC file: {fn}".format(fn=cpc_file.name))

        return super().clean(data, initial)

    def widget_attrs(self, widget):
        attrs = super().widget_attrs(widget)
        if isinstance(widget, FileInput) and 'accept' not in widget.attrs:
            attrs.setdefault('accept', '.cpc')
        return attrs


class CpcImportForm(Form):
    cpc_files = CpcFilesField(label='CPC files')
    label_mapping = ChoiceField(
        label="Determine CoralNet label codes from",
        choices=(
            ('id_only',
             "ID field only"),
            ('id_and_notes',
             "ID and Notes fields (using + character as a separator)"),
        ),
        widget=RadioSelect,
    )

    def __init__(self, source, *args, **kwargs):
        has_plus_code = (
            source.labelset and labelset_has_plus_code(source.labelset))
        kwargs['initial'] = dict(
            # Only use Notes by default if the labelset has codes with + in
            # them. Otherwise, the uploader probably didn't intend to use
            # the ID+Notes concat feature, and any Notes present in the
            # CPC files would make the upload fail.
            label_mapping='id_and_notes' if has_plus_code else 'id_only',
        )
        super().__init__(*args, **kwargs)

    def get_cpc_names_and_streams(self):
        cpc_names_and_streams = []
        for cpc_file in self.cleaned_data['cpc_files']:
            cpc_unicode_stream = text_file_to_unicode_stream(cpc_file)
            cpc_names_and_streams.append((cpc_file.name, cpc_unicode_stream))
        return cpc_names_and_streams


class CpcExportForm(Form):
    annotation_filter = None  # See __init__()
    override_filepaths = None  # See __init__()

    local_image_dir = CharField(
        label="Folder with images",
        max_length=Source._meta.get_field('cpce_image_dir').max_length,
        widget=TextInput(attrs={'class': 'cpc-filepath'}))
    local_code_filepath = CharField(
        label="Code file",
        max_length=Source._meta.get_field('cpce_code_filepath').max_length,
        widget=TextInput(attrs={'class': 'cpc-filepath'}))

    label_mapping = ChoiceField(
        label="Map CoralNet label codes to",
        choices=(
            ('id_only',
             "ID field only"),
            ('id_and_notes',
             "ID and Notes fields (using + character as a separator)"),
        ),
        widget=RadioSelect,
    )

    def __init__(self, source, image_results, *args, **kwargs):
        has_plus_code = (
            source.labelset and labelset_has_plus_code(source.labelset))
        kwargs['initial'] = dict(
            local_image_dir=source.cpce_image_dir,
            local_code_filepath=source.cpce_code_filepath,
            # Only use Notes by default if the labelset has codes with + in
            # them. Otherwise, the user probably didn't intend to use
            # the ID+Notes concat feature, and if there were any
            # previously-uploaded CPC files which contained Notes, those
            # Notes would be excluded from this export.
            label_mapping='id_and_notes' if has_plus_code else 'id_only',
        )

        super().__init__(*args, **kwargs)

        # annotation_filter

        if source.confidence_threshold == 100:

            # Don't need to show this field, since there can be no unconfirmed
            # annotations above 100% confidence.
            self.fields['annotation_filter'] = CharField(
                widget=HiddenInput(), initial='confirmed_only')

        else:

            confirmed_and_confident_label = (
                f"Confirmed annotations AND Unconfirmed annotations"
                f" above the machine confidence threshold of"
                f" {source.confidence_threshold}%")

            self.fields['annotation_filter'] = ChoiceField(
                label="Annotations to include",
                choices=(
                    ('confirmed_only', "Confirmed annotations only"),
                    ('confirmed_and_confident', confirmed_and_confident_label),
                ),
                initial='confirmed_only',
                widget=RadioSelect,
            )

        # override_filepaths

        override_filepaths_kwargs = dict(
            label="Use CPCe environment info from",
            initial='no',
            widget=RadioSelect,
        )
        previous_cpcs_status = get_previous_cpcs_status(image_results)

        if previous_cpcs_status == 'all':

            override_filepaths_kwargs['choices'] = (
                ('no', "Previously-uploaded CPC files"),
                ('yes', "The two fields below"),
            )
            self.fields['override_filepaths'] = ChoiceField(
                **override_filepaths_kwargs)
            self.previous_cpcs_help_text = mark_safe(
               "<strong>All of the images</strong> in this search"
               " have previously-uploaded CPC files available.")

        elif previous_cpcs_status == 'some':

            override_filepaths_kwargs['choices'] = (
                ('no', "Previously-uploaded CPC files (if present),"
                       " otherwise the two fields below"),
                ('yes', "The two fields below (for the whole image set)"),
            )
            self.fields['override_filepaths'] = ChoiceField(
                **override_filepaths_kwargs)
            self.previous_cpcs_help_text = mark_safe(
                "<strong>Some of the images</strong> in this search"
                " have previously-uploaded CPC files available.")

        else:

            # 'none'
            # Don't need to show this field, since there are no previous
            # filepaths to override.
            self.fields['override_filepaths'] = CharField(
                widget=HiddenInput(), initial='no')
            self.previous_cpcs_help_text = mark_safe(
                "<strong>None of the images</strong> in this search"
                " have previously-uploaded CPC files available."
                " They will use the CPCe environment info in the text fields"
                " below.")

        self.order_fields([
            'override_filepaths', 'local_code_filepath', 'local_image_dir',
            'annotation_filter', 'label_mapping'])


class CpcBatchEditCpcsForm(Form):
    cpc_files = CpcFilesField()
    # Django doesn't readily support filepaths of file uploads, only
    # filenames. So we'll use this field to pass in filepaths of the CPCs.
    cpc_filepaths = CharField()


class CpcBatchEditSpecForm(Form):
    label_spec_fields = ChoiceField(
        label="Fields to process",
        choices=(
            ('id_only',
             "ID field only"),
            ('id_and_notes',
             "ID and Notes fields"),
        ),
        initial='id_only',
        widget=RadioSelect,
    )
    label_spec_csv = CsvFileField(label="CSV file")
