from collections import Counter
import datetime
from datetime import timedelta
from logging import getLogger
import random

from django.conf import settings
from django.core.files.storage import get_storage_class
from django.db import IntegrityError
from django.db.models import F
from django.utils import timezone
from spacer.exceptions import TrainingLabelsError
from spacer.messages import (
    ClassifyFeaturesMsg,
    ClassifyImageMsg,
    ClassifyReturnMsg,
    DataLocation,
    ExtractFeaturesMsg,
    JobMsg,
    TrainClassifierMsg,
    TrainingTaskLabels,
)
from spacer.tasks import classify_features as spacer_classify_features
from spacer.task_utils import preprocess_labels

from annotations.models import Annotation
from api_core.models import ApiJobUnit
from config.constants import SpacerJobSpec
from events.models import ClassifyImageEvent
from images.models import Source, Image, Point
from jobs.exceptions import JobError
from jobs.models import Job
from jobs.utils import job_runner, job_starter, queue_job
from labels.models import Label
from . import task_helpers as th
from .common import CLASSIFIER_MAPPINGS
from .exceptions import RowColumnMismatchError
from .models import Classifier, Score
from .queues import get_queue_class
from .utils import get_extractor, queue_source_check, reset_features

logger = getLogger(__name__)


# Run daily, and not at prime times of biggest users (e.g. US East, Hawaii,
# Australia).
@job_runner(
    interval=timedelta(days=1),
    offset=datetime.datetime(
        year=2023, month=1, day=1, hour=7, minute=0,
        tzinfo=datetime.timezone.utc,
    ),
)
def check_all_sources():
    queued = 0
    for source in Source.objects.all():
        # Queue a check of this source at a random time in the next 4 hours.
        delay_in_seconds = random.randrange(1, 60*60*4)
        job = queue_source_check(
            source.pk, delay=timedelta(seconds=delay_in_seconds))
        if job:
            queued += 1
    return f"Queued checks for {queued} source(s)"


@job_runner()
def check_source(source_id):
    """
    Check a source for appropriate vision-backend tasks to run,
    and run those tasks.
    """
    try:
        source = Source.objects.get(pk=source_id)
    except Source.DoesNotExist:
        raise JobError(f"Can't find source {source_id}")

    start = timezone.now()
    wrap_up_time = start + timedelta(minutes=settings.JOB_MAX_MINUTES)
    timed_out = False

    done_caveat = None

    # Feature extraction

    not_extracted = source.image_set.without_features()
    not_extracted = not_extracted.annotate(
        num_pixels=F('original_width') * F('original_height'))
    cant_extract = not_extracted.filter(
        num_pixels__gt=settings.SPACER['MAX_IMAGE_PIXELS'])
    to_extract = not_extracted.difference(cant_extract)

    if to_extract.exists():
        active_training_jobs = Job.objects.filter(
            job_name='train_classifier',
            source_id=source_id,
            status__in=[Job.Status.PENDING, Job.Status.IN_PROGRESS]
        )
        if active_training_jobs.exists():
            # If we submit, rowcols that were submitted to training may get
            # out of sync with features in S3.
            # The potentially dangerous sequence is like:
            #
            # 1) submit training to spacer with old point set
            # 2) upload new point set for training images
            # 3) as a result of the upload, submit associated feature
            # extractions to spacer
            # 4) spacer runs feature extractions, replacing old feature
            # files with new feature files
            # 5) spacer runs training with old point set + new feature files.
            #
            # So, we prevent 3) from being able to happen.
            return (
                f"Feature extraction(s) ready, but not"
                f" submitted due to training in progress")

        active_extraction_jobs = Job.objects.filter(
            job_name='extract_features',
            source_id=source_id,
            status__in=[Job.Status.PENDING, Job.Status.IN_PROGRESS]
        )
        active_extraction_image_ids = set([
            int(str_id) for str_id in
            active_extraction_jobs.values_list('arg_identifier', flat=True)
        ])

        # Try to queue extractions (will not be queued if an extraction for
        # the same image is already active)
        num_queued_extractions = 0
        for image in to_extract:
            if image.pk in active_extraction_image_ids:
                # Very quick short-circuit without additional DB check.
                continue

            # This hits the DB to check for a race condition (identical
            # active job), then to create a job as appropriate.
            job = queue_job('extract_features', image.pk, source_id=source_id)
            if not job:
                continue

            num_queued_extractions += 1

            if (
                num_queued_extractions % 10 == 0
                and timezone.now() > wrap_up_time
            ):
                timed_out = True
                break

        # If there are extractions to be done, then having that overlap with
        # training can lead to desynced rowcols, so we return and worry about
        # training later.
        if num_queued_extractions > 0:
            result_str = (
                f"Queued {num_queued_extractions} feature extraction(s)")
            if timed_out:
                result_str += " (timed out)"
            return result_str
        else:
            return "Waiting for feature extraction(s) to finish"

    if cant_extract.exists():
        done_caveat = (
            f"At least one image has too large of a resolution to extract"
            f" features (example: image ID {cant_extract[0].pk}).")

    # Classifier training

    need_new_robot, reason = source.need_new_robot()
    if need_new_robot:
        # Try to queue training
        job = queue_job('train_classifier', source_id, source_id=source_id)
        # We return and don't worry about classification until the classifier
        # is up to date.
        if job:
            return "Queued training"
        else:
            return "Waiting for training to finish"

    # Image classification

    if not source.has_robot():
        return f"Can't train first classifier: {reason}"

    classifiable_images = source.image_set.incomplete().with_features()
    unclassified_images = classifiable_images.unclassified()

    # Here we detect whether the current classifier has been used for ANY
    # classifications so far. We check this because, most of the time,
    # the current classifier has either taken a pass on ALL classifiable
    # images, or it hasn't run at all yet.
    #
    # Checking the events should work for any classifications that happened
    # after such events were introduced (CoralNet 1.7). Otherwise, we look
    # for annotations attributed to the current classifier, but that can
    # miss cases where the current classifier agreed with the previous
    # classifier on all points.
    current_classifier = source.get_current_classifier()
    current_classifier_events = ClassifyImageEvent.objects \
        .filter(classifier_id=current_classifier.pk, source_id=source_id)
    current_classifier_annotations = source.annotation_set \
        .filter(robot_version=current_classifier)
    current_classifier_used = current_classifier_events.exists() \
        or current_classifier_annotations.exists()

    if current_classifier_used:
        # Has been used; so most likely the only images to look at are the
        # unclassified ones.
        images_to_classify = unclassified_images
    else:
        # Hasn't been used; so the classifier needs to run on everything.
        images_to_classify = classifiable_images

    if images_to_classify.exists():

        active_classify_jobs = Job.objects.filter(
            job_name='classify_features',
            source_id=source_id,
            status__in=[Job.Status.PENDING, Job.Status.IN_PROGRESS]
        )
        active_classify_image_ids = set([
            int(str_id) for str_id in
            active_classify_jobs.values_list('arg_identifier', flat=True)
        ])

        # Try to queue classifications
        num_queued_classifications = 0
        for image in images_to_classify:
            if image.pk in active_classify_image_ids:
                # Very quick short-circuit without additional DB check.
                continue

            job = queue_job('classify_features', image.pk, source_id=source_id)
            if not job:
                continue

            num_queued_classifications += 1

            if (
                num_queued_classifications % 10 == 0
                and timezone.now() > wrap_up_time
            ):
                timed_out = True
                break

        if num_queued_classifications > 0:
            result_str = (
                f"Queued {num_queued_classifications} image classification(s)")
            if timed_out:
                result_str += " (timed out)"
            return result_str
        else:
            return "Waiting for image classification(s) to finish"

    # If we got here, then the source should be all caught up, and there's
    # no need to queue another check for now. However, there may be a caveat
    # to the 'caught up' status.
    if done_caveat:
        return (
            f"{done_caveat} Otherwise, the source seems to be all caught up."
            f" {reason}")
    return f"Source seems to be all caught up. {reason}"


def job_spec_for_extract(image) -> SpacerJobSpec:
    """
    Specs required for feature extraction. Higher resolution images seem
    to need more memory.
    """
    pixels = image.original_width * image.original_height
    for job_spec, threshold in settings.FEATURE_EXTRACT_SPEC_PIXELS:
        if pixels >= threshold:
            return job_spec


@job_starter(job_name='extract_features')
def submit_features(image_id, job_id):
    """ Submits a feature extraction job. """
    try:
        img = Image.objects.get(pk=image_id)
    except Image.DoesNotExist:
        raise JobError(f"Image {image_id} does not exist.")

    # Setup the job payload.
    storage = get_storage_class()()

    # Assemble row column information
    rowcols = [(p.row, p.column) for p in Point.objects.filter(image=img)]

    # Assemble task.
    task = ExtractFeaturesMsg(
        job_token=str(job_id),
        extractor=get_extractor(img.source.feature_extractor),
        rowcols=rowcols,
        image_loc=storage.spacer_data_loc(img.original_file.name),
        feature_loc=storage.spacer_data_loc(
            settings.FEATURE_VECTOR_FILE_PATTERN.format(
                full_image_path=img.original_file.name))
    )

    msg = JobMsg(task_name='extract_features', tasks=[task])

    # Submit.
    queue = get_queue_class()()
    queue.submit_job(msg, job_id, job_spec_for_extract(img))

    return msg


@job_starter(job_name='train_classifier')
def submit_classifier(source_id, job_id):
    """ Submits a classifier training job. """

    # We know the Source exists since we got past the job_starter decorator,
    # and deleting the Source would've cascade-deleted the Job.
    source = Source.objects.get(pk=source_id)

    images = source.image_set.confirmed().with_features().order_by('pk')

    without_feature_rowcols = images.filter(features__has_rowcols=False)
    if without_feature_rowcols.exists():
        count = without_feature_rowcols.count()
        for image in without_feature_rowcols:
            reset_features(image)
        raise JobError(
            f"This source has {count} feature vector(s) without"
            f" rows/columns, and this is no longer accepted for training."
            f" Feature extractions will be redone to fix this.")

    # Create new classifier
    classifier = Classifier(
        source=source, train_job_id=job_id, nbr_train_images=len(images))
    classifier.save()

    # Create training datasets.
    # The train+ref vs. val split is defined in advance, while the
    # train vs. ref split is determined here with mod-10. This matches
    # how it's worked since coralnet 1.0.
    train_and_ref_images = [image for image in images if image.trainset]
    train_images = []
    ref_images = []
    ref_annotation_count = 0
    ref_done = False
    for image_index, image in enumerate(train_and_ref_images):
        if not ref_done and image_index % 10 == 0:
            image_annotation_count = image.annotation_set.count()
            if (ref_annotation_count + image_annotation_count
                    <= settings.TRAINING_BATCH_LABEL_COUNT):
                ref_images.append(image)
                ref_annotation_count += image_annotation_count
            else:
                train_images.append(image)
                ref_done = True
        else:
            train_images.append(image)

    labels = TrainingTaskLabels(
        train=th.make_dataset(train_images),
        ref=th.make_dataset(ref_images),
        val=th.make_dataset([image for image in images if image.valset]),
    )
    try:
        labels = preprocess_labels(labels)
    except TrainingLabelsError:
        # After preprocessing, we either ended up with only 0 or 1 unique
        # label(s), or train/ref/val set ended up empty.
        # There's a bit of "luck" involved with what ends up in train/ref/val,
        # but generally this means that there weren't enough annotations of
        # at least 2 different labels.
        #
        # We can get stuck in an error loop if we proceed to submit training
        # (see issue #412), so we don't submit training.
        classifier.status = Classifier.LACKING_UNIQUE_LABELS
        classifier.save()
        raise JobError(
            f"{classifier} was declined training, because there weren't enough"
            f" annotations of at least 2 different labels.")

    # This will not include the one we just created, b/c status isn't accepted.
    prev_classifiers = source.get_accepted_robots()

    # Create TrainClassifierMsg
    storage = get_storage_class()()
    task = TrainClassifierMsg(
        job_token=str(job_id),
        trainer_name='minibatch',
        nbr_epochs=settings.NBR_TRAINING_EPOCHS,
        clf_type=CLASSIFIER_MAPPINGS[source.feature_extractor],
        labels=labels,
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

    # How big of a job is this; how many annotations? That will determine
    # runtime (and possibly memory) requirements of training.
    annotation_count = (
        labels.train.label_count
        + labels.ref.label_count
        + labels.val.label_count
    )
    job_spec = None
    for spec, threshold in settings.TRAIN_SPEC_ANNOTATIONS:
        if annotation_count >= threshold:
            job_spec = spec
            break

    # Submit.
    queue = get_queue_class()()
    queue.submit_job(msg, job_id, job_spec)

    return msg


@job_starter(job_name='classify_image')
def deploy(api_job_id, api_unit_order, job_id):
    """Begin classifying an image submitted through the deploy-API."""
    try:
        api_job_unit = ApiJobUnit.objects.get(
            parent_id=api_job_id, order_in_parent=api_unit_order)
    except ApiJobUnit.DoesNotExist:
        raise JobError(
            f"Job unit [{api_job_id} / {api_unit_order}] does not exist.")

    classifier_id = api_job_unit.request_json['classifier_id']
    try:
        classifier = Classifier.objects.get(pk=classifier_id)
    except Classifier.DoesNotExist:
        error_message = (
            f"Classifier of id {classifier_id} does not exist."
            f" Maybe it was deleted.")
        raise JobError(error_message)

    storage = get_storage_class()()

    task = ClassifyImageMsg(
        job_token=str(job_id),
        image_loc=DataLocation(
            storage_type='url',
            key=api_job_unit.request_json['url']
        ),
        extractor=get_extractor(classifier.source.feature_extractor),
        rowcols=[(point['row'], point['column']) for point in
                 api_job_unit.request_json['points']],
        classifier_loc=storage.spacer_data_loc(
            settings.ROBOT_MODEL_FILE_PATTERN.format(pk=classifier.pk))
    )
    # Note the 'deploy' is called 'classify_image' in spacer.
    msg = JobMsg(task_name='classify_image', tasks=[task])

    # Submit.
    queue = get_queue_class()()
    # We have no idea how big the image will be; hopefully medium spec
    # covers it.
    queue.submit_job(msg, job_id, SpacerJobSpec.MEDIUM)

    return msg


@job_runner(job_name='classify_features')
def classify_image(image_id):
    """Classify a source's image."""
    try:
        img = Image.objects.get(pk=image_id)
    except Image.DoesNotExist:
        raise JobError(f"Image {image_id} does not exist.")

    if not img.features.extracted:
        raise JobError(
            f"Image {image_id} needs to have features extracted"
            f" before being classified.")

    classifier = img.source.get_current_classifier()
    if not classifier:
        raise JobError(
            f"Image {image_id} can't be classified;"
            f" its source doesn't have a classifier.")

    # Create task message
    storage = get_storage_class()()
    msg = ClassifyFeaturesMsg(
        job_token=str(image_id),
        feature_loc=storage.spacer_data_loc(
            settings.FEATURE_VECTOR_FILE_PATTERN.format(
                full_image_path=img.original_file.name)),
        classifier_loc=storage.spacer_data_loc(
            settings.ROBOT_MODEL_FILE_PATTERN.format(pk=classifier.pk)
        )
    )

    # Process job right here since it is so fast.
    # In spacer, this task is called classify_features since that
    # is actually what we are doing (the features are already extracted).
    res: ClassifyReturnMsg = spacer_classify_features(msg)

    # Pre-fetch label objects
    label_objs = [Label.objects.get(pk=pk) for pk in res.classes]

    # Add annotations if image isn't already confirmed    
    if not img.annoinfo.confirmed:
        try:
            th.add_annotations(image_id, res, label_objs, classifier)
        except (IntegrityError, RowColumnMismatchError):
            raise JobError(
                f"Failed to save annotations for image {image_id}."
                f" Maybe there was another change happening at the same time"
                f" with the image's points/annotations."
            )

    # Always add scores
    try:
        th.add_scores(image_id, res, label_objs)
    except (IntegrityError, RowColumnMismatchError):
        # If we got here, then the annotations saved, so it might seem strange
        # to finish the job with an error. However, if we got here, then the
        # points also got regenerated, so the just-saved annotations got
        # deleted anyway.
        raise JobError(
            f"Failed to save scores for image {image_id}."
            f" Maybe there was another change happening at the same time"
            f" with the image's points."
        )

    current_classifier_events = ClassifyImageEvent.objects \
        .filter(classifier_id=classifier.pk, source_id=img.source_id)
    incomplete_images = img.source.image_set.incomplete()
    if current_classifier_events.count() >= incomplete_images.count():
        # Classification for this source may be done.
        # Confirm whether the source is all caught up. That's useful to know
        # when looking at job/backend dashboards.
        queue_source_check(img.source_id)

    return f"Used classifier {classifier.pk}"


@job_runner(interval=timedelta(minutes=1))
def collect_spacer_jobs():
    """
    Collects and handles spacer job results until A) the result queue is empty
    or B) the max job time has been reached.

    This task gets job-tracking to enforce that only one thread runs this
    task at a time. That way, no spacer job can get collected multiple times.
    """
    start = timezone.now()
    wrap_up_time = start + timedelta(minutes=settings.JOB_MAX_MINUTES)
    timed_out = False

    queue = get_queue_class()()
    job_statuses = []

    for job in queue.get_collectable_jobs():
        job_res, job_status = queue.collect_job(job)
        job_statuses.append(job_status)
        if job_res:
            th.handle_spacer_result(job_res)

        if timezone.now() > wrap_up_time:
            # As long as collect_jobs() is implemented with `yield`,
            # this loop-break won't abandon any job results.
            timed_out = True
            break

    status_counts = Counter(job_statuses)

    # sorted() sorts statuses alphabetically.
    counts_str = ', '.join([
        f'{count} {status}'
        for status, count in sorted(status_counts.items())
    ])
    result_str = f"Jobs checked/collected: {counts_str or '0'}"

    if timed_out:
        result_str += " (timed out)"
    return result_str


@job_runner()
def reset_backend_for_source(source_id):
    """
    Removes all traces of the backend for this source, including
    classifiers and features.
    """
    queue_job(
        'reset_classifiers_for_source', source_id,
        source_id=source_id)

    for image in Image.objects.filter(source_id=source_id):
        reset_features(image)


@job_runner()
def reset_classifiers_for_source(source_id):
    """
    Removes all traces of the classifiers for this source.
    """
    Score.objects.filter(source_id=source_id).delete()
    Classifier.objects.filter(source_id=source_id).delete()
    Annotation.objects.filter(source_id=source_id).unconfirmed().delete()

    # Can probably train a new classifier.
    queue_source_check(source_id)
