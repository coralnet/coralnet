from django.conf import settings
from django.core.exceptions import ValidationError
from django.forms import BaseModelFormSet, Form, ModelForm
from django.forms.fields import ChoiceField, IntegerField
from django.forms.widgets import NumberInput, Select, TextInput

from .model_utils import PointGen
from .models import Metadata, Source


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


class PointGenForm(Form):

    class Media:
        js = (
            "js/PointGenFormHelper.js",
        )

    point_generation_type = ChoiceField(
        label='Point generation type',
        choices=Source.POINT_GENERATION_CHOICES,
        widget=Select(
            attrs={'onchange': 'PointGenFormHelper.showOnlyRelevantFields()'}),
    )

    # The following fields may or may not be required depending on the
    # point_generation_type. We'll make all of them not required by default
    # (so that browser-side required field checks don't block form submission),
    # Then in clean(), we'll account for errors on fields that
    # we decide are required.

    # For simple random
    simple_number_of_points = IntegerField(
        label='Number of annotation points', required=False,
        min_value=1, max_value=settings.MAX_POINTS_PER_IMAGE,
        widget=NumberInput(attrs={'size': 3}),
    )

    # For stratified random and uniform grid
    number_of_cell_rows = IntegerField(
        label='Number of cell rows', required=False,
        min_value=1, max_value=settings.MAX_POINTS_PER_IMAGE,
        widget=NumberInput(attrs={'size': 3}),
    )
    number_of_cell_columns = IntegerField(
        label='Number of cell columns', required=False,
        min_value=1, max_value=settings.MAX_POINTS_PER_IMAGE,
        widget=NumberInput(attrs={'size': 3}),
    )

    # For stratified random
    stratified_points_per_cell = IntegerField(
        label='Points per cell', required=False,
        min_value=1, max_value=settings.MAX_POINTS_PER_IMAGE,
        widget=NumberInput(attrs={'size': 3}),
    )

    def __init__(self, *args, **kwargs):
        """
        If a Source is passed in as an argument, then get
        the point generation method of that Source,
        and use that to fill the form fields' initial values.
        """
        if 'source' in kwargs:
            source = kwargs.pop('source')
            kwargs['initial'] = PointGen.db_to_args_format(
                source.default_point_generation_method)

        self.form_help_text = \
            Source._meta.get_field('default_point_generation_method').help_text

        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        point_gen_type = cleaned_data.get('point_generation_type')
        if not point_gen_type:
            # Already have an error on the type, no need to clean further
            return

        point_gen_number_fields = {
            'simple_number_of_points', 'number_of_cell_rows',
            'number_of_cell_columns', 'stratified_points_per_cell'}

        # Depending on the point generation type that was picked, different
        # fields are going to be required or not. Identify the required fields
        # (other than the point-gen type).
        required_number_fields = set()
        if point_gen_type == PointGen.Types.SIMPLE:
            required_number_fields = {'simple_number_of_points'}
        elif point_gen_type == PointGen.Types.STRATIFIED:
            required_number_fields = {
                'number_of_cell_rows', 'number_of_cell_columns',
                'stratified_points_per_cell'}
        elif point_gen_type == PointGen.Types.UNIFORM:
            required_number_fields = {
                'number_of_cell_rows', 'number_of_cell_columns'}

        # Delete errors on the non-applicable fields. It would be
        # confusing if these errors counted, since the fields would be
        # invisible.
        non_applicable_fields = point_gen_number_fields - required_number_fields
        for field_name in non_applicable_fields:
            if field_name in self._errors:
                del self._errors[field_name]

        # Add 'required' errors to blank applicable fields.
        for field_name in required_number_fields:
            if field_name not in cleaned_data:
                # The field is non-blank with an invalid value.
                continue
            if cleaned_data[field_name] is None:
                # The field is blank.
                self.add_error(
                    field_name,
                    ValidationError("This field is required.", code='required'))

        if not self._errors:
            # No errors so far, so do a final check of
            # the total number of points specified.
            # It should be between 1 and settings.MAX_POINTS_PER_IMAGE.
            num_points = 0

            if point_gen_type == PointGen.Types.SIMPLE:
                num_points = cleaned_data['simple_number_of_points']
            elif point_gen_type == PointGen.Types.STRATIFIED:
                num_points = (
                    cleaned_data['number_of_cell_rows']
                    * cleaned_data['number_of_cell_columns']
                    * cleaned_data['stratified_points_per_cell'])
            elif point_gen_type == PointGen.Types.UNIFORM:
                num_points = (
                    cleaned_data['number_of_cell_rows']
                    * cleaned_data['number_of_cell_columns'])

            if num_points > settings.MAX_POINTS_PER_IMAGE:
                # Raise a non-field error (error applying to the form as a
                # whole).
                raise ValidationError(
                    "You specified {num_points} points total."
                    " Please make it no more than {max_points}.".format(
                        num_points=num_points,
                        max_points=settings.MAX_POINTS_PER_IMAGE))
