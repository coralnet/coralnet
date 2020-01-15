from __future__ import division, unicode_literals
import logging
from operator import itemgetter
import random

from celery.decorators import task
from django.conf import settings

from api_core.models import ApiJobUnit
from vision_backend.models import Classifier

logger = logging.getLogger(__name__)


@task(name="Deploy - extract features")
def deploy_extract_features(job_unit_id):

    try:
        features_job_unit = ApiJobUnit.objects.get(pk=job_unit_id)
    except ApiJobUnit.DoesNotExist:
        logger.info("Job unit of id {} does not exist.".format(job_unit_id))
        return

    features_job_unit.status = ApiJobUnit.IN_PROGRESS
    features_job_unit.save()

    # TODO: Download the image from the provided URL (maybe in a separate
    # task?), run feature extraction, and make the below code run after
    # collecting the result (e.g. from spacer).

    request_json = features_job_unit.request_json.copy()
    request_json['features_path'] = ''

    classify_job_unit = ApiJobUnit(
        job=features_job_unit.job,
        type='deploy_classify',
        request_json=request_json)
    classify_job_unit.save()

    deploy_classify.delay(classify_job_unit.pk)

    features_job_unit.status = ApiJobUnit.SUCCESS
    features_job_unit.save()


@task(name="Deploy - classify")
def deploy_classify(job_unit_id):
    try:
        job_unit = ApiJobUnit.objects.get(pk=job_unit_id)
    except ApiJobUnit.DoesNotExist:
        logger.info("Job unit of id {} does not exist.".format(job_unit_id))
        return

    job_unit.status = ApiJobUnit.IN_PROGRESS
    job_unit.save()

    classifier_id = job_unit.request_json['classifier_id']
    try:
        classifier = Classifier.objects.get(pk=classifier_id)
    except Classifier.DoesNotExist:
        message = "Classifier of id {pk} does not exist.".format(
            pk=classifier_id)
        job_unit.result_json = dict(
            url=job_unit.request_json['url'], errors=[message])
        job_unit.status = ApiJobUnit.FAILURE
        job_unit.save()
        return

    # TODO: The following code generates random scores. We should instead
    # use the selected backend (e.g. spacer) to classify.

    labels = classifier.source.labelset.get_globals()
    # Copy this list
    result_points = job_unit.request_json['points'][:]

    for point in result_points:

        random_numbers = [random.random() for _ in range(labels.count())]
        random_number_sum = sum(random_numbers)
        posterior_probabilities = [
            num / random_number_sum for num in random_numbers]

        # Associate the scores with labels, and sort them.
        sorted_label_score_pairs = sorted(
            zip(labels, posterior_probabilities),
            key=itemgetter(1), reverse=True)
        # Keep only the top <nbr_scores> results.
        nbr_scores = min(settings.NBR_SCORES_PER_ANNOTATION, len(labels))
        # Top results as (label, score) pairs.
        top_results = sorted_label_score_pairs[:nbr_scores]

        point['classifications'] = [
            dict(
                label_id=label.pk, label_name=label.name,
                default_code=label.default_code, score=score)
            for label, score in top_results]

    job_unit.result_json = dict(
        url=job_unit.request_json['url'],
        points=result_points)
    job_unit.status = ApiJobUnit.SUCCESS
    job_unit.save()
