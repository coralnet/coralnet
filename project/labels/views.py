from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import serializers
from django.core.paginator import Paginator, EmptyPage, InvalidPage
from django.db.models import Count, F
from django.forms import modelformset_factory
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import render, get_object_or_404
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_POST, require_GET

from annotations.models import Annotation
from annotations.utils import label_ids_with_confirmed_annotations_in_source
from calcification.utils import get_default_calcify_tables
from jobs.utils import schedule_job
from lib.decorators import (
    login_required_ajax, source_permission_required,
    source_visibility_required, source_labelset_required)
from lib.exceptions import FileProcessError
from lib.forms import get_one_formset_error, get_one_form_error
from sources.models import Source
from sources.utils import filter_out_test_sources
from upload.forms import CSVImportForm
from visualization.utils import generate_patch_if_doesnt_exist, get_patch_url
from .decorators import label_edit_permission_required
from .forms import (
    LabelForm, LabelSearchForm, LabelSetForm, LocalLabelForm,
    BaseLocalLabelFormSet, labels_csv_process, LabelFormForCurators)
from .models import cacheable_label_details, Label, LocalLabel, LabelSet
from .utils import search_labels_by_text, is_label_editable_by_user


@login_required
def duplicates_overview(request):
    """
    Renders the view for the duplicates overview.
    """

    dups = Label.objects.exclude(duplicate=None)
    return render(request, 'labels/list_duplicates.html', {
        'labels': dups,
        'stats': {
            'ann_count': sum([dup.ann_count for dup in dups]),
            'dup_count': len(dups),
        }
    })

@login_required
def label_new(request):
    """
    Create a new global label.
    """
    if request.method == 'POST':
        form = LabelForm(request.POST, request.FILES)

        if form.is_valid():
            form.save_new_label(request)
            messages.success(request, 'Label successfully created.')
            return HttpResponseRedirect(
                reverse('label_main', args=[form.instance.pk]))
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = LabelForm()

    return render(request, 'labels/label_new.html', {
        'form': form,
    })


@login_required_ajax
@require_POST
def label_new_ajax(request):
    """
    Create a new global label (through Ajax).
    """
    form = LabelForm(request.POST, request.FILES)

    if form.is_valid():
        label = form.save_new_label(request)
        return render(request, 'labels/label_box_container.html', {
            'labels': [label],
        })

    # Not valid. Find the first error and return it.
    return JsonResponse(dict(error=get_one_form_error(form)))


@label_edit_permission_required('label_id')
def label_edit(request, label_id):
    """
    Edit a global label.
    """
    label = get_object_or_404(Label, id=label_id)

    if request.user.has_perm('labels.verify_label'):
        FormClass = LabelFormForCurators
    else:
        FormClass = LabelForm

    if request.method == 'POST':

        # Cancel
        cancel = request.POST.get('cancel', None)
        if cancel:
            messages.success(request, 'Edit cancelled.')
            return HttpResponseRedirect(reverse('label_main', args=[label_id]))

        # Submit
        form = FormClass(request.POST, request.FILES, instance=label)

        if form.is_valid():
            form.save()
            messages.success(request, 'Label successfully edited.')
            return HttpResponseRedirect(reverse('label_main', args=[label_id]))
        else:
            messages.error(request, 'Please correct the errors below.')

    else:
        # Just reached the page
        form = FormClass(instance=label)

    return render(request, 'labels/label_edit.html', {
        'label': label,
        'form': form,
    })


@source_permission_required('source_id', perm=Source.PermTypes.ADMIN.code)
def labelset_add(request, source_id):
    """
    Add or remove label entries from a labelset
    (or pick entries for a new labelset).
    """
    source = get_object_or_404(Source, id=source_id)

    if not source.trains_own_classifiers and source.deployed_classifier:
        return render(request, 'lib/function_unavailable.html', {
            'message': "Since this source relies on a specific classifier,"
                       " the labelset can't be edited.",
        })

    if request.method == 'POST':

        # Cancel (available for edit only)
        cancel = request.POST.get('cancel', None)
        if cancel:
            messages.success(request, 'Edit cancelled.')
            return HttpResponseRedirect(
                reverse('labelset_main', args=[source_id]))

        # Submit
        labelset_form = LabelSetForm(request.POST, source=source)

        if labelset_form.is_valid():
            labelset_was_created = labelset_form.save_labelset()

            if labelset_was_created:
                messages.success(request, "Labelset successfully created.")
            else:
                messages.success(request, "Labelset successfully changed.")

                # Reset classifiers.
                schedule_job(
                    'reset_classifiers_for_source', source_id,
                    source_id=source_id)

            return HttpResponseRedirect(
                reverse('labelset_main', args=[source.id]))
        else:
            messages.error(request, get_one_form_error(
                labelset_form, include_field_name=False))

    else:
        labelset_form = LabelSetForm(source=source)

    initial_label_ids_str = labelset_form['label_ids'].value()
    if initial_label_ids_str in ['', None]:
        initial_label_ids = []
    else:
        initial_label_ids = initial_label_ids_str.split(',')
    initial_labels = Label.objects.filter(pk__in=initial_label_ids)

    label_ids_in_confirmed_annotations = \
        label_ids_with_confirmed_annotations_in_source(source)

    return render(request, 'labels/labelset_add.html', {
        'source': source,
        'labelset_form': labelset_form,
        'initial_labels': initial_labels,
        'label_ids_in_confirmed_annotations':
            label_ids_in_confirmed_annotations,
        'has_classifier': source.classifier_set.exists(),

        # Include a new-label form on the page. It'll be submitted to
        # another view though.
        'new_label_form': LabelForm(),
        'labelset_committee_email': settings.LABELSET_COMMITTEE_EMAIL,
    })


@login_required
@require_GET
def labelset_add_search_ajax(request):
    """
    Use a text search value to get a set of global labels.
    Return general info for those global labels.
    """
    search_value = request.GET.get('search')

    labels = search_labels_by_text(search_value)

    # Sort by: verified over non-verified, then by highest popularity.
    def sort_key(label):
        key_1 = 1 if label.verified else 0
        key_2 = label.popularity
        return key_1, key_2
    limit = 50
    labels = sorted(labels, key=sort_key, reverse=True)[:limit]

    return render(request, 'labels/label_box_container.html', {
        'labels': labels,
    })


@source_permission_required('source_id', perm=Source.PermTypes.ADMIN.code)
@source_labelset_required('source_id', message=(
    "This source doesn't have a labelset yet."))
def labelset_edit(request, source_id):
    """
    Edit entries of a labelset: label code, custom groups, etc.
    """
    source = get_object_or_404(Source, id=source_id)

    LocalLabelFormSet = modelformset_factory(
        LocalLabel, form=LocalLabelForm,
        formset=BaseLocalLabelFormSet, extra=0)

    if request.POST:
        # Cancel
        cancel = request.POST.get('cancel', None)
        if cancel:
            messages.success(request, 'Edit cancelled.')
            return HttpResponseRedirect(
                reverse('labelset_main', args=[source_id]))

        # Submit
        formset = LocalLabelFormSet(
            request.POST,
            # Only accept LocalLabel IDs from this source, as a security check.
            queryset=source.labelset.get_labels())

        if formset.is_valid():
            formset.save()

            messages.success(request, "Label entries successfully edited.")
            return HttpResponseRedirect(
                reverse('labelset_main', args=[source.id]))
        else:
            def get_form_name(f):
                # Defensive coding. Submitting a nonexistent LocalLabel ID
                # (e.g. via Inspect Element) gets a null global_label here.
                try:
                    return f.instance.global_label.name
                except Label.DoesNotExist:
                    return "(No name)"
            messages.error(
                request, get_one_formset_error(formset, get_form_name))
    else:
        formset = LocalLabelFormSet(
            queryset=source.labelset.get_locals_ordered_by_group_and_code())

    return render(request, 'labels/labelset_edit.html', {
        'source': source,
        'formset': formset,
    })


@source_permission_required('source_id', perm=Source.PermTypes.ADMIN.code)
def labelset_import(request, source_id):
    source = get_object_or_404(Source, id=source_id)

    csv_import_form = CSVImportForm()

    return render(request, 'labels/labelset_import.html', {
        'source': source,
        'csv_import_form': csv_import_form,
    })


@require_POST
@source_permission_required(
    'source_id', perm=Source.PermTypes.ADMIN.code, ajax=True)
def labelset_import_preview_ajax(request, source_id):
    source = get_object_or_404(Source, id=source_id)

    csv_import_form = CSVImportForm(request.POST, request.FILES)
    if not csv_import_form.is_valid():
        error_message = get_one_form_error(
            csv_import_form, include_field_name=False)
        error_html = '<br>'.join(error_message.splitlines())
        return JsonResponse(dict(error=error_html))

    try:
        csv_labels = labels_csv_process(
            csv_import_form.get_csv_stream(), source)
    except FileProcessError as error:
        error_html = '<br>'.join(str(error).splitlines())
        return JsonResponse(dict(error=error_html))

    csv_labels.sort(key=lambda x: x.code)
    request.session['csv_labels'] = serializers.serialize('json', csv_labels)

    return JsonResponse(dict(
        success=True,
        previewTable=render_to_string(
            'labels/labelset_import_preview_table.html', {
                'labels': csv_labels,
            }
        ),
        previewDetail="",
    ))


@require_POST
@source_permission_required(
    'source_id', perm=Source.PermTypes.ADMIN.code, ajax=True)
def labelset_import_ajax(request, source_id):
    source = get_object_or_404(Source, id=source_id)

    serialized_labels = request.session.pop('csv_labels', None)
    if not serialized_labels:
        return JsonResponse(dict(
            error=(
                "We couldn't find the expected data in your session."
                " Please try loading this page again. If the problem persists,"
                " let us know on the forum."
            ),
        ))
    csv_labels = serializers.deserialize('json', serialized_labels)

    if not source.labelset:
        labelset = LabelSet()
        labelset.save()
        source.labelset = labelset
        source.save()

    labels_to_add = []
    for deserialized_object in csv_labels:
        label = deserialized_object.object
        if label.pk:
            # Updating an existing local label
            label.save()
        else:
            # Adding a new local label
            label.labelset = source.labelset
            labels_to_add.append(label)
    LocalLabel.objects.bulk_create(labels_to_add)

    return JsonResponse(dict(
        success=True,
    ))


def label_main(request, label_id):
    """
    Main page for a particular label
    """
    label = get_object_or_404(Label, id=label_id)

    # Sources with the label
    labelsets_with_label = LocalLabel.objects.filter(
        global_label=label).values_list('labelset', flat=True)
    all_sources_with_label = Source.objects.filter(
        labelset__in=labelsets_with_label)

    users_sources = Source.get_sources_of_user(request.user) \
        .filter(pk__in=all_sources_with_label) \
        .order_by('name')

    other_public = Source.get_other_public_sources(request.user) \
        .filter(pk__in=all_sources_with_label) \
        .order_by('name')

    other_private = all_sources_with_label \
        .exclude(pk__in=users_sources) \
        .exclude(pk__in=other_public) \
        .order_by('name')
    # Exclude test sources.
    other_private = filter_out_test_sources(other_private)
    # Exclude small sources.
    other_private = other_private.annotate(image_count=Count('image'))
    other_private = other_private.exclude(image_count__lt=100)

    # Create a dict of the rates from each region, if available for this label.
    # If this label doesn't have rates defined in any region, then this is an
    # empty dict.
    calcification_tables = get_default_calcify_tables()
    calcification_rates = {
        table.region: table.rates_json[str(label_id)]
        for table in calcification_tables
        if str(label_id) in table.rates_json
    }

    # Label usage stats
    source_count = all_sources_with_label.count()

    return render(request, 'labels/label_main.html', {
        'label': label,
        'can_edit_label': is_label_editable_by_user(label, request.user),
        'calcification_rates': calcification_rates,
        'calcification_tables': calcification_tables,
        'users_sources': users_sources,
        'other_public_sources': other_public,
        'other_private_sources': other_private,
        'source_count': source_count,
        'annotation_count': label.ann_count,
    })


@require_GET
def label_example_patches_ajax(request, label_id):
    """
    Example patches for a label.
    """
    label = get_object_or_404(Label, id=label_id)

    try:
        page = int(request.GET.get('page', '1'))
    except ValueError:
        page = 1

    if request.user.is_authenticated:
        page_size = settings.LABEL_EXAMPLE_PATCHES_PER_PAGE
    else:
        page_size = settings.LABEL_EXAMPLE_PATCHES_PER_PAGE_GUEST

    label_details = cacheable_label_details.get()

    if page == 1 and label_details and label_id in label_details:
        # Use the cache
        annotation_ids_full_page = \
            label_details[label_id]['random_patches_page_1']
        # The cached annotations fill up a regular sized page,
        # but if we're requesting as a guest, then we only need
        # the first few elements of that.
        annotation_ids = annotation_ids_full_page[:page_size]

        patch_annotations = Annotation.objects.filter(pk__in=annotation_ids)
        is_last_page = page_size >= label.ann_count
    else:
        all_annotations = Annotation.objects.confirmed() \
            .filter(label=label) \
            .order_by('?')
        paginator = Paginator(all_annotations, page_size)

        try:
            page_annotations = paginator.page(page)
        except (EmptyPage, InvalidPage):
            page_annotations = paginator.page(paginator.num_pages)

        patch_annotations = page_annotations.object_list
        is_last_page = page >= paginator.num_pages

    patches = []
    for index, annotation in enumerate(patch_annotations):
        point = annotation.point
        image = point.image
        source = image.source

        generate_patch_if_doesnt_exist(point.pk)

        if source.visible_to_user(request.user):
            dest_url = reverse('image_detail', args=[image.pk])
        else:
            dest_url = None

        patches.append(dict(
            source=source,
            dest_url=dest_url,
            thumbnail_url=get_patch_url(point.id),
        ))

    return JsonResponse({
        'patchesHtml': render_to_string('labels/label_example_patches.html', {
            'patches': patches,
        }),
        'isLastPage': is_last_page,
    })


@source_visibility_required('source_id')
def labelset_main(request, source_id):
    """
    Main page for a particular source's labelset
    """
    source = get_object_or_404(Source, id=source_id)

    if source.labelset is None:
        return render(request, 'labels/labelset_required.html', {
            'source': source,
            'message': "This source doesn't have a labelset yet.",
        })

    return render(request, 'labels/labelset_main.html', {
        'source': source,
        'labelset': source.labelset,
        'labels': source.labelset.get_locals_ordered_by_group_and_code(),
    })


def labelset_list(request):
    """
    Page with a list of all the labelsets

    Not sure where to put a link to this page. It's a little less
    useful when each source has its own labelset, but this view still
    might be useful if someone wants to browse through labelsets that
    they could base their labelset off of.
    """

    publicSources = Source.objects.filter \
        (visibility=Source.VisibilityTypes.PUBLIC)
    publicSourcesWithLabelsets = publicSources.exclude(labelset=None)

    return render(request, 'labels/labelset_list.html', {
        'publicSourcesWithLabelsets': publicSourcesWithLabelsets,
    })


def label_list(request):
    """
    Page with a list of all the labels
    """
    labels = Label.objects.all().order_by('group__id', 'name').annotate(
        group__name=F('group__name'))

    return render(request, 'labels/label_list.html', {
        'labels': labels,
        'can_edit_labels': request.user.has_perm('labels.change_label'),
        'search_form': LabelSearchForm(),
    })


@require_GET
def label_list_search_ajax(request):
    """
    Takes label search parameters, returns a list of label ids.
    """
    search_form = LabelSearchForm(request.GET)
    if search_form.is_valid():
        labels = search_form.get_labels()
    else:
        return JsonResponse(dict(
            error=get_one_form_error(search_form)))

    return JsonResponse(dict(
        label_ids=[label.pk for label in labels]))
