import csv
import datetime
import json

import numpy as np

from django.contrib import messages
from django.contrib.auth.decorators import permission_required
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from spacer.data_classes import ValResults

from images.models import Image
from jobs.models import Job
from lib.decorators import (
    source_permission_required, source_visibility_required)
from lib.utils import paginate
from sources.models import Source
from .confmatrix import ConfMatrix
from .forms import BackendMainForm, CmTestForm
from .models import Classifier
from .utils import (
    labelset_mapper, map_labels, get_alleviate, schedule_source_check)


@permission_required('is_superuser')
def backend_overview(request):
    images_all = Image.objects.all()
    total = images_all.count()

    confirmed = images_all.confirmed().count()
    unconfirmed = images_all.unconfirmed().count()
    images_unclassified = images_all.unclassified()
    images_need_features = \
        images_unclassified.without_features().exclude(
            source__deployed_classifier__isnull=True,
            source__trains_own_classifiers=False)
    images_need_classification = \
        images_unclassified.with_features().exclude(
            source__deployed_classifier__isnull=True)
    need_features = images_need_features.count()
    need_classification = images_need_classification.count()
    not_ready = \
        images_unclassified.count() - need_features - need_classification

    def percent_display(numerator, denominator):
        return format(100*numerator / denominator, '.1f') + "%"

    image_stats = [
        [
            "Confirmed",
            confirmed,
            percent_display(confirmed, total),
        ],
        [
            "Unconfirmed",
            unconfirmed,
            percent_display(unconfirmed, total),
        ],
        [
            "Unclassified, need features",
            need_features,
            percent_display(need_features, total),
        ],
        [
            "Unclassified, need classification",
            need_classification,
            percent_display(need_classification, total),
        ],
        [
            "Unclassified, not ready for features/classification",
            not_ready,
            percent_display(not_ready, total),
        ],
        [
            "All",
            total,
            "100.0%",
        ],
    ]

    all_sources = Source.objects.all()
    all_classifiers = Classifier.objects.all()
    accepted_classifiers = all_classifiers.filter(status=Classifier.ACCEPTED)
    accepted_ratio = format(
        accepted_classifiers.count() / all_sources.count(), '.1f')
    clf_stats = {
        'nclassifiers': all_classifiers.count(),
        'nacceptedclassifiers': accepted_classifiers.count(),
        'nsources': all_sources.count(),
        'accepted_ratio': accepted_ratio,
    }

    latest_source_check_values = (
        Job.objects.filter(job_name='check_source', status=Job.Status.SUCCESS)
        .order_by('source', '-id').distinct('source')
        .values('source', 'result_message')
    )
    latest_check_lookup = {
        v['source']: v['result_message'] for v in latest_source_check_values
    }

    sorted_sources = []
    for source in all_sources:
        check_message = latest_check_lookup.get(source.pk)
        if check_message is None:
            # No source check has been done recently
            status = 'needs_check'
            status_order = 2
        elif (
            "all caught up" in check_message
            or "Can't train first classifier" in check_message
            or "Machine classification isn't configured" in check_message
        ):
            status = 'caught_up'
            status_order = 3
        else:
            status = 'needs_processing'
            status_order = 1
        sorted_sources.append(dict(
            status=status, status_order=status_order,
            source_id=source.pk, source=source,
        ))
    sorted_sources.sort(key=lambda s: (s['status_order'], -s['source_id']))

    page_results, _ = paginate(
        results=sorted_sources,
        items_per_page=200,
        request_args=request.GET,
    )

    page_sources = []
    for source_dict in page_results.object_list:
        source_id = source_dict['source_id']
        source = source_dict['source']
        last_accepted_classifier = source.last_accepted_classifier
        page_sources.append(dict(
            pk=source_id,
            status=source_dict['status'],
            name=source.name,
            image_count=source.image_set.count(),
            confirmed_image_count=source.image_set.confirmed().count(),
            classifier_image_count=(
                last_accepted_classifier.nbr_train_images
                if last_accepted_classifier
                else 0
            ),
            check_message=latest_check_lookup.get(source_id) or "(None)",
        ))

    return render(request, 'vision_backend/overview.html', {
        'page_results': page_results,
        'page_sources': page_sources,
        'image_stats': image_stats,
        'clf_stats': clf_stats,
    })


@source_visibility_required('source_id')
def backend_main(request, source_id):

    # Default form values.
    confidence_threshold = 0
    label_mode = 'full'
    initial = {
        'confidence_threshold': confidence_threshold,
        'label_mode': label_mode,
    }
    form = BackendMainForm(initial=initial)

    if request.GET:
        # Form submission.
        # Using GET is OK here as this view only reads from DB.
        form = BackendMainForm(request.GET)
        if form.is_valid():
            confidence_threshold = form.cleaned_data['confidence_threshold']
            label_mode = form.cleaned_data['label_mode']

    source = Source.objects.get(id=source_id)

    # Make sure that there is a classifier for this source.
    if not source.deployed_classifier:
        return render(request, 'vision_backend/backend_main.html', {
            'form': form,
            'has_classifier': False,
            'source': source,
        })

    classifier = source.deployed_classifier
    if 'valres' in request.session.keys() and \
            'classifier_id' in request.session.keys() and \
            request.session['classifier_id'] == classifier.pk:
        pass
    else:
        valres: ValResults = classifier.valres
        request.session['valres'] = valres.serialize()
        request.session['classifier_id'] = classifier.pk
    
    # Load stored variables to local namespace
    valres: ValResults = ValResults.deserialize(request.session['valres'])
    
    # find classmap and class names for selected label-mode
    classmap, classnames = labelset_mapper(label_mode, valres.classes, source)

    # Initialize confusion matrix
    cm = ConfMatrix(len(classnames), labelset=classnames)

    # Add data-points above the threshold.
    cm.add_select(map_labels(valres.gt, classmap),
                  map_labels(valres.est, classmap), valres.scores,
                  confidence_threshold / 100)

    # Sort by descending order.
    cm.sort()

    max_display_labels = 50
    
    if cm.nclasses > max_display_labels:
        cm.cut(max_display_labels)

    if label_mode == 'full':
        labelset_description = "full labelset"
    else:
        # 'func'
        labelset_description = "functional groups"

    # Export for heat-map
    cm_render = dict()
    cm_render['data_'], cm_render['xlabels'], cm_render[
        'ylabels'] = cm.render_for_heatmap()
    cm_render['title_'] = json.dumps(
        'Confusion matrix for {} (acc:{}, n: {})'.format(
            labelset_description,
            round(100 * cm.get_accuracy()[0], 1),
            int(np.sum(np.sum(cm.cm))),
        ))
    cm_render['css_height'] = max(500, cm.nclasses * 22 + 320)
    cm_render['css_width'] = max(600, cm.nclasses * 22 + 360)

    # Prepare the alleviate plot if not allready in session
    if 'alleviate_data' not in request.session.keys():
        acc_full, ratios, confs = get_alleviate(valres.gt, valres.est,
                                                valres.scores)
        classmap, _ = labelset_mapper('func', valres.classes, source)
        acc_func, _, _ = get_alleviate(map_labels(valres.gt, classmap),
                                       map_labels(valres.est, classmap),
                                       valres.scores)
        request.session['alleviate'] = dict()
        for member in ['acc_full', 'acc_func', 'ratios']:
            request.session['alleviate'][member] = [[conf, val] for val, conf
                                                    in
                                                    zip(eval(member), confs)]

    # Handle the case where we are exporting the confusion matrix.
    if request.method == 'POST' and request.POST.get('export_cm', None):
        vecfmt = np.vectorize(myfmt)

        # create CSV file
        response = HttpResponse()
        response[
            'Content-Disposition'] = \
            'attachment;filename=confusion_matrix_{}_{}.csv'.format(
                label_mode, confidence_threshold)
        writer = csv.writer(response)

        for enu, classname in enumerate(cm.labelset):
            row = [classname]
            row.extend(vecfmt(cm.cm[enu, :]))
            writer.writerow(row)

        return response

    return render(request, 'vision_backend/backend_main.html', {
        'form': form,
        'has_classifier': True,
        'source': source,
        'cm': cm_render,
        'alleviate': request.session['alleviate'],
    })


def myfmt(r):
    """Helper function to format numpy outputs"""
    return "%.0f" % (r,)


@require_POST
@source_permission_required('source_id', perm=Source.PermTypes.EDIT.code)
def request_source_check(request, source_id):
    source_jobs = Job.objects.filter(source_id=source_id)
    is_doing_any_job = source_jobs.incomplete().exists()

    if is_doing_any_job:
        messages.error(request, "There are still active jobs to wait for.")
    else:
        try:
            latest_check = source_jobs.completed().filter(
                job_name='check_source').latest('pk')
        except Job.DoesNotExist:
            delay = datetime.timedelta(0)
        else:
            # Wait 30 minutes since the last check, as needed.
            base_delay = datetime.timedelta(minutes=30)
            time_since_check = timezone.now() - latest_check.modify_date
            delay = max(base_delay - time_since_check, datetime.timedelta(0))

        schedule_source_check(source_id, delay=delay)
        messages.success(request, "Source check scheduled.")

    return HttpResponseRedirect(reverse('jobs:source_job_list', args=[source_id]))


@permission_required('is_superuser')
def cm_test(request):
    """
    Test and debug function for confusion matrices.
    """
    nlabels = int(request.GET.get('nlabels', 5))
    namelength = int(request.GET.get('namelength', 25))

    # Initialize form
    form = CmTestForm()
    form.initial['nlabels'] = nlabels
    form.initial['namelength'] = namelength

    # Initialize confusion matrix
    cm = ConfMatrix(nlabels, labelset=['a' * namelength] * nlabels)

    # Add datapoints above the threhold.
    cm.add(np.random.choice(nlabels, size=10 * nlabels),
           np.random.choice(nlabels, size=10 * nlabels))

    # Sort by descending order.
    cm.sort()

    max_display_labels = 50

    if nlabels > max_display_labels:
        cm.cut(max_display_labels)
    # Export for heatmap
    cm_render = dict()
    cm_render['data_'], cm_render['xlabels'], cm_render[
        'ylabels'] = cm.render_for_heatmap()
    cm_render['title_'] = '"This is a title"'
    cm_render['css_height'] = max(500, cm.nclasses * 22 + 320)
    cm_render['css_width'] = max(600, cm.nclasses * 22 + 360)

    return render(request, 'vision_backend/cm_test.html', {
        'form': form,
        'cm': cm_render,
    })
