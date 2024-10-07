from django import forms
from django.forms.fields import CharField
from django.forms.renderers import TemplatesSetting
from django.forms.widgets import MultiWidget


class GridFormRenderer(TemplatesSetting):
    """
    Based off of TemplatesSetting, for overriding built-in widget templates:
    https://docs.djangoproject.com/en/dev/ref/forms/renderers/#templatessetting
    """
    form_template_name = 'lib/forms/grid.html'


class RowsFormRenderer(TemplatesSetting):
    form_template_name = 'lib/forms/rows.html'


class BoxFormRenderer(TemplatesSetting):
    form_template_name = 'lib/forms/box.html'


class InlineFormRenderer(TemplatesSetting):
    form_template_name = 'lib/forms/inline.html'


class FieldsetsFormComponent:
    """
    Allows grouping form fields into fieldsets, which can be recognized
    in renderer templates for visually grouping related fields.

    To use this class, inherit from this class first, then either
    Form or ModelForm.
    This isn't a standalone parent class, yet it's arguably not a mixin
    either because it overrides the get_context() method. So we wanted a
    different label for this, and came up with 'component'.
    """
    fieldsets: list[dict] = []
    fieldsets_keys: list[str] | list[list[str]] = []

    def get_context(self):
        """
        Context for the form-renderer template.
        """
        context = super().get_context()

        if self.fieldsets:
            pass
        elif self.fieldsets_keys:
            # fieldsets_keys is shorthand for fieldsets.
            self.fieldsets = []
            for fieldset in self.fieldsets_keys:
                if isinstance(fieldset[0], list):
                    self.fieldsets.append(dict(
                        subfieldsets=[
                            dict(fields=subfieldset)
                            for subfieldset in fieldset
                        ],
                    ))
                else:
                    self.fieldsets.append(dict(
                        fields=fieldset,
                    ))
        else:
            raise ValueError(
                "Any form using FieldsetsFormComponent must define fieldsets"
                " or fieldsets_keys.")

        field_dict = {
            field.name: (field, errors)
            for (field, errors) in context['fields']
        }

        # Construct the fieldsets. Up to two levels of nesting are
        # supported.
        # Note that we make no assumptions about which of the
        # specified field keys are actually present in the form,
        # since the form may conditionally omit some fields.

        fieldsets = []

        for fieldset in self.fieldsets:

            if 'fields' in fieldset:
                # Replace field names with actual fields and their errors.
                fields = [
                    field_dict[field_name]
                    for field_name in fieldset['fields']
                    if field_name in field_dict
                ]

                if fields:
                    fieldsets.append(fieldset | dict(fields=fields))
                # Else, fieldset has nothing in it, so we don't add it.

            elif 'subfieldsets' in fieldset:
                subfieldsets = []
                for subfieldset in fieldset['subfieldsets']:
                    subfields = [
                        field_dict[field_name]
                        for field_name in subfieldset['fields']
                        if field_name in field_dict
                    ]
                    if subfields:
                        subfieldsets.append(
                            subfieldset | dict(fields=subfields))

                if subfieldsets:
                    fieldsets.append(
                        fieldset | dict(subfieldsets=subfieldsets))
                # Else, fieldset has nothing in it, so we don't add it.

            else:
                raise ValueError(
                    "Each fieldset should specify either fields or"
                    " subfieldsets.")

        context['fieldsets'] = fieldsets
        return context


class EnhancedMultiWidget(MultiWidget):

    # Flag to use subfields' labels instead of the overall field's label
    use_subfield_labels = False

    # Define how field values control the visibility of the other fields.
    visibility_specs = dict()

    def __init__(self, field, attrs=None):
        # It's useful to reference the field associated with this widget.
        self.field = field

        widgets = [
            getattr(self.field, field_name).widget
            for field_name in self.field.field_order]
        super().__init__(widgets, attrs)

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)

        names_to_html_names = dict()
        for index, subwidget in enumerate(context['widget']['subwidgets']):
            subfield_name = self.field.field_order[index]
            names_to_html_names[subfield_name] = subwidget['name']

        # Add to the subwidgets template context to assist rendering.
        for index, subwidget in enumerate(context['widget']['subwidgets']):
            subfield = self.field.fields[index]
            subfield_name = self.field.field_order[index]

            subwidget['label'] = subfield.label
            subwidget['input_type'] = subfield.widget.input_type

            if subfield_name in self.visibility_specs:
                control_field_name, activating_values = \
                    self.visibility_specs[subfield_name]

                subwidget['attrs'] |= {
                    'data-visibility-control-field':
                        names_to_html_names[control_field_name],
                    'data-visibility-activating-values':
                        ' '.join(activating_values),
                }

        return context


class DummyForm(forms.Form):
    """
    Dummy form that can be used for Javascript tests
    in place of any other form, to keep those tests simple.
    """
    def __init__(self, **field_values):
        super().__init__()

        if not field_values:
            field_values['field1'] = 'value1'
        for field_name, field_value in field_values.items():
            self.fields[field_name] = CharField(
                required=False, initial=field_value)


def get_one_form_error(form, include_field_name=True):
    """
    Use this if form validation failed and you just want to get the string for
    one error.
    """
    for field_name, error_messages in form.errors.items():
        if error_messages:
            if not include_field_name:
                # Requested not to include the field name in the message
                return error_messages[0]
            elif field_name == '__all__':
                # Non-field error
                return error_messages[0]
            else:
                # Include the field name
                return "{field}: {error}".format(
                    field=form[field_name].label,
                    error=error_messages[0])

    # This function was called under the assumption that there was a
    # form error, but if we got here, then we couldn't find that form error.
    return (
        "Unknown error. If the problem persists, please let us know on the"
        " forum.")


def get_one_formset_error(formset, get_form_name, include_field_name=True):
    for form in formset:
        error_message = get_one_form_error(form, include_field_name)

        if not error_message.startswith("Unknown error"):
            # Found an error in this form
            return "{form}: {error}".format(
                form=get_form_name(form),
                error=error_message)

    for error_message in formset.non_form_errors():
        return error_message

    return (
        "Unknown error. If the problem persists, please let us know on the"
        " forum.")
