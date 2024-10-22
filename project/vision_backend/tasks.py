from collections import Counter
from datetime import timedelta
from logging import getLogger

from django.conf import settings
from django.core.files.storage import default_storage
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
from images.model_utils import PointGen
from images.models import Image, Point
from jobs.exceptions import JobError
from jobs.models import Job
from jobs.utils import job_runner, job_starter, schedule_job
from labels.models import Label
from sources.models import Source
from . import task_helpers as th
from .common import CLASSIFIER_MAPPINGS
from .exceptions import RowColumnMismatchError
from .models import Classifier, Score
from .queues import get_queue_class
from .utils import (
    get_extractor,
    reset_features,
    reset_features_bulk,
    schedule_source_check,
    source_is_finished_with_core_jobs,
)

logger = getLogger(__name__)


def after_check(job_id):
    job = Job.objects.get(pk=job_id)

    # On job lists, showing all source checks can be a lot. Hide the ones
    # that don't actually schedule anything.
    if not job.result_message.startswith("Scheduled"):
        job.hidden = True
        job.save()


@job_runner(after_finishing_job=after_check)
def check_source(source_id):
    """
    Check a source for appropriate vision-backend tasks to run,
    and run those tasks.
    """
    try:
        source = Source.objects.get(pk=source_id)
    except Source.DoesNotExist:
        raise JobError(f"Can't find source {source_id}")

    active_reset_jobs = source.job_set.incomplete().filter(
        job_name__in=['reset_classifiers_for_source',
                      'reset_features_for_source'],
    )
    if active_reset_jobs.exists():
        return "Waiting for reset job to finish"

    if source.feature_extractor is None:
        # None of the backend processes can happen without being able to
        # extract features.
        return "Machine classification isn't configured for this source"

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
        active_training_jobs = Job.objects.incomplete().filter(
            job_name='train_classifier',
            source_id=source_id,
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

        active_extraction_jobs = Job.objects.incomplete().filter(
            job_name='extract_features',
            source_id=source_id,
        )
        active_extraction_image_ids = set([
            int(str_id) for str_id in
            active_extraction_jobs.values_list('arg_identifier', flat=True)
        ])

        # Try to schedule extractions (will not be scheduled if an extraction
        # for the same image is already active)
        num_scheduled_extractions = 0
        for image in to_extract:
            if image.pk in active_extraction_image_ids:
                # Very quick short-circuit without additional DB check.
                continue

            job, created = schedule_job(
                'extract_features', image.pk, source_id=source_id)
            if not created:
                continue

            num_scheduled_extractions += 1

            if (
                num_scheduled_extractions % 10 == 0
                and timezone.now() > wrap_up_time
            ):
                timed_out = True
                break

        # If there are extractions to be done, then having that overlap with
        # training can lead to desynced rowcols, so we return and worry about
        # training later.
        if num_scheduled_extractions > 0:
            result_str = (
                f"Scheduled {num_scheduled_extractions} feature extraction(s)")
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

    ready_to_train, reason = source.ready_to_train()
    if ready_to_train:
        # Try to schedule training
        job, created = schedule_job(
            'train_classifier', source_id, source_id=source_id)
        # We return and don't worry about classification until the classifier
        # is up to date.
        if created:
            return "Scheduled training"
        else:
            return "Waiting for training to finish"

    # Image classification

    if not source.deployed_classifier:
        # Can't classify without a classifier.
        #
        # For the message, we know that we must be in train mode here. If we
        # were in use-existing-classifier mode, then we wouldn't have passed
        # the source.feature_extractor check earlier.
        return f"Can't train first classifier: {reason}"

    # The images we should classify are the images that...
    # - Have features extracted
    # - Are non-confirmed (incomplete) and classifier isn't the deployed
    #   classifier, OR, are unclassified (covering the case where the deployed
    #   classifier's annotations were deleted)
    extracted_images = source.image_set.with_features()
    images_to_classify = (
        extracted_images.incomplete().exclude(
            annoinfo__classifier=source.deployed_classifier)
        |
        extracted_images.unclassified()
    )

    if images_to_classify.exists():

        active_classify_jobs = Job.objects.incomplete().filter(
            job_name='classify_features',
            source_id=source_id,
        )
        active_classify_image_ids = set([
            int(str_id) for str_id in
            active_classify_jobs.values_list('arg_identifier', flat=True)
        ])

        num_scheduled_classifications = 0
        work_score = 0

        # Try to schedule classifications
        for vals in images_to_classify.values('id', 'point_generation_method'):
            image_id = vals['id']
            if image_id in active_classify_image_ids:
                # Very quick short-circuit without additional DB check.
                continue

            point_count = PointGen.from_db_value(
                vals['point_generation_method']).total_points
            # When measuring the amount of 'work' a classification is, say each
            # image has this base value, and add the point count to that.
            # (Based on a vague recollection of classification runtimes with
            # different point counts, recent changes since those recollections,
            # and accounting for general overhead of starting/finishing jobs.)
            image_base_value = 100
            work_score += image_base_value + point_count

            if work_score > settings.SOURCE_CLASSIFICATIONS_MAX_WORK:
                # That's enough for this source at the moment.
                # If we schedule too much classifications work at once, other
                # jobs may not get a chance to run for a while.
                break

            job, created = schedule_job(
                'classify_features', image_id, source_id=source_id)
            if not created:
                continue

            num_scheduled_classifications += 1

            if (
                num_scheduled_classifications % 10 == 0
                and timezone.now() > wrap_up_time
            ):
                timed_out = True
                break

        if num_scheduled_classifications > 0:
            result_str = (
                f"Scheduled {num_scheduled_classifications}"
                f" image classification(s)")
            if timed_out:
                result_str += " (timed out)"
            return result_str
        else:
            return "Waiting for image classification(s) to finish"

    # If we got here, then the source should be all caught up, and there's
    # no need to schedule another check for now. However, there may be a caveat
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

    if img.source.feature_extractor is None:
        raise JobError(f"No feature extractor configured for this source.")

    # Assemble row column information
    rowcols = [(p.row, p.column) for p in Point.objects.filter(image=img)]

    # Assemble task.
    task = ExtractFeaturesMsg(
        job_token=str(job_id),
        extractor=get_extractor(img.source.feature_extractor),
        rowcols=rowcols,
        image_loc=default_storage.spacer_data_loc(img.original_file.name),
        feature_loc=img.features.data_loc,
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

    if not source.trains_own_classifiers:
        raise JobError("Training is disabled for this source")

    images = source.image_set.confirmed().with_features().order_by('pk')

    without_feature_rowcols = images.filter(features__has_rowcols=False)
    if without_feature_rowcols.exists():
        count = without_feature_rowcols.count()
        reset_features_bulk(without_feature_rowcols)
        raise JobError(
            f"This source has {count} feature vector(s) without"
            f" rows/columns, and this is no longer accepted for training."
            f" Feature extractions will be redone to fix this.")

    in_wrong_feature_format = images.exclude(
        features__extractor=source.feature_extractor)
    if in_wrong_feature_format.exists():
        count = in_wrong_feature_format.count()
        reset_features_bulk(in_wrong_feature_format)
        raise JobError(
            f"This source has {count} feature vector(s) which don't match"
            f" the source's feature format."
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

    # Feature caching can greatly speed up training, but might make training
    # fail if the amount to cache approaches the available storage space.
    # If that's the case, disable caching.
    if labels.label_count > settings.FEATURE_CACHING_ANNOTATION_LIMIT:
        feature_cache_dir = TrainClassifierMsg.FeatureCache.DISABLED
    else:
        feature_cache_dir = TrainClassifierMsg.FeatureCache.AUTO

    # Create TrainClassifierMsg
    task = TrainClassifierMsg(
        job_token=str(job_id),
        trainer_name='minibatch',
        nbr_epochs=settings.NBR_TRAINING_EPOCHS,
        clf_type=CLASSIFIER_MAPPINGS[source.feature_extractor],
        labels=labels,
        features_loc=default_storage.spacer_data_loc(''),
        previous_model_locs=[default_storage.spacer_data_loc(
            settings.ROBOT_MODEL_FILE_PATTERN.format(pk=pc.pk))
            for pc in prev_classifiers],
        model_loc=default_storage.spacer_data_loc(
            settings.ROBOT_MODEL_FILE_PATTERN.format(pk=classifier.pk)),
        valresult_loc=default_storage.spacer_data_loc(
            settings.ROBOT_MODEL_VALRESULT_PATTERN.format(pk=classifier.pk)),
        feature_cache_dir=feature_cache_dir,
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


@job_starter(job_name='classify_image', job_display_name="Deploy")
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

    task = ClassifyImageMsg(
        job_token=str(job_id),
        image_loc=DataLocation(
            storage_type='url',
            key=api_job_unit.request_json['url']
        ),
        extractor=get_extractor(classifier.source.feature_extractor),
        rowcols=[(point['row'], point['column']) for point in
                 api_job_unit.request_json['points']],
        classifier_loc=default_storage.spacer_data_loc(
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


def after_classify_features(job_id):
    job = Job.objects.get(pk=job_id)
    source_id = job.source_id

    if source_is_finished_with_core_jobs(source_id):
        # There may be more classifications to schedule, if the previous
        # source check reached the limit for number of classifications.
        # Or, classification for this source may be done, in which case it's
        # useful to confirm whether the source is all caught up (can see the
        # confirmation message when looking at job/backend dashboards).
        #
        # Either way (especially the former case), use a delay so that other
        # jobs get a chance to run. Since most classifications run on the
        # web server, they can hog web server resources.
        schedule_source_check(source_id, delay=timedelta(minutes=10))


@job_runner(
    job_name='classify_features', job_display_name="Classify",
    after_finishing_job=after_classify_features,
)
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

    classifier = img.source.deployed_classifier
    if not classifier:
        raise JobError(
            f"Image {image_id} can't be classified;"
            f" its source doesn't have a classifier.")

    if img.features.extractor != img.source.feature_extractor:
        reset_features(img)
        raise JobError(
            "This image's features don't match the source's feature format."
            " Feature extraction will be redone to fix this.")

    # Create task message
    msg = ClassifyFeaturesMsg(
        job_token=str(image_id),
        feature_loc=img.features.data_loc,
        classifier_loc=default_storage.spacer_data_loc(
            settings.ROBOT_MODEL_FILE_PATTERN.format(pk=classifier.pk)
        )
    )

    # Process job right here since it is so fast.
    # In spacer, this task is called classify_features since that
    # is actually what we are doing (the features are already extracted).
    res: ClassifyReturnMsg = spacer_classify_features(msg)

    # Pre-fetch label objects
    label_objs = [Label.objects.get(pk=pk) for pk in res.classes]

    result_message = f"Used classifier {classifier.pk}"
    # Add annotations if image isn't already confirmed
    if not img.annoinfo.confirmed:
        try:
            annotation_summary = th.add_annotations(
                image_id, res, label_objs, classifier)
            result_message += f": {annotation_summary}"
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

    img.annoinfo.refresh_from_db()
    img.annoinfo.classifier = classifier
    img.annoinfo.save()

    return result_message


def after_collect(job_id):
    job = Job.objects.get(pk=job_id)
    if job.result_message == "Jobs checked/collected: 0":
        job.hidden = True
        job.save()


@job_runner(interval=timedelta(minutes=1), after_finishing_job=after_collect)
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


def reset_start_condition(job_id):
    job = Job.objects.get(pk=job_id)
    return source_is_finished_with_core_jobs(job.source_id)


@job_runner(
    atomic=True,
    start_condition=reset_start_condition)
def reset_features_for_source(source_id):
    """
    Clears all extracted features for this source.

    atomic=True because there is a schedule_source_check_on_commit()
    within here, which we want to run after this job finishes, so that the
    source check isn't stopped by this reset job still being active.
    """
    reset_features_bulk(Image.objects.filter(source_id=source_id))


def after_reset_classifiers(job_id):
    # Successful jobs related to classifier history should persist in the DB.
    job = Job.objects.get(pk=job_id)
    job.persist = True
    job.save()

    # Can probably train a new classifier. Also, it's possible that the
    # reset job made a previous source check get cut short.
    schedule_source_check(job.source_id)


@job_runner(
    start_condition=reset_start_condition,
    after_finishing_job=after_reset_classifiers)
def reset_classifiers_for_source(source_id):
    """
    Removes all traces of the classifiers for this source.
    """
    # Nobody has foreign keys to Scores, so this is one efficient query.
    Score.objects.filter(source_id=source_id).delete()

    # There are SET_NULL FKs to Annotations, so deletion would induce Django
    # to fetch all Annotations as part of implementing setting null. This could
    # run us out of memory with production amounts of Annotations, so we chunk
    # it.
    # We also use only() to reduce what's fetched.
    #
    # We do this before deleting Classifiers, since Annotations have FKs to
    # Classifiers, but not vice versa. So this order should reduce a bit of
    # work, and also makes more sense from a data consistency standpoint.
    annotations = (
        Annotation.objects.filter(source_id=source_id)
        .unconfirmed()
        .only('pk')
    )
    while True:
        chunk_pks = annotations[:settings.QUERYSET_CHUNK_SIZE].values('pk')
        if chunk_pks:
            Annotation.objects.filter(pk__in=chunk_pks).only('pk').delete()
        else:
            break

    # There are SET_NULL FKs to Classifiers, so this fetches all classifiers to
    # implement setting null. But that's okay since there aren't many
    # classifiers per source.
    Classifier.objects.filter(source_id=source_id).delete()
