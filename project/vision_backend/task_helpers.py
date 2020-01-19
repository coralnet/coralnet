"""
This file contains helper functions to vision_backend.tasks.
"""
import boto.sqs
import os
import json
import logging

import numpy as np

from sklearn import linear_model

from django.conf import settings
from django.utils import timezone
from django.db.models import F
from django.db import transaction
from reversion import revisions

from images.models import Image, Point
from annotations.models import Label, Annotation
from api_core.models import ApiJobUnit

from .models import Classifier, Score


logger = logging.getLogger(__name__)


def _submit_job(messagebody):
    """
    Submits message to the SQS spacer_jobs
    """
    conn = boto.sqs.connect_to_region("us-west-2",
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY)
    queue = conn.get_queue('spacer_jobs')
    m = boto.sqs.message.Message()
    m.set_body(json.dumps(messagebody))
    queue.write(m)


# Must explicitly turn on history creation when RevisionMiddleware is
# not in effect. (It's only in effect within views.)
@revisions.create_revision()
def _add_annotations(image_id, scores, label_objs, classifier):
    """
    Adds annotations objects using the classifier scores.

    :param image_id: Database ID of the Image to add scores for.
    :param scores: List of lists of score numbers. Same as in _add_scores().
    :param label_objs: Iterable of Label DB objects, one per label in the
      source's labelset.

    May throw an IntegrityError when trying to save annotations. The caller is
    responsible for handling the error. In this error case, no annotations
    are saved due to the transaction.atomic() context manager.

    NOTE: this function is SLOW.
    Note that bulk-saving annotations would skip the signal firing,
    and thus would not trigger django-reversion's revision creation.
    So we must save annotations one by one.
    """
    img = Image.objects.get(pk = image_id)
    points = Point.objects.filter(image=img).order_by('id')
    estlabels = [np.argmax(score) for score in scores]
    with transaction.atomic():
        for pt, estlabel in zip(points, estlabels):
            
            label = label_objs[estlabel]

            Annotation.objects.update_point_annotation_if_applicable(
                point=pt, label=label,
                now_confirmed=False,
                user_or_robot_version=classifier)


def _add_scores(image_id, scores, label_objs):
    """
    Adds score objects using the classifier scores.

    :param image_id: Database ID of the Image to add scores for.
    :param scores: List of lists of score numbers.
      Each score number is a float; 0.65 to represent 65% probability. Will be
      rounded as needed.
      Each inner list consists of the scores for ALL labels in the source's
      labelset, for one particular point. The scores should be in the same
      order as label_objs.
      The outer list consists of one score list per point in the image. The
      points are assumed to be in database ID order.
    :param label_objs: Iterable of Label DB objects, one per label in the
      source's labelset.
    """
    img = Image.objects.get(pk = image_id)

    # First, delete all scores associated with this image.
    Score.objects.filter(image = img).delete()

    # Figure out how many of the (top) scores to store.
    nbr_scores = min(settings.NBR_SCORES_PER_ANNOTATION, len(scores[0]))

    # Now, go through and create new ones.
    points = Point.objects.filter(image = img).order_by('id')
    
    score_objs = []
    for point, score in zip(points, scores):
        inds = np.argsort(score)[::-1][:nbr_scores] # grab the index of the n highest index
        for ind in inds:
            score_objs.append(
                Score(
                    source = img.source, 
                    image = img, 
                    label = label_objs[ind],
                    point = point, 
                    score = int(round(score[ind]*100))
                )
            )
    Score.objects.bulk_create(score_objs)


def _make_dataset(images):
    """
    Helper funtion for classifier_submit. Assemples all features and ground truth annotations
    for training and evaluation of the robot classifier.
    """
    gtdict = {}
    for img in images:
        full_image_path = os.path.join(settings.AWS_LOCATION, img.original_file.name)
        feature_key = settings.FEATURE_VECTOR_FILE_PATTERN.format(full_image_path = full_image_path)
        anns = Annotation.objects.filter(image = img).order_by('point__id').annotate(gt = F('label__id'))
        gtlabels = [int(ann.gt) for ann in anns]
        gtdict[feature_key] = gtlabels
    return gtdict


def _read_message(queue_name):
    """
    helper function for reading messages from AWS SQS.
    """

    conn = boto.sqs.connect_to_region("us-west-2",
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY)

    queue = conn.get_queue(queue_name)

    message = queue.read()
    if message is None:
        return None
    else:
        return message


def _featurecollector(messagebody):
    """
    collects feature_extract jobs.
    """
    image_id = messagebody['original_job']['payload']['pk']
    try:
        img = Image.objects.get(pk = image_id)
    except:
        logger.info("Image {} was deleted. Aborting".format(image_id))
        return 0
    logstr = "Image {} [Source: {} [{}]]".format(image_id, img.source, img.source_id)
        
    # Double-check that the row-col information is still correct.
    rowcols = []
    for point in Point.objects.filter(image = img).order_by('id'):
        rowcols.append([point.row, point.column])

    if not rowcols == messagebody['original_job']['payload']['rowcols']:
        logger.info("Row-col for {} have changed. Aborting.".format(logstr))
        return 0
    
    # If all is ok store meta-data.
    img.features.extracted = True
    img.features.runtime_total = messagebody['result']['runtime']['total']
    img.features.runtime_core = messagebody['result']['runtime']['core']
    img.features.model_was_cashed = messagebody['result']['model_was_cashed']
    img.features.extracted_date = timezone.now()
    img.features.save()
    return 1


def _classifiercollector(messagebody):
    """
    collects train_classifier jobs.
    """
    result = messagebody['result']
    payload = messagebody['original_job']['payload']
    
    # Check that Classifier still exists. 
    try:
        classifier = Classifier.objects.get(pk = payload['pk'])
    except:
        logger.info("Classifier {} was deleted. Aborting".format(payload['pk']))
        return 0
    logstr = 'Classifier {} [Source: {} [{}]]'.format(classifier.pk, classifier.source, classifier.source.id)
    
    # If training didn't finish with OK status, return false and exit.
    if not result['ok']:
        return 0

    # Store generic stats
    classifier.runtime_train = result['runtime']
    classifier.accuracy = result['acc']
    classifier.epoch_ref_accuracy = str([int(round(10000 * ra)) for ra in result['refacc']])
    classifier.save()

    # Check that the accuracy is higher than the previous classifiers
    if 'pc_models' in payload and len(payload['pc_models']) > 0:
        if max(result['pc_accs']) * settings.NEW_CLASSIFIER_IMPROVEMENT_TH > result['acc']:
            logger.info("{} worse than previous. Not validated. Max previous: {:.2f}, threshold: {:.2f}, this: {:.2f}".format(logstr, max(result['pc_accs']), max(result['pc_accs']) * settings.NEW_CLASSIFIER_IMPROVEMENT_TH, result['acc']))
            return 0
        
        # Update accuracy for previous models
        for pc_pk, pc_acc in zip(payload['pc_pks'], result['pc_accs']):
            pc = Classifier.objects.get(pk=pc_pk)
            pc.accuracy = pc_acc
            pc.save()
    
    classifier.valid = True
    classifier.save()
    logger.info("{} collected successfully.".format(logstr))
    return 1


def _deploycollector(messagebody):

    def build_points_dicts(scores, classes, rowcols):
        """
        Converts scores from the deploy call to the dictionary returned
        by the API
        """

        # Figure out how many of the (top) scores to store.
        nbr_scores = min(settings.NBR_SCORES_PER_ANNOTATION, len(scores[0]))

        # Pre-fetch label objects
        label_objs = []
        for class_ in classes:
            label_objs.append(Label.objects.get(pk=class_))

        data = []
        for score, rowcol in zip(scores, rowcols):
            # grab the index of the highest indices
            inds = np.argsort(score)[::-1][:nbr_scores]
            classifications = []
            for ind in inds:
                label_obj = label_objs[ind]
                classifications.append(dict(
                    label_id=label_obj.pk,
                    label_name=label_obj.name,
                    label_code=label_obj.default_code,
                    score=score[ind]))
            data.append(dict(
                row=rowcol[0],
                column=rowcol[1],
                classifications=classifications
            ))
        return data

    result = messagebody['result']
    org_payload = messagebody['original_job']['payload']

    pk = org_payload['pk']
    try:
        job_unit = ApiJobUnit.objects.get(pk=pk)
    except ApiJobUnit.DoesNotExist:
        logger.info("Job unit of id {} does not exist.".format(pk))
        return

    # TODO add result status to spacer, and read here.
    # For now assume job was successful.
    # if not result['ok']:
    #     job_unit.status = ApiJobUnit.FAILURE
    #     job_unit.save()
    # else:
    job_unit.result_json = dict(
        url=job_unit.request_json['url'],
        points=build_points_dicts(
            result['scores'],
            result['classes'],
            org_payload['rowcols'])
    )
    job_unit.status = ApiJobUnit.SUCCESS
    job_unit.save()
