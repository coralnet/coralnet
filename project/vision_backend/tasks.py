import os
import logging
import json

from celery.decorators import task, periodic_task
from django.conf import settings
from django.db import IntegrityError
from django.utils.timezone import now

from datetime import timedelta

import task_helpers as th

from .models import Classifier, Score
from annotations.models import Annotation
from images.models import Source, Image, Point
from labels.models import LabelSet, Label
from api_core.models import ApiJobUnit

from lib.utils import direct_s3_read, direct_s3_write
from accounts.utils import get_robot_user

logger = logging.getLogger(__name__)


@task(name="Submit Features")
def submit_features(image_id, force=False):
    """
    Submits a job to SQS for extracting features for an image.
    """
    # Do some initial checks
    if not settings.DEFAULT_FILE_STORAGE == 'lib.storage_backends.MediaStorageS3' or settings.FORCE_NO_BACKEND_SUBMIT:
        logger.info("Can't use vision backend if media is stored locally.")
        return

    try:
        img = Image.objects.get(pk=image_id)
    except:
        logger.info("Image {} does not exist.".format(image_id))
        return
    logstr = u"Image {} [Source: {} [{}]]".format(image_id, img.source, img.source_id)

    if img.features.extracted and not force:
        logger.info(u"{} already has features".format(logstr))
        return

    # Assemble row column information
    rowcols = []
    for point in Point.objects.filter(image=img).order_by('id'):
        rowcols.append([point.row, point.column])
    
    # Setup the job payload.
    full_image_path = os.path.join(settings.AWS_LOCATION, img.original_file.name)
    payload = {
        'bucketname': settings.AWS_STORAGE_BUCKET_NAME,
        'imkey': full_image_path,
        'outputkey': settings.FEATURE_VECTOR_FILE_PATTERN.format(full_image_path=full_image_path),
        'modelname': 'vgg16_coralnet_ver1',
        'rowcols': rowcols,
        'pk': image_id
    }

    # Assemble message body.
    messagebody = {
        'task': 'extract_features',
        'payload': payload
    }

    # Submit.
    th._submit_job(messagebody)

    logger.info(u"Submitted feature extraction for {}".format(logstr))
    logger.debug(u"Submitted feature extraction for {}. Message: {}".format(logstr, messagebody))
    return messagebody


@periodic_task(run_every=timedelta(hours = 24), name='Periodic Classifiers Submit', ignore_result=True)
def submit_all_classifiers():
    for source in Source.objects.filter():
        if source.need_new_robot():
            submit_classifier.delay(source.id)


@task(name="Submit Classifier")
def submit_classifier(source_id, nbr_images=1e5, force=False):

    # Do some initial checks
    if not settings.DEFAULT_FILE_STORAGE == 'lib.storage_backends.MediaStorageS3' or settings.FORCE_NO_BACKEND_SUBMIT:
        logger.info("Can't use vision backend if media is stored locally.")
        return

    try:
        source = Source.objects.get(pk=source_id)
    except:
        logger.info("Can't find source [{}]".format(source_id))
        return
    
    if not source.need_new_robot() and not force:
        logger.info(u"Source {} [{}] don't need new classifier.".format(source.name, source.pk))
        return

    logger.info(u"Preparing new classifier for {} [{}].".format(source.name, source.pk))
    
    # Create new classifier model
    images = Image.objects.filter(source = source, confirmed = True, features__extracted = True)[:nbr_images]
    classifier = Classifier(source = source, nbr_train_images = len(images))
    classifier.save()

    # Write traindict to S3
    direct_s3_write(
        settings.ROBOT_MODEL_TRAINDATA_PATTERN.format(pk = classifier.pk, media = settings.AWS_LOCATION),
        'json',
        th._make_dataset([image for image in images if image.trainset])
    )

    # Write valdict to S3
    direct_s3_write(
        settings.ROBOT_MODEL_VALDATA_PATTERN.format(pk = classifier.pk, media = settings.AWS_LOCATION),
        'json',
        th._make_dataset([image for image in images if image.valset])
    )
        
    # Prepare information for the message payload
    previous_classifiers = Classifier.objects.filter(source=source, valid=True) # This will not include the current.
    pc_models = [settings.ROBOT_MODEL_FILE_PATTERN.format(pk=pc.pk, media=settings.AWS_LOCATION) for pc in previous_classifiers]
    pc_pks = [pc.pk for pc in previous_classifiers]  # Primary keys needed for collect task.

    # Create payload
    payload = {
        'bucketname': settings.AWS_STORAGE_BUCKET_NAME,
        'model': settings.ROBOT_MODEL_FILE_PATTERN.format(pk = classifier.pk, media = settings.AWS_LOCATION),
        'traindata': settings.ROBOT_MODEL_TRAINDATA_PATTERN.format(pk = classifier.pk, media = settings.AWS_LOCATION),
        'valdata': settings.ROBOT_MODEL_VALDATA_PATTERN.format(pk = classifier.pk, media = settings.AWS_LOCATION),
        'valresult': settings.ROBOT_MODEL_VALRESULT_PATTERN.format(pk = classifier.pk, media = settings.AWS_LOCATION),
        'pk': classifier.pk,
        'nbr_epochs': settings.NBR_TRAINING_EPOCHS,
        'pc_models': pc_models,
        'pc_pks': pc_pks
    }

    # Assbmeble the message body.
    messagebody = {
        'task': 'train_classifier',
        'payload': payload
    }

    # Submit.
    th._submit_job(messagebody)

    logger.info(u"Submitted classifier for source {} [{}] with {} images.".format(source.name, source.id, len(images)))
    logger.debug(u"Submitted classifier for source {} [{}] with {} images. Message: {}".format(source.name, source.id, len(images), messagebody))
    return messagebody
 

@task(name="Deploy")
def deploy(job_unit_id):

    try:
        job_unit = ApiJobUnit.objects.get(pk=job_unit_id)
    except ApiJobUnit.DoesNotExist:
        logger.info("Job unit of id {} does not exist.".format(job_unit_id))
        return

    job_unit.status = ApiJobUnit.IN_PROGRESS
    job_unit.save()

    rowcols = [[point['row'], point['column']] for point in
               job_unit.request_json['points']]

    payload = {
        'bucketname': settings.AWS_STORAGE_BUCKET_NAME,
        'im_url': job_unit.request_json['url'],
        'modelname': 'vgg16_coralnet_ver1',
        'rowcols': rowcols,
        'model': settings.ROBOT_MODEL_FILE_PATTERN.format(
            pk=job_unit.request_json['classifier_id'],
            media=settings.AWS_LOCATION),
    }

    # Assemble message body.
    messagebody = {
        'task': 'deploy',
        'payload': payload
    }

    th._submit_job(messagebody)

    logger.info(u"Submitted image at url: {} for deploy with job unit {}.".
                format(job_unit.request_json['url'], job_unit.pk))

    return messagebody


@task(name="Classify Image")
def classify_image(image_id):

    try:
        img = Image.objects.get(pk=image_id)
    except:
        logger.info("Image {} does not exist.".format(image_id))
        return

    if not img.features.extracted:
        return    

    classifier = img.source.get_latest_robot()
    if not classifier:
        return

    # Load model
    classifier_model = direct_s3_read(
        settings.ROBOT_MODEL_FILE_PATTERN.format(
            pk=classifier.pk, media=settings.AWS_LOCATION), 'pickle')
    
    feats = direct_s3_read(
        settings.FEATURE_VECTOR_FILE_PATTERN.format(
            full_image_path=os.path.join(settings.AWS_LOCATION,
                                         img.original_file.name)), 'json')

    # Classify.
    scores = classifier_model.predict_proba(feats)

    # Pre-fetch label objects
    label_objs = []
    for class_ in classifier_model.classes_:
        label_objs.append(Label.objects.get(pk=class_))

    # Add annotations if image isn't already confirmed    
    if not img.confirmed:
        try:
            th._add_annotations(image_id, scores, label_objs, classifier)
        except IntegrityError:
            logger_message = u"Failed to classify Image {} [Source: {} [{}] " \
                             u"with classifier {}. There might have been a race" \
                             u" condition when trying to save annotations. " \
                             u"Will try again later."
            logger.info(logger_message.format(img.id, img.source,
                                              img.source_id, classifier.id))
            classify_image.apply_async(args=[image_id], eta=now() + timedelta(seconds=10))
            return
    
    # Always add scores
    th._add_scores(image_id, scores, label_objs)
    
    img.features.classified = True
    img.features.save()

    logger.info(u"Classified Image {} [Source: {} [{}]] with classifier {}".
                format(img.id, img.source, img.source_id, classifier.id))


@periodic_task(run_every=timedelta(seconds=60), name='Collect all jobs', ignore_result=True)
def collect_all_jobs():
    """
    Runs collectjob until queue is empty.
    """
    logger.info('Collecting all jobs in result queue.')
    while collectjob():
        pass
    logger.info('Done collecting all jobs in result queue.')


def collectjob():
    """
    main task for collecting jobs from AWS SQS.
    """
    
    # Grab a message
    message = th._read_message('spacer_results')
    if message is None:
        return 0
    messagebody = json.loads(message.get_body())

    # Check that the message pertains to this server
    if not messagebody['original_job']['payload']['bucketname'] == settings.AWS_STORAGE_BUCKET_NAME:
        logger.info("Job pertains to wrong bucket [%]".format(messagebody['original_job']['payload']['bucketname']))
        return 1

    # Delete message (at this point, if it is not handled correctly,
    # we still want to delete it from queue.)
    message.delete()

    # Handle message
    task = messagebody['original_job']['task']
    pk = messagebody['original_job']['payload']['pk']
    
    if task == 'extract_features':
        if th._featurecollector(messagebody): 
            # If job was entered into DB, submit a classify job.
            classify_image.apply_async(args=[pk], eta=now() + timedelta(seconds=10))
 
    elif task == 'train_classifier':
        if th._classifiercollector(messagebody):
            # If job was entered into DB, submit a classify job for all images in source.
            classifier = Classifier.objects.get(pk=pk)
            for image in Image.objects.filter(source=classifier.source, features__extracted=True, confirmed=False):
                classify_image.apply_async(args=[image.id], eta=now() + timedelta(seconds = 10))
    elif task == 'deploy':
        # TODO, make the colletors public
        th._deploycollector(messagebody)

    else:
        logger.error('Job task type {} not recognized'.format(task))
    
    # Conclude
    logger.info("job {}, pk: {} collected successfully".format(task, pk))
    logger.debug("Collected job with messagebody: {}".format(messagebody))
    return 1


@task(name="Reset Source")
def reset_after_labelset_change(source_id):
    """
    The removes ALL TRACES of the vision backend for this source, including:
    1) Delete all Score objects for all images
    2) Delete Classifier objects
    3) Sets all image.features.classified = False
    """
    Score.objects.filter(source_id = source_id).delete()
    Classifier.objects.filter(source_id = source_id).delete()
    Annotation.objects.filter(source_id = source_id, user = get_robot_user()).delete()
    for image in Image.objects.filter(source_id = source_id):
        image.features.classified = False
        image.features.save()

    # Finally, let's train a new classifier.
    submit_classifier.apply_async(args = [source_id], eta = now() + timedelta(seconds = 10))


@task(name="Reset Features")
def reset_features(image_id):
    """
    Resets features for image. Call this after any change that affects the image 
    point locations. E.g:
    Re-generate point locations.
    Change annotation area.
    Add new poits.
    """

    img = Image.objects.get(pk = image_id)
    features = img.features
    features.extracted = False
    features.classified = False
    features.save()

    # Re-submit feature extraction.
    submit_features.apply_async(args = [img.id], eta = now() + timedelta(seconds = 10))




