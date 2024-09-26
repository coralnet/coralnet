from django.core.exceptions import ValidationError
from django.forms import ModelForm
from django.forms.fields import ChoiceField, MultipleChoiceField
from django.forms.widgets import CheckboxSelectMultiple, Textarea

from export.forms import ExportImageStatsForm
from upload.forms import CsvFileField
from .models import CalcifyRateTable
from .utils import get_global_calcify_tables


def get_calcify_table_choices(source):
    # Source's tables
    choices = [
        (table.pk, table.name)
        for table in source.calcifyratetable_set.order_by('name')
    ]

    # Default tables
    default_tables = get_global_calcify_tables()
    choices.extend([
        (table.pk, table.name)
        for table in default_tables
    ])

    return choices


class ExportCalcifyStatsForm(ExportImageStatsForm):
    rate_table_id = ChoiceField(
        label="Label rates to use")

    optional_columns = MultipleChoiceField(
        widget=CheckboxSelectMultiple, required=False)

    field_order = ['rate_table_id', 'optional_columns', 'label_display']

    def __init__(self, source, *args, **kwargs):

        super().__init__(*args, **kwargs)

        # TODO: The best thing to do is to remove all possibility of
        # initializing this form without a labelset, and then remove this
        # conditional.
        if source.labelset:
            labelset_size = source.labelset.get_labels().count()
        else:
            labelset_size = 0

        self.fields['rate_table_id'].choices = \
            get_calcify_table_choices(source)

        self.fields['optional_columns'].choices = (
            ('per_label_mean',
             "Per-label contributions to mean rate"
             f" (adds {labelset_size} columns)"),
            ('per_label_bounds',
             "Per-label contributions to confidence bounds"
             f" (adds {labelset_size * 2} columns)"),
        )


class CalcifyRateTableForm(ModelForm):
    csv_file = CsvFileField(label='CSV file')

    class Meta:
        model = CalcifyRateTable
        fields = ['name', 'description']
        widgets = {
            'description': Textarea(),
        }

    def __init__(self, source, *args, **kwargs):
        self.source = source
        super().__init__(*args, **kwargs)

    def clean_name(self):
        """
        Check for uniqueness within the source. The ModelForm doesn't
        validate this automatically because the source isn't a field in the
        form.
        """
        name = self.cleaned_data['name']
        try:
            CalcifyRateTable.objects.get(source=self.source, name=name)
            raise ValidationError(
                "This source already has a rate table with the same name.")
        except CalcifyRateTable.DoesNotExist:
            # This name isn't taken yet, so it's valid.
            return name
