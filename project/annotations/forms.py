from decimal import Decimal
import json

from django.core.exceptions import ValidationError
from django import forms
from django.forms import Form
from django.forms.fields import (
    BooleanField, CharField, DecimalField, IntegerField, MultiValueField)
from django.forms.models import ModelForm
from django.forms.widgets import HiddenInput, NumberInput, TextInput

from accounts.utils import is_robot_user
from images.models import Metadata, Point
from labels.models import LocalLabel
from lib.forms import EnhancedMultiWidget
from .model_utils import AnnotationArea
from .models import Annotation, AnnotationToolSettings


class AnnotationForm(forms.Form):

    def __init__(self, *args, **kwargs):
        image = kwargs.pop('image')
        show_machine_annotations = kwargs.pop('show_machine_annotations')
        super().__init__(*args, **kwargs)

        labelFieldMaxLength = LocalLabel._meta.get_field('code').max_length

        for point in Point.objects.filter(image=image).order_by('point_number'):

            try:
                annotation = point.annotation
            except Annotation.DoesNotExist:
                # This point doesn't have an annotation
                existingAnnoCode = ''
                isRobotAnnotation = None
            else:
                # This point has an annotation
                existingAnnoCode = annotation.label_code
                isRobotAnnotation = is_robot_user(annotation.user)

                if isRobotAnnotation and not show_machine_annotations:
                    # Is machine annotation and we're not including those
                    existingAnnoCode = ''
                    isRobotAnnotation = None

            pointNum = point.point_number

            # Create the text field for annotating a point with a label code.
            # label_1 for point 1, label_23 for point 23, etc.
            labelFieldName = 'label_' + str(pointNum)

            self.fields[labelFieldName] = CharField(
                widget=TextInput(attrs=dict(
                    size=6,
                    readonly='',
                )),
                max_length=labelFieldMaxLength,
                label=str(pointNum),
                required=False,
                initial=existingAnnoCode,
            )

            # Create a hidden field to indicate whether a point is robot-annotated or not.
            # robot_1 for point 1, robot_23 for point 23, etc.
            robotFieldName = 'robot_' + str(pointNum)

            self.fields[robotFieldName] = BooleanField(
                widget=HiddenInput(),
                required=False,
                initial=json.dumps(isRobotAnnotation),
            )


class AnnotationToolSettingsForm(ModelForm):

    class Meta:
        model = AnnotationToolSettings
        fields = [
            'point_marker', 'point_marker_size', 'point_marker_is_scaled',
            'point_number_size', 'point_number_is_scaled',
            'unannotated_point_color', 'robot_annotated_point_color',
            'human_annotated_point_color', 'selected_point_color',
            'show_machine_annotations',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Make text fields have the appropriate size.
        #
        # TODO: This should really be sized with CSS:
        # https://developer.mozilla.org/en-US/docs/Web/HTML/Element/input/number#Using_number_inputs
        # But it so happens that Firefox still accepts this size attr.
        # And other browsers (Chromium-based) already size the field reasonably
        # based on min and max values.
        self.fields['point_marker_size'].widget.attrs.update({'size': 4})
        self.fields['point_number_size'].widget.attrs.update({'size': 4})

        # Make the color fields have class="jscolor" so they use jscolor.
        color_fields = [self.fields[name] for name in
                        ['unannotated_point_color',
                         'robot_annotated_point_color',
                         'human_annotated_point_color',
                         'selected_point_color',]
                       ]
        for field in color_fields:
            field.widget.attrs.update({'class': 'jscolor'})


class AnnotationImageOptionsForm(Form):
    brightness = IntegerField(initial=0, min_value=-100, max_value=100)
    contrast = IntegerField(initial=0, min_value=-100, max_value=100)


class AnnotationAreaPercentsWidget(EnhancedMultiWidget):

    template_name = 'annotations/annotation_area_percents_field.html'

    def decompress(self, value):
        if value is None:
            return [None for _ in self.field.field_order]

        area_spec = AnnotationArea.from_db_value(value)
        return [
            getattr(area_spec, field_name)
            for field_name in self.field.field_order
        ]


error_messages = {
    'min_value': "Each value must be between 0 and 100.",
    'max_value': "Each value must be between 0 and 100.",
    'max_decimal_places': "Up to %(max)s decimal places are allowed.",
}


class AnnotationAreaPercentsField(MultiValueField):
    # To be filled in by __init__()
    widget = None

    # decimal_places=3 defines the max decimal places for the server-side form.
    # But for the client-side experience, we define step='any' for two reasons:
    # (1) So the NumberInput's up/down arrows change the value by 1 instead of
    # 0.001 at a time.
    # (2) So the browser doesn't do client-side form refusal based on
    # decimal place count, which at least in Firefox is confusing
    # because it doesn't display an error message.
    min_x = DecimalField(
        label="Left boundary X", required=True,
        min_value=Decimal(0), max_value=Decimal(100), initial=Decimal(0),
        decimal_places=3, error_messages=error_messages)
    max_x = DecimalField(
        label="Right boundary X", required=True,
        min_value=Decimal(0), max_value=Decimal(100), initial=Decimal(100),
        decimal_places=3, error_messages=error_messages)
    min_y = DecimalField(
        label="Top boundary Y", required=True,
        min_value=Decimal(0), max_value=Decimal(100), initial=Decimal(0),
        decimal_places=3, error_messages=error_messages)
    max_y = DecimalField(
        label="Bottom boundary Y", required=True,
        min_value=Decimal(0), max_value=Decimal(100), initial=Decimal(100),
        decimal_places=3, error_messages=error_messages)

    field_order = AnnotationArea.number_field_order

    def __init__(self, **kwargs):
        self.widget = AnnotationAreaPercentsWidget(field=self)

        self.min_x.widget.attrs |= {'step': 'any', 'size': 3}
        self.max_x.widget.attrs |= {'step': 'any', 'size': 3}
        self.min_y.widget.attrs |= {'step': 'any', 'size': 3}
        self.max_y.widget.attrs |= {'step': 'any', 'size': 3}

        # Some kwargs from the model field (which would be passed in by a
        # ModelForm) can't be applied directly to MultiValueField.
        kwargs.pop('max_length')
        # TODO: Might not need this line if image_annotation_area model field
        #  becomes non-null, which it seems it should.
        kwargs.pop('empty_value')

        super().__init__(
            fields=[
                getattr(self, field_name) for field_name in self.field_order],
            require_all_fields=True,
            error_messages = {
                'required': "All of these fields are required.",
            },
            **kwargs)

    def compress(self, data_list):
        # For DateFilterField, data_list was empty sometimes. Not sure if that
        # also applies to this field, but here's a case to handle it.
        if not data_list:
            return dict()

        values_dict = dict(zip(self.field_order, data_list))
        area = AnnotationArea(
            type=AnnotationArea.TYPE_PERCENTAGES, **values_dict)

        if area.min_x >= area.max_x:
            raise ValidationError(
                "The right boundary x must be greater than"
                " the left boundary x.",
                code='require_positive_width')

        if area.min_y >= area.max_y:
            raise ValidationError(
                "The bottom boundary y must be greater than"
                " the top boundary y.",
                code='require_positive_height')

        return area.db_value


class AnnotationAreaPixelsForm(Form):

    class Media:
        js = ("js/AnnotationAreaEditHelper.js",)
        css = {
            'all': ("css/annotation_area_edit.css",)
        }

    # The complete field definitions are in __init__(), because
    # max_value needs to be set dynamically.
    # (We *could* just append the max-value validators dynamically, except
    # that results in some really weird behavior where the error list grows
    # with duplicate errors every time you press submit.)
    min_x = IntegerField()
    max_x = IntegerField()
    min_y = IntegerField()
    max_y = IntegerField()

    def __init__(self, *args, **kwargs):

        image = kwargs.pop('image')

        if image.metadata.annotation_area:
            area = AnnotationArea.from_db_value(image.metadata.annotation_area)
            area = AnnotationArea.to_pixels(
                area, width=image.original_width, height=image.original_height)
            kwargs['initial'] = dict(
                min_x=area.min_x,
                max_x=area.max_x,
                min_y=area.min_y,
                max_y=area.max_y,
            )

        super().__init__(*args, **kwargs)

        self.fields['min_x'] = IntegerField(
            label="Left boundary X", required=False,
            min_value=0, max_value=image.max_column,
            widget=NumberInput(attrs={'size': 5})
        )
        self.fields['max_x'] = IntegerField(
            label="Right boundary X", required=False,
            min_value=0, max_value=image.max_column,
            widget=NumberInput(attrs={'size': 5})
        )
        self.fields['min_y'] = IntegerField(
            label="Top boundary Y", required=False,
            min_value=0, max_value=image.max_row,
            widget=NumberInput(attrs={'size': 5})
        )
        self.fields['max_y'] = IntegerField(
            label="Bottom boundary Y", required=False,
            min_value=0, max_value=image.max_row,
            widget=NumberInput(attrs={'size': 5})
        )

        self.form_help_text = Metadata._meta.get_field('annotation_area').help_text

    def clean(self):
        data = self.cleaned_data

        field_keys = ['min_x', 'max_x', 'min_y', 'max_y']
        no_errors_yet = all([key in data for key in field_keys])

        if no_errors_yet:
            has_empty_fields = any([data[key] is None for key in field_keys])
            all_empty_fields = all([data[key] is None for key in field_keys])

            if has_empty_fields and not all_empty_fields:
                raise ValidationError("You must fill in all four of the annotation area fields.")

        if 'min_x' in data and 'max_x' in data:

            if data['min_x'] > data['max_x']:
                self.add_error('max_x', "The right boundary x must be greater than or equal to the left boundary x.")
                del data['min_x']
                del data['max_x']

        if 'min_y' in data and 'max_y' in data:

            if data['min_y'] > data['max_y']:
                self.add_error('max_y', "The bottom boundary y must be greater than or equal to the top boundary y.")
                del data['min_y']
                del data['max_y']

        self.cleaned_data = data
        super().clean()
