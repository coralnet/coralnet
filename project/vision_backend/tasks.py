import logging
from datetime import timedelta

from celery.decorators import task, periodic_task
from django.conf import settings
from django.core.files.storage import get_storage_class
from django.core.mail import mail_admins
from django.db import IntegrityError
from django.utils import timezone
from django.utils.timezone import now
from spacer.messages import \
    ExtractFeaturesMsg, \
    TrainClassifierMsg, \
    ClassifyFeaturesMsg, \
    ClassifyImageMsg, \
    ClassifyReturnMsg, \
    JobMsg, \
    JobReturnMsg, \
    DataLocation
from spacer.tasks import classify_features as spacer_classify_features

from accounts.utils import get_robot_user
from annotations.models import Annotation
from api_core.models import ApiJobUnit
from images.models import Source, Image, Point
from labels.models import Label
from . import task_helpers as th
from .models import Classifier, Score, BatchJob
from .queues import get_queue_class

logger = logging.getLogger(__name__)


@task(name="Submit Features")
def submit_features(image_id, force=False):
    """ Submits a feature extraction job. """

    try:
        img = Image.objects.get(pk=image_id)
    except Image.DoesNotExist:
        logger.info("Image {} does not exist.".format(image_id))
        return
    log_str = u"Image {} [Source: {} [{}]]".format(image_id, img.source,
                                                   img.source_id)

    if img.features.extracted and not force:
        logger.info(u"{} already has features".format(log_str))
        return

    # Setup the job payload.
    storage = get_storage_class()()

    # Assemble row column information
    rowcols = [(p.row, p.column) for p in Point.objects.filter(image=img)]

    # Assemble task.
    task = ExtractFeaturesMsg(
        job_token=th.encode_spacer_job_token([image_id]),
        feature_extractor_name=img.source.feature_extractor,
        rowcols=list(set(rowcols)),
        image_loc=storage.spacer_data_loc(img.original_file.name),
        feature_loc=storage.spacer_data_loc(
            settings.FEATURE_VECTOR_FILE_PATTERN.format(
                full_image_path=img.original_file.name))
    )

    msg = JobMsg(task_name='extract_features', tasks=[task])

    # Submit.
    queue = get_queue_class()()
    queue.submit_job(msg)

    logger.info(u"Submitted feature extraction for {}".format(log_str))
    return msg


@periodic_task(run_every=timedelta(hours=24),
               name='Periodic Classifiers Submit',
               ignore_result=True)
def submit_all_classifiers():
    for source in Source.objects.filter():
        if source.need_new_robot():
            submit_classifier.delay(source.id)


@task(name="Submit Classifier")
def submit_classifier(source_id, nbr_images=1e5, force=False):
    """ Submits a classifier training job. """
    try:
        source = Source.objects.get(pk=source_id)
    except Source.DoesNotExist:
        logger.info("Can't find source [{}]".format(source_id))
        return

    if not source.need_new_robot() and not force:
        logger.info(u"Source {} [{}] don't need new classifier.".format(
            source.name, source.pk))
        return

    # Create new classifier model
    images = Image.objects.filter(source=source, confirmed=True,
                                  features__extracted=True)[:nbr_images]
    classifier = Classifier(source=source, nbr_train_images=len(images))
    classifier.save()

    logger.info(u"Preparing new classifier ({}) for {} [{}].".format(
        classifier.pk, source.name, source.pk))

    # Write train-labels to file storage
    storage = get_storage_class()()
    train_labels = th.make_dataset([image for image in images if image.trainset])

    # Write val-labels to file storage
    val_labels = th.make_dataset([image for image in images if image.valset])

    # This will not include the one we just created, b/c it is not valid.
    prev_classifiers = Classifier.objects.filter(source=source, valid=True)

    # Primary keys needed for collect task.
    pc_pks = [pc.pk for pc in prev_classifiers]

    # Create TrainClassifierMsg
    task = TrainClassifierMsg(
        job_token=th.encode_spacer_job_token([classifier.pk] + pc_pks),
        trainer_name='minibatch',
        nbr_epochs=settings.NBR_TRAINING_EPOCHS,
        clf_type=settings.CLASSIFIER_MAPPINGS[source.feature_extractor],
        train_labels=train_labels,
        val_labels=val_labels,
        features_loc=storage.spacer_data_loc(''),
        previous_model_locs=[storage.spacer_data_loc(
            settings.ROBOT_MODEL_FILE_PATTERN.format(pk=pc.pk))
            for pc in prev_classifiers],
        model_loc=storage.spacer_data_loc(
            settings.ROBOT_MODEL_FILE_PATTERN.format(pk=classifier.pk)),
        valresult_loc=storage.spacer_data_loc(
            settings.ROBOT_MODEL_VALRESULT_PATTERN.format(pk=classifier.pk))
    )

    # Assemble the message body.
    msg = JobMsg(task_name='train_classifier', tasks=[task])

    # Submit.
    queue = get_queue_class()()
    queue.submit_job(msg)

    logger.info(u"Submitted classifier {} for source {} [{}] with {} images.".
                format(classifier.pk, source.name, source.id, len(images)))
    return msg


@task(name="Deploy")
def deploy(job_unit_id):
    """ Submits a deploy job. """
    try:
        job_unit = ApiJobUnit.objects.get(pk=job_unit_id)
    except ApiJobUnit.DoesNotExist:
        logger.info("Job unit of id {} does not exist.".format(job_unit_id))
        return

    job_unit.status = ApiJobUnit.IN_PROGRESS
    job_unit.save()

    # TODO: catch DoesNotExist here if pk is wrong? Or just let it fail?
    classifier = Classifier.objects.get(
        pk=job_unit.request_json['classifier_id'])

    storage = get_storage_class()()

    task = ClassifyImageMsg(
        job_token=th.encode_spacer_job_token([job_unit_id]),
        image_loc=DataLocation(
            storage_type='url',
            key=job_unit.request_json['url']
        ),
        feature_extractor_name=classifier.source.feature_extractor,
        rowcols=[(point['row'], point['column']) for point in
                 job_unit.request_json['points']],
        classifier_loc=storage.spacer_data_loc(
            settings.ROBOT_MODEL_FILE_PATTERN.format(pk=classifier.pk))
    )
    # Note the 'deploy' is called 'classify_image' in spacer.
    msg = JobMsg(task_name='classify_image', tasks=[task])

    # Submit.
    queue = get_queue_class()()
    queue.submit_job(msg)

    logger.info(u"Submitted image at url: {} for deploy with job unit {}.".
                format(job_unit.request_json['url'], job_unit.pk))

    return msg


@task(name="Classify Image")
def classify_image(image_id):
    """ Executes a classify_image job. """
    try:
        img = Image.objects.get(pk=image_id)
    except Image.DoesNotExist:
        logger.info("Image {} does not exist.".format(image_id))
        return

    if not img.features.extracted:
        return

    classifier = img.source.get_latest_robot()
    if not classifier:
        return

    # Create task message
    storage = get_storage_class()()
    msg = ClassifyFeaturesMsg(
        job_token=th.encode_spacer_job_token([image_id]),
        feature_loc=storage.spacer_data_loc(
            settings.FEATURE_VECTOR_FILE_PATTERN.format(
                full_image_path=img.original_file.name)),
        classifier_loc=storage.spacer_data_loc(
            settings.ROBOT_MODEL_FILE_PATTERN.format(pk=classifier.pk)
        )
    )

    # Process job right here since it is so fast.
    # In spacer, this task is called classify_features since that
    # is actually what we are doing (the feature are already extracted).
    res: ClassifyReturnMsg = spacer_classify_features(msg)

    # Pre-fetch label objects
    label_objs = [Label.objects.get(pk=pk) for pk in res.classes]

    # Add annotations if image isn't already confirmed    
    if not img.confirmed:
        try:
            th.add_annotations(image_id, res, label_objs, classifier)
        except IntegrityError:
            logger_message = \
                u"Failed to classify Image {} [Source: {} [{}] with " \
                u"classifier {}. There might have been a race condition " \
                u"when trying to save annotations. Will try again later."
            logger.info(logger_message.format(img.id, img.source,
                                              img.source_id, classifier.id))
            classify_image.apply_async(args=[image_id],
                                       eta=now() + timedelta(seconds=10))
            return

    # Always add scores
    th.add_scores(image_id, res, label_objs)

    img.features.classified = True
    img.features.save()

    logger.info(u"Classified Image {} [Source: {} [{}]] with classifier {}".
                format(img.id, img.source, img.source_id, classifier.id))


@periodic_task(run_every=timedelta(seconds=60), name='Collect all jobs',
               ignore_result=True)
def collect_all_jobs():
    """Collects and handles job results until the job result queue is empty."""

    logger.info('Collecting all jobs in result queue.')
    queue = get_queue_class()()
    while True:
        job_res = queue.collect_job()
        if job_res:
            _handle_job_result(job_res)
        else:
            break
    logger.info('Done collecting all jobs in result queue.')


def _handle_job_result(job_res: JobReturnMsg):
    """Handles the job results found in queue. """

    if not job_res.ok:
        logger.error("Job failed: {}".format(job_res.error_message))
        mail_admins("Spacer job failed", repr(job_res))
        if job_res.original_job.task_name == 'classify_image':
            th.deploy_fail(job_res)
        return

    task_name = job_res.original_job.task_name

    for task, res in zip(job_res.original_job.tasks,
                         job_res.results):
        pk = th.decode_spacer_job_token(task.job_token)[0]
        if task_name == 'extract_features':
            if th.featurecollector(task, res):
                # If job was entered into DB, submit a classify job.
                classify_image.apply_async(args=[pk],
                                           eta=now() + timedelta(seconds=10))

        elif task_name == 'train_classifier':
            if th.classifiercollector(task, res):
                # If successful, submit a classify job for all imgs in source.
                classifier = Classifier.objects.get(pk=pk)
                for image in Image.objects.filter(source=classifier.source,
                                                  features__extracted=True,
                                                  confirmed=False):
                    classify_image.apply_async(
                        args=[image.id],
                        eta=now() + timedelta(seconds=10))
        elif job_res.original_job.task_name == 'classify_image':
            th.deploycollector(task, res)

        else:
            logger.error('Job task type {} not recognized'.format(task_name))

        # Conclude
        logger.info("Collected job: {} with pk: {}".format(task_name, pk))


@task(name="Reset Source")
def reset_after_labelset_change(source_id):
    """The removes ALL TRACES of the vision backend for this source, including:
    1) Delete all Score objects for all images
    2) Delete Classifier objects
    3) Sets all image.features.classified = False
    """
    Score.objects.filter(source_id=source_id).delete()
    Classifier.objects.filter(source_id=source_id).delete()
    Annotation.objects.filter(source_id=source_id,
                              user=get_robot_user()).delete()
    for image in Image.objects.filter(source_id=source_id):
        image.features.classified = False
        image.features.save()

    # Finally, let's train a new classifier.
    submit_classifier.apply_async(args=[source_id],
                                  eta=now() + timedelta(seconds=10))


@task(name="Reset Features")
def reset_features(image_id):
    """Resets features for image. Call this after any change that affects the image
    point locations. E.g:
    Re-generate point locations.
    Change annotation area.
    Add new poits.
    """

    try:
        img = Image.objects.get(pk=image_id)
    except Image.DoesNotExist:
        logger.info("Image {} deleted. Nothing to reset.".format(image_id))
        return

    features = img.features
    features.extracted = False
    features.classified = False
    features.save()

    # Re-submit feature extraction.
    submit_features.apply_async(args=[img.id],
                                eta=now() + timedelta(seconds=10))


@periodic_task(
    run_every=timedelta(days=1),
    name="Clean up old Batch jobs",
    ignore_result=True,
)
def clean_up_old_batch_jobs():
    thirty_days_ago = timezone.now() - timedelta(days=30)
    for job in BatchJob.objects.filter(create_date__lt=thirty_days_ago):
        job.delete()
        mail_admins("Job {} not completed after 30 days.".format(
            job.batch_token), str(job))
