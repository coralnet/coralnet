from django.forms import Form
from django.forms.fields import ChoiceField
from django.forms.widgets import RadioSelect


class ExportImageStatsForm(Form):
    """Form for ImageStatsExportView."""
    label_display = ChoiceField(
        label="Label displays in column headers",
        choices=(
            ('code', "Short code"),
            ('name', "Full name"),
        ),
        initial='code',
        widget=RadioSelect,
    )

    export_format = ChoiceField(
        label="Export format",
        choices=(
            ('csv', "CSV"),
            ('excel',
             "Excel workbook with meta information"
             " (image search filters, etc.)"),
        ),
        initial='csv',
        widget=RadioSelect,
    )


class ExportImageCoversForm(ExportImageStatsForm):
    pass
