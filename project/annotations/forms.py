from decimal import Decimal
import json
from django.core.exceptions import ValidationError
from django import forms
from django.forms import Form
from django.forms.fields import BooleanField, CharField, DecimalField, IntegerField
from django.forms.models import ModelForm
from django.forms.widgets import TextInput, HiddenInput, NumberInput
from accounts.utils import is_robot_user
from annotations.model_utils import AnnotationAreaUtils
from annotations.models import Annotation, AnnotationToolSettings
from images.models import Metadata, Point
from labels.models import LocalLabel
from sources.models import Source


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


class AnnotationAreaPercentsForm(Form):

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
        decimal_places=3, widget=NumberInput(attrs={'step': 'any'}))
    max_x = DecimalField(
        label="Right boundary X", required=True,
        min_value=Decimal(0), max_value=Decimal(100), initial=Decimal(100),
        decimal_places=3, widget=NumberInput(attrs={'step': 'any'}))
    min_y = DecimalField(
        label="Top boundary Y", required=True,
        min_value=Decimal(0), max_value=Decimal(100), initial=Decimal(0),
        decimal_places=3, widget=NumberInput(attrs={'step': 'any'}))
    max_y = DecimalField(
        label="Bottom boundary Y", required=True,
        min_value=Decimal(0), max_value=Decimal(100), initial=Decimal(100),
        decimal_places=3, widget=NumberInput(attrs={'step': 'any'}))

    def __init__(self, *args, **kwargs):
        """
        If a Source is passed in as an argument, then get
        the annotation area of that Source,
        and use that to fill the form fields' initial values.
        """
        if 'source' in kwargs:
            source = kwargs.pop('source')

            if source.image_annotation_area:
                kwargs['initial'] = AnnotationAreaUtils.db_format_to_percentages(source.image_annotation_area)

        self.form_help_text = Source._meta.get_field('image_annotation_area').help_text

        super().__init__(*args, **kwargs)


    def clean(self):
        data = self.cleaned_data

        if 'min_x' in data and 'max_x' in data:

            if data['min_x'] >= data['max_x']:
                self.add_error('max_x', "The right boundary x must be greater than the left boundary x.")
                # Also mark min_x as being errored
                del data['min_x']

        if 'min_y' in data and 'max_y' in data:

            if data['min_y'] >= data['max_y']:
                self.add_error('max_y', "The bottom boundary y must be greater than the top boundary y.")
                # Also mark min_y as being errored
                del data['min_y']

        self.cleaned_data = data
        super().clean()


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
            d = AnnotationAreaUtils.db_format_to_numbers(image.metadata.annotation_area)
            annoarea_type = d.pop('type')
            if annoarea_type == AnnotationAreaUtils.TYPE_PERCENTAGES:
                kwargs['initial'] = AnnotationAreaUtils.percentages_to_pixels(width=image.original_width, height=image.original_height, **d)
            elif annoarea_type == AnnotationAreaUtils.TYPE_PIXELS:
                kwargs['initial'] = d
            elif annoarea_type == AnnotationAreaUtils.TYPE_IMPORTED:
                raise ValueError("Points were imported; annotation area should be un-editable.")

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
