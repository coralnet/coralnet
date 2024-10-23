from collections import OrderedDict

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage
from django.core.validators import validate_comma_separated_integer_list
from django.forms import Form
from django.forms.fields import BooleanField, CharField, IntegerField
from django.forms.models import ModelChoiceField, ModelForm, BaseModelFormSet
from django.forms.widgets import TextInput, HiddenInput
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.html import escape
from django.utils.safestring import mark_safe

from annotations.utils import label_ids_with_confirmed_annotations_in_source
from lib.exceptions import FileProcessError
from lib.forms import (
    BoxFormRenderer, FieldsetsFormComponent, get_one_form_error)
from upload.utils import csv_to_dicts
from .models import Label, LabelGroup, LabelSet, LocalLabel
from .utils import label_popularity, search_labels_by_text


def labels_csv_process(csv_stream, source):
    csv_data = csv_to_dicts(
        csv_stream=csv_stream,
        required_columns=dict(
            global_pk_str="Label ID",
            code="Short code",
        ),
        optional_columns=dict(),
        unique_keys=['global_pk_str'],
    )

    local_labels = OrderedDict()

    if source.labelset:
        # Fill local_labels with the currently existing labels.
        for local_label in source.labelset.get_labels():
            local_labels[local_label.global_label.pk] = local_label

    for label_d in csv_data:
        try:
            global_pk = int(label_d['global_pk_str'])
            Label.objects.get(pk=global_pk)
        except (ValueError, Label.DoesNotExist):
            raise FileProcessError(
                f"CSV has non-existent label id: {label_d['global_pk_str']}")

        if global_pk in local_labels:
            # Exists in labelset; we'll use the same local label object
            # but update the fields
            form = LocalLabelForm(label_d, instance=local_labels[global_pk])
        else:
            # New to labelset
            form = LocalLabelForm(label_d)

        if not form.is_valid():
            raise FileProcessError("Row with id {pk} - {error}".format(
                pk=global_pk, error=get_one_form_error(form)))

        # Replace existing local_labels entries with new ones.
        # This gets us the set of local labels we'd have if we decided to
        # save the user's input.
        local_labels[global_pk] = form.instance
        # The form doesn't have the global label info, so set that.
        local_labels[global_pk].global_label_id = global_pk

    # Dict -> flat iterable.
    local_labels = list(local_labels.values())

    try:
        detect_dupe_label_codes(local_labels)
    except ValidationError as e:
        raise FileProcessError(e.message)

    # Remember to set the local labels' labelset fields later.
    # Other than that, they should be ready for saving.
    return local_labels


def detect_dupe_label_codes(local_labels):
    codes = [local_label.code.lower() for local_label in local_labels]
    dupe_codes = [
        code for code in codes
        if codes.count(code) > 1
    ]

    if not dupe_codes:
        return

    raise ValidationError(
        "The resulting labelset would have multiple labels with the code"
        " '{code}' (non case sensitive). This is not allowed.".format(
            code=dupe_codes[0]),
        # The following is a validation-error code used by
        # Django for error IDing, not a label code!
        code='dupe_code',
    )


class LabelForm(ModelForm):
    class Meta:
        model = Label
        fields = ['name', 'default_code', 'group', 'description', 'thumbnail']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields['default_code'].widget.attrs['size'] = \
            Label._meta.get_field('default_code').max_length

    def clean_name(self):
        """
        Add an error if the specified name matches that of an existing label.

        Two reasons why we check here instead of specifying uniqueness on the
        model field level:
        (1) Specifying case insensitive uniqueness on that level is a pain.
        http://stackoverflow.com/questions/7773341/
        (2) On that level, the error message would only be minimally
        customizable; it would not be simple to link to the conflicting label.
        """
        name = self.cleaned_data['name']

        if self.instance.name.lower() == name.lower():
            # We're editing an existing label and the name is unchanged
            # (case insensitively); no error.
            # We check this before checking for uniqueness,
            # because the uniqueness check would include a comparison of
            # this label versus itself, which would yield a false positive.
            return name
        try:
            # Case-insensitive uniqueness check
            conflicting_label = Label.objects.get(name__iexact=name)
        except Label.DoesNotExist:
            # Name is not taken; no error
            return name

        # Name is taken; raise error
        # Use mark_safe() to ensure the HTML a tag is not escaped
        msg = mark_safe(
            'There is already a label with the same name:'
            ' <a href="{url}" target="_blank">'
            '{conflicting_name}</a>'.format(
                url=reverse('label_main', args=[conflicting_label.pk]),
                # Label names are in general user defined, so use
                # escape to prevent XSS
                conflicting_name=escape(conflicting_label.name),
            ))
        raise ValidationError(msg, code='unique')

    def clean_default_code(self):
        """
        Add an error if the specified default code matches that
        of an existing label.
        Similar to checking for name conflicts.
        """
        default_code = self.cleaned_data['default_code']

        if self.instance.default_code.lower() == default_code.lower():
            return default_code
        try:
            conflicting_label = Label.objects.get(
                default_code__iexact=default_code)
        except Label.DoesNotExist:
            return default_code

        msg = mark_safe(
            'There is already a label with the same default code:'
            ' <a href="{url}" target="_blank">'
            '{conflicting_code}</a>'.format(
                url=reverse('label_main', args=[conflicting_label.pk]),
                conflicting_code=escape(conflicting_label.default_code),
            ))
        raise ValidationError(msg, code='unique')

    @staticmethod
    def send_label_creation_email(request, new_label):
        """Email the committee about the label creation, and CC the creator."""
        context = dict(label=new_label)

        subject = render_to_string(
            'labels/label_created_subject.txt', context)
        # Force subject to a single line to avoid header-injection issues.
        subject = ''.join(subject.splitlines())
        message = render_to_string(
            'labels/label_created_email.txt', context, request=request)

        label_creation_email = EmailMessage(
            subject=subject,
            body=message,
            to=[settings.LABELSET_COMMITTEE_EMAIL],
            cc=[request.user.email],
        )
        label_creation_email.send()

    def save_new_label(self, request):
        label = self.instance
        label.created_by = request.user
        label.save()

        self.send_label_creation_email(request, label)

        return label


class LabelFormForCurators(LabelForm):
    class Meta:
        model = Label
        fields = [
            'name', 'default_code', 'group', 'description', 'thumbnail',
            'verified', 'duplicate'
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Order the 'is duplicate of' candidate labels alphabetically
        # by label name.
        # There's a model-level alternative of specifying Meta.ordering in the
        # model class, but that would mean all usages of Labels become
        # name-ordered by default, which we might not want.
        self.fields['duplicate'].queryset = \
            self.fields['duplicate'].queryset.order_by('name')


class LabelSearchForm(FieldsetsFormComponent, Form):

    name_search = CharField(
        label="Search by name",
        max_length=Label._meta.get_field('name').max_length,
        required=False)

    show_verified = BooleanField(
        label="Verified", initial=True, required=False)
    show_regular = BooleanField(
        label="Regular", initial=True, required=False)
    show_duplicate = BooleanField(
        label="Duplicate", initial=False, required=False)

    functional_group = ModelChoiceField(
        queryset=LabelGroup.objects.all(),
        empty_label="All",
        required=False)

    min_popularity = IntegerField(
        label="Minimum popularity (0-100)",
        required=False,
        min_value=0, max_value=100)

    default_renderer = BoxFormRenderer
    fieldsets_keys = [[
        ['name_search', 'show_verified', 'show_regular', 'show_duplicate'],
        ['functional_group', 'min_popularity'],
    ]]

    def get_labels(self):
        """
        After validating the form, call this method to get the labels
        corresponding to the search parameters.
        Returns an ITERABLE of Labels, not necessarily a queryset (because
        the popularity filter can't be implemented on the database side).
        """
        if self.cleaned_data['name_search']:
            labels = search_labels_by_text(self.cleaned_data['name_search'])
        else:
            labels = Label.objects.all()

        if not self.cleaned_data['show_verified']:
            labels = labels.exclude(verified=True)
        if not self.cleaned_data['show_regular']:
            labels = labels.exclude(verified=False, duplicate__isnull=True)
        if not self.cleaned_data['show_duplicate']:
            labels = labels.exclude(duplicate__isnull=False)

        if self.cleaned_data['functional_group']:
            labels = labels.filter(group=self.cleaned_data['functional_group'])

        if self.cleaned_data['min_popularity']:
            min_popularity = int(self.cleaned_data['min_popularity'])
            # Popularity isn't a database field, so we'll have to convert to a
            # list here.
            labels = [
                label for label in labels
                if label_popularity(label.pk) >= min_popularity]

        return labels


class LabelSetForm(Form):
    label_ids = CharField(
        validators=[validate_comma_separated_integer_list],
        required=True,
        widget=HiddenInput(),
        error_messages=dict(required="You must select one or more labels."),
    )

    def __init__(self, *args, **kwargs):
        self.source = kwargs.pop('source')
        super().__init__(*args, **kwargs)

        if not self.is_bound:
            if self.source.labelset:
                # Initialize with the source labelset's label ids
                global_ids = self.source.labelset.get_globals() \
                    .values_list('pk', flat=True)
                self.initial['label_ids'] = ','.join(
                    str(pk) for pk in global_ids)

        self.global_ids_to_delete = None
        self.locals_to_add = None

    def clean_label_ids(self):
        # Run through a set to remove dupes, then get a list again
        label_id_list = list(set(
            int(pk) for pk in self.cleaned_data['label_ids'].split(',')))

        # Check if labels of these ids exist
        for label_id in label_id_list:
            try:
                Label.objects.get(pk=label_id)
            except Label.DoesNotExist:
                msg = (
                    "Could not find labels of id: {bad_id}."
                    " Either we messed up, or one of the"
                    " labels you selected just got deleted."
                    " If the problem persists,"
                    " please let us know on the forum.").format(
                        bad_id=label_id,
                    )
                raise ValidationError(msg, code='bad_label_id')

        # Check if any in-use labels are marked for removal
        label_ids_in_confirmed_annotations = \
            label_ids_with_confirmed_annotations_in_source(self.source)
        for label_id in label_ids_in_confirmed_annotations:
            if label_id not in label_id_list:
                label = Label.objects.get(pk=label_id)
                msg = (
                    "The label '{name}' is marked for removal from the"
                    " labelset, but we can't remove it because the source"
                    " still has confirmed annotations with this label."
                    " Either we messed up, or some annotations have"
                    " changed since you reached this page."
                    " If the problem persists,"
                    " please let us know on the forum.").format(
                        name=label.name,
                    )
                raise ValidationError(msg, code='deleting_in_use_label')

        # Return the integer list (rather than its string repr).
        return label_id_list

    def clean(self):
        """
        Detect label code conflicts in the labelset.

        Also, for convenience, set some info about the label changes
        since we have to figure it out here anyway.
        """
        if any(self.errors):
            # Don't bother with these checks unless the other fields
            # are valid so far.
            return

        pending_global_ids = set(self.cleaned_data['label_ids'])

        if self.source.labelset:
            # Editing a labelset
            existing_locals = self.source.labelset.get_labels()
        else:
            # Creating a labelset
            existing_locals = LocalLabel.objects.none()

        existing_global_ids = set(
            existing_locals.values_list('global_label_id', flat=True))
        self.global_ids_to_delete = existing_global_ids - pending_global_ids
        global_ids_to_add = pending_global_ids - existing_global_ids
        global_ids_to_keep = existing_global_ids - self.global_ids_to_delete

        self.locals_to_add = []

        for global_id in global_ids_to_add:
            local_label = LocalLabel(
                global_label_id=global_id,
                code=Label.objects.get(pk=global_id).default_code
            )
            self.locals_to_add.append(local_label)

        locals_to_keep = existing_locals.filter(
            global_label_id__in=global_ids_to_keep)
        detect_dupe_label_codes(locals_to_keep)

    def save_labelset(self):
        """
        Call this after validation to save the labelset.
        """
        labelset_was_created = False

        if not self.source.labelset:
            labelset = LabelSet()
            labelset.save()
            self.source.labelset = labelset
            self.source.save()
            labelset_was_created = True

        labelset = self.source.labelset

        local_labels_to_delete = labelset.get_labels() \
            .filter(global_label__pk__in=self.global_ids_to_delete)
        local_labels_to_delete.delete()

        for local_label in self.locals_to_add:
            local_label.labelset = labelset
        LocalLabel.objects.bulk_create(self.locals_to_add)

        return labelset_was_created


class LocalLabelForm(ModelForm):
    class Meta:
        model = LocalLabel
        fields = ['code']
        widgets = {
            'code': TextInput(attrs={'size': 10}),
        }


class BaseLocalLabelFormSet(BaseModelFormSet):
    def clean(self):
        """
        Checks that no two labels in the formset have the same short code
        (case-insensitive).
        """
        if any(self.errors):
            # Don't bother validating the formset
            # unless each form is valid on its own
            return

        pending_local_labels = [form.instance for form in self.forms]
        detect_dupe_label_codes(pending_local_labels)
