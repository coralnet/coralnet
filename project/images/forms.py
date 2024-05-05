from django.conf import settings
from django.core.exceptions import ValidationError
from django.forms import BaseModelFormSet, ModelForm
from django.forms.fields import ChoiceField, IntegerField, MultiValueField
from django.forms.widgets import TextInput

from lib.forms import EnhancedMultiWidget
from .model_utils import PointGen, PointGenerationTypes
from .models import Metadata


class MetadataForm(ModelForm):
    """
    Edit metadata of an image.
    """
    class Meta:
        model = Metadata
        fields = Metadata.EDIT_FORM_FIELDS

    def __init__(self, *args, **kwargs):
        self.source = kwargs.pop('source')
        super().__init__(*args, **kwargs)

        # Specify aux. fields' labels. These depend on the source,
        # so this must be done during init.
        self.fields['aux1'].label = self.source.key1
        self.fields['aux2'].label = self.source.key2
        self.fields['aux3'].label = self.source.key3
        self.fields['aux4'].label = self.source.key4
        self.fields['aux5'].label = self.source.key5

        # Specify fields' size attributes. This is done during init so that
        # we can modify existing widgets, thus avoiding having to manually
        # re-specify the widget class and attributes besides size.
        field_sizes = dict(
            name=30,
            photo_date=8,
            aux1=10,
            aux2=10,
            aux3=10,
            aux4=10,
            aux5=10,
            height_in_cm=10,
            latitude=10,
            longitude=10,
            depth=10,
            camera=10,
            photographer=10,
            water_quality=10,
            strobes=10,
            framing=16,
            balance=16,
        )
        for field_name, field_size in field_sizes.items():
            self.fields[field_name].widget.attrs['size'] = str(field_size)


class MetadataFormForGrid(MetadataForm):
    """
    Metadata form which is used in the metadata-edit grid view.
    """
    class Meta:
        model = Metadata
        fields = Metadata.EDIT_FORM_FIELDS
        widgets = {
            # Our metadata-edit grid Javascript is wonky with a
            # NumberInput widget.
            #
            # Browser-side checking makes the value not submit
            # if it thinks the input is erroneous, leading to
            # our Ajax returning "This field is required" when the field
            # actually is filled with an erroneous value.
            # Only change this to NumberInput if we have a good solution
            # for this issue.
            'height_in_cm': TextInput(attrs={'size': 10}),
        }


class BaseMetadataFormSet(BaseModelFormSet):
    def clean(self):
        """
        Checks that no two images in the source have the same name.
        """
        if any(self.errors):
            # Don't bother validating the formset
            # unless each form is valid on its own
            return

        source = self.forms[0].source
        # For some reason, there is an extra form at the end which has
        # no valid values...
        actual_forms = self.forms[:-1]

        # Find dupe image names in the source, taking together the
        # existing names of images not in the forms, and the new names
        # of images in the forms
        pks_in_forms = [f.instance.pk for f in actual_forms]
        names_not_in_forms = list(
            Metadata.objects
            .filter(image__source=source)
            .exclude(pk__in=pks_in_forms)
            .values_list('name', flat=True)
        )
        names_in_forms = [f.cleaned_data['name'] for f in actual_forms]
        all_names = names_not_in_forms + names_in_forms
        dupe_names = [
            name for name in all_names
            if all_names.count(name) > 1
        ]

        for form in actual_forms:
            name = form.cleaned_data['name']
            if name in dupe_names:
                form.add_error(
                    'name',
                    ValidationError(
                        "Same name as another image in"
                        " the source or this form",
                        code='dupe_name',
                    )
                )


class PointGenWidget(EnhancedMultiWidget):

    template_name = 'images/point_gen_field.html'

    use_subfield_labels = True

    visibility_specs = {
        # Conditionally visible field: (
        #     control field,
        #     control value(s) that would make the field visible,
        # )
        'points': (
            'type',
            [PointGen.Types.SIMPLE.value],
        ),

        'cell_rows': (
            'type',
            [PointGen.Types.STRATIFIED.value,
             PointGen.Types.UNIFORM.value],
        ),

        'cell_columns': (
            'type',
            [PointGen.Types.STRATIFIED.value,
             PointGen.Types.UNIFORM.value],
        ),

        'per_cell': (
            'type',
            [PointGen.Types.STRATIFIED.value],
        ),
    }

    def decompress(self, value):
        point_gen_spec = PointGen.from_db_value(value)
        return [
            getattr(point_gen_spec, field_name, None)
            for field_name in self.field.field_order
        ]


number_error_messages = {
    'min_value': "Please use positive integers only.",
}


class PointGenField(MultiValueField):
    # To be filled in by __init__()
    widget = None

    type = ChoiceField(
        label='Point generation type',
        choices=PointGenerationTypes.choices,
        # Seems the 'incomplete' message is used when a subfield
        # like this is required and not filled in.
        error_messages={'incomplete': "Missing type value."},
    )

    # For simple random
    points = IntegerField(
        label='Number of points', required=False, min_value=1,
        error_messages=number_error_messages,
    )

    # For stratified random and uniform grid
    cell_rows = IntegerField(
        label='Number of cell rows', required=False, min_value=1,
        error_messages=number_error_messages,
    )
    cell_columns = IntegerField(
        label='Number of cell columns', required=False, min_value=1,
        error_messages=number_error_messages,
    )

    # For stratified random
    per_cell = IntegerField(
        label='Points per cell', required=False, min_value=1,
        error_messages=number_error_messages,
    )

    field_order = PointGen.source_form_field_order

    def __init__(self, **kwargs):
        self.widget = PointGenWidget(field=self)

        self.points.widget.attrs |= {'size': 3}
        self.cell_rows.widget.attrs |= {'size': 3}
        self.cell_columns.widget.attrs |= {'size': 3}
        self.per_cell.widget.attrs |= {'size': 3}

        # Some kwargs from the model field (which would be passed in by a
        # ModelForm) can't be applied directly to MultiValueField.
        kwargs.pop('max_length')

        super().__init__(
            fields=[
                getattr(self, field_name) for field_name in self.field_order],
            require_all_fields=False, **kwargs)

    def compress(self, data_list):
        # For DateFilterField, data_list was empty sometimes. Not sure if that
        # also applies to this field, but here's a case to handle it.
        if not data_list:
            return dict()

        field_values = {
            field_name: data_list[index]
            for index, field_name in enumerate(self.field_order)
        }
        field_labels = {
            field_name: getattr(self, field_name).label
            for field_name in self.field_order
        }

        point_gen_spec = PointGen(**field_values)

        # Validate that the applicable fields are present for the type.
        missing_fields = [
            name for name in point_gen_spec.number_fields
            if getattr(point_gen_spec, name) is None
        ]
        if missing_fields:
            missing_values_str = ', '.join([
                field_labels[name] for name in missing_fields])
            raise ValidationError(
                f"Missing value(s): {missing_values_str}",
                code='incomplete')

        point_count = point_gen_spec.total_points
        if point_count > settings.MAX_POINTS_PER_IMAGE:
            raise ValidationError(
                f"You specified {point_count} points total."
                f" Please make it no more than"
                f" {settings.MAX_POINTS_PER_IMAGE}.",
                code='too_many_points')

        return point_gen_spec.db_value
