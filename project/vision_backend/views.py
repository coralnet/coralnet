import csv
import json

import numpy as np

from django.contrib.auth.decorators import permission_required
from django.http import HttpResponse
from django.shortcuts import render
from spacer.data_classes import ValResults

from images.models import Image
from jobs.models import Job
from lib.decorators import source_visibility_required
from lib.utils import paginate
from sources.models import Source
from .confmatrix import ConfMatrix
from .forms import TreshForm, CmTestForm
from .models import Classifier
from .utils import labelset_mapper, map_labels, get_alleviate


@permission_required('is_superuser')
def backend_overview(request):
    total = Image.objects.filter().count()

    images_backend_enabled = \
        Image.objects.filter(source__enable_robot_classifier=True)
    confirmed = images_backend_enabled.confirmed().count()
    unconfirmed = images_backend_enabled.unconfirmed().count()
    unclassified_with_features = \
        images_backend_enabled.unclassified().with_features().count()
    unclassified_without_features = \
        images_backend_enabled.unclassified().without_features().count()
    backend_disabled = \
        Image.objects.filter(source__enable_robot_classifier=False).count()

    def percent_display(numerator, denominator):
        return format(100*numerator / denominator, '.1f') + "%"

    img_stats = {
        'total': total,
        'confirmed': confirmed,
        'unconfirmed': unconfirmed,
        'unclassified_with_features': unclassified_with_features,
        'unclassified_without_features': unclassified_without_features,
        'backend_disabled': backend_disabled,
        'pct_confirmed': percent_display(confirmed, total),
        'pct_unconfirmed': percent_display(unconfirmed, total),
        'pct_unclassified_with_features': percent_display(
            unclassified_with_features, total),
        'pct_unclassified_without_features': percent_display(
            unclassified_without_features, total),
        'pct_backend_disabled': percent_display(backend_disabled, total),
    }

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
        current_classifier = source.get_current_classifier()
        page_sources.append(dict(
            pk=source_id,
            status=source_dict['status'],
            name=source.name,
            image_count=source.image_set.count(),
            confirmed_image_count=source.image_set.confirmed().count(),
            classifier_image_count=(
                current_classifier.nbr_train_images
                if current_classifier
                else 0
            ),
            check_message=latest_check_lookup.get(source_id) or "(None)",
        ))

    return render(request, 'vision_backend/overview.html', {
        'page_results': page_results,
        'page_sources': page_sources,
        'img_stats': img_stats,
        'clf_stats': clf_stats,
    })


@source_visibility_required('source_id')
def backend_main(request, source_id):
    # Read plotting input from the request.
    # (Using GET is OK here as this view only reads from DB).
    confidence_threshold = int(request.GET.get('confidence_threshold', 0))
    labelmode = request.GET.get('labelmode', 'full')
    
    # Initialize form
    form = TreshForm()    
    form.initial['confidence_threshold'] = confidence_threshold
    form.initial['labelmode'] = labelmode

    # Mapper for pretty printing.
    labelmodestr = {
        'full': 'full labelset',
        'func': 'functional groups',
    }

    # Get source
    source = Source.objects.get(id=source_id)

    # Make sure that there is a classifier for this source.
    if not source.has_robot():
        return render(request, 'vision_backend/backend_main.html', {
            'form': form,
            'has_classifier': False,
            'source': source,
        })

    cc = source.get_current_classifier()
    if 'valres' in request.session.keys() and \
            'ccpk' in request.session.keys() and \
            request.session['ccpk'] == cc.pk:
        pass
    else:
        valres: ValResults = cc.valres
        request.session['valres'] = valres.serialize()
        request.session['ccpk'] = cc.pk
    
    # Load stored variables to local namespace
    valres: ValResults = ValResults.deserialize(request.session['valres'])
    
    # find classmap and class names for selected label-mode
    classmap, classnames = labelset_mapper(labelmode, valres.classes, source)

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

    # Export for heat-map
    cm_render = dict()
    cm_render['data_'], cm_render['xlabels'], cm_render[
        'ylabels'] = cm.render_for_heatmap()
    cm_render['title_'] = json.dumps(
        'Confusion matrix for {} (acc:{}, n: {})'.format(
            labelmodestr[labelmode], round(100 * cm.get_accuracy()[0], 1),
            int(np.sum(np.sum(cm.cm)))))
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
                labelmode, confidence_threshold)
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
