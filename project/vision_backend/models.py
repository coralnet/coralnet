from collections import Counter

from django.conf import settings
from django.core.files.storage import default_storage
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse
from spacer.data_classes import DataLocation, ImageFeatures, ValResults

from events.models import Event
from images.models import Image, Point
from labels.models import Label, LocalLabel
from lib.utils import date_display
from sources.models import Source
from .common import ClassifierStatuses, Extractors, SourceExtractorChoices


class Classifier(models.Model):
    """
    Computer vision classifier.
    """

    # Source this classifier belongs to and is trained on.
    source = models.ForeignKey(Source, on_delete=models.CASCADE)

    # Training status of the classifier.
    status = models.CharField(
        max_length=2, choices=ClassifierStatuses.choices, default=ClassifierStatuses.TRAIN_PENDING.value)

    # Training runtime in seconds.
    runtime_train = models.BigIntegerField(default=0)

    # Accuracy as evaluated on the validation set
    accuracy = models.FloatField(null=True)

    # Epoch reference set accuracy (for bookkeeping mostly)
    epoch_ref_accuracy = models.CharField(max_length=512, null=True)

    # Number of image (val + train) that were used to train this classifier
    nbr_train_images = models.IntegerField(null=True)

    # Create date
    create_date = models.DateTimeField('Date created', auto_now_add=True,
                                       editable=False)
    
    @property
    def valres(self) -> ValResults:
        valres_loc: DataLocation = default_storage.spacer_data_loc(
            settings.ROBOT_MODEL_VALRESULT_PATTERN.format(pk=self.pk))

        return ValResults.load(valres_loc)

    def get_train_job(self):
        from jobs.models import Job
        try:
            return self.job_set.get(job_name='train_classifier')
        except Job.DoesNotExist:
            # Most likely this classifier was trained before the introduction
            # of the Job model.
            return None

    @property
    def train_completion_date(self):
        train_job = self.get_train_job()
        if train_job:
            # The date the train job's status was updated to success/failure.
            return train_job.modify_date
        else:
            # Use the Classifier's create date as a less-accurate fallback.
            return self.create_date

    def get_process_date_short_str(self):
        """
        Return the image's (pre)process date in YYYY-MM-DD format.

        Advantage over YYYY-(M)M-(D)D: alphabetized = sorted by date
        Advantage over YYYY(M)M(D)D: date is unambiguous
        """
        return "{0}-{1:02}-{2:02}".format(self.create_date.year,
                                          self.create_date.month,
                                          self.create_date.day)

    def __str__(self):
        """
        To-string method.
        """
        return (
            f"Classifier {self.pk}"
            f" [Source: {self.source} [{self.source.pk}]]")


class Features(models.Model):
    """
    This class manages the bookkeeping of features for each image.

    Most fields are nullable for the case where `extracted` is False.
    """
    image = models.OneToOneField(Image, on_delete=models.CASCADE)

    # Indicates whether the features are extracted. Set when jobs are collected
    extracted = models.BooleanField(default=False)

    # Which extractor was used. Typically, this matches the extractor setting
    # of the classifier's source; but after any interim period where there's
    # no designated classifier, the extractor used may be non-obvious.
    extractor = models.CharField(
        max_length=50, choices=Extractors.choices, blank=True, default='')

    # Total runtime for job
    runtime_total = models.IntegerField(null=True)

    # Whether the stored ImageFeatures structure has row/column information
    # (added around pyspacer PR #5).
    # Loading this info from S3 is slow, so this field is for quicker access.
    has_rowcols = models.BooleanField(null=True)

    # Whether the extractor needed to be downloaded from S3
    extractor_loaded_remotely = models.BooleanField(null=True)

    # When were the features extracted
    extracted_date = models.DateTimeField(null=True)

    @property
    def data_loc(self) -> DataLocation:
        return default_storage.spacer_data_loc(
            settings.FEATURE_VECTOR_FILE_PATTERN.format(
                full_image_path=self.image.original_file.name))

    def load(self) -> ImageFeatures:
        return ImageFeatures.load(self.data_loc)


class Score(models.Model):
    """
    Tracks scores for each point in each image. For each point,
    scores for only the top NBR_SCORES_PER_ANNOTATION labels are saved.
    """
    label = models.ForeignKey(Label, on_delete=models.CASCADE)
    point = models.ForeignKey(Point, on_delete=models.CASCADE)
    source = models.ForeignKey(Source, on_delete=models.CASCADE)
    image = models.ForeignKey(Image, on_delete=models.CASCADE)

    # Integer between 0 and 99, representing the percent probability
    # that this point is this label according to the backend. Although
    # scores are only saved for the top NBR_SCORES_PER_ANNOTATION labels,
    # this is the probability among all labels in the labelset.
    score = models.IntegerField(default=0)

    @property
    def label_code(self):
        local_label = LocalLabel.objects.get(
            global_label=self.label, labelset=self.source.labelset)
        return local_label.code

    def __str__(self):
        return "%s - %s - %s - %s" % (
            self.image, self.point.point_number, self.label_code, self.score)


class SourceClassifierOptions(models.Model):

    source = models.OneToOneField(
        Source, on_delete=models.CASCADE, related_name='classifier_options')

    confidence_threshold = models.IntegerField(
        "Confidence threshold (%)",
        validators=[MinValueValidator(0),
                    MaxValueValidator(100)],
        default=100,
    )

    trains_own_classifiers = models.BooleanField(
        "Source trains its own classifiers",
        default=True,
    )
    # Classifier selected for classification in this source. May be from
    # another source.
    deployed_classifier = models.ForeignKey(
        Classifier,
        # This field should not place any restrictions on the other source's
        # ability to manage its classifiers. So, for example, this shouldn't
        # be PROTECT.
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='deploying_sources',
    )
    # In case the selected classifier gets deleted, this is a 'backup' pointer
    # to the source that the classifier was from.
    # This is a BigIntegerField instead of a ForeignKey because:
    # 1) This way, if the selected-classifier's source also gets deleted,
    #    this field remains populated; thus we can still distinguish that
    #    situation vs. intentionally not selecting a classifier.
    # 2) This way we don't worry about any complexities regarding
    #    self-referential FKs.
    # 3) This is just a backup pointer. Generally,
    #    `deployed_classifier__source` can be used to get the same
    #    relationship.
    #
    # Since this is a redundant field, we automatically set it in save().
    deployed_source_id = models.BigIntegerField(
        null=True, blank=True,
    )

    feature_extractor_setting = models.CharField(
        "Feature extractor",
        max_length=50,
        choices=SourceExtractorChoices.choices,
        default=SourceExtractorChoices.EFFICIENTNET.value)

    @property
    def feature_extractor(self) -> str | None:
        if not self.trains_own_classifiers and not self.deployed_classifier:
            # We consider this source to have no feature extraction config.
            return None

        if settings.FORCE_DUMMY_EXTRACTOR:
            # Use dummy extractor for tests.
            # The real extractors are relatively slow.
            return 'dummy'

        if self.trains_own_classifiers:
            # Read feature extractor name from this source's field.
            return self.feature_extractor_setting

        # Else, using deployed_classifier.
        # Read feature extractor name from the classifier's source's field.
        return (
            self.deployed_classifier.source
            .classifier_options.feature_extractor_setting
        )

    def get_deployed_classifier_html(self):

        if self.deployed_classifier:

            if self.deployed_classifier.source.pk == self.source.pk:
                deployed_source = self.source
                html = (
                    f"{self.deployed_classifier.pk},"
                    f" from this source")
            else:
                deployed_source = self.deployed_classifier.source
                deployed_source_link = reverse(
                    'source_main', args=[deployed_source.pk])

                html = (
                    f'{self.deployed_classifier.pk}, from'
                    f' <a href="{deployed_source_link}" target="_blank">'
                    f'{deployed_source.name}</a>'
                )

            date = date_display(
                self.deployed_classifier.train_completion_date)
            html += f", trained {date}"

            last_accepted = deployed_source.last_accepted_classifier
            if last_accepted.pk != self.deployed_classifier.pk:
                date = date_display(last_accepted.train_completion_date)
                html += f" (latest: {last_accepted.pk}, trained {date})"

            return html

        if self.deployed_source_id:

            if self.deployed_source_id == self.source.pk:
                return "None. Previously used a classifier from this source"

            try:
                deployed_source = Source.objects.get(
                    pk=self.deployed_source_id)
            except Source.DoesNotExist:
                return (
                    f"None. Previously used a classifier from source"
                    f" {self.deployed_source_id} (now deleted)"
                )

            deployed_source_link = reverse(
                'source_main', args=[deployed_source.pk])
            return (
                f'None. Previously used a classifier from'
                f' <a href="{deployed_source_link}" target="_blank">'
                f'{deployed_source.name}</a>'
            )

        return "None"


class ClassifyImageEvent(Event):
    """
    Machine classification of an image.

    Details example:
    {
        1: dict(label=28, result='added'),
        2: dict(label=12, result='updated'),
        3: dict(label=28, result='no change'),
    }
    """
    class Meta:
        proxy = True

    type_for_subclass = 'classify_image'
    required_id_fields = ['source_id', 'image_id', 'classifier_id']

    def annotation_history_entry(self, labelset_dict):
        from annotations.models import Annotation
        not_changed_code = (
            Annotation.objects.UpdateResultsCodes.NOT_CHANGED.value)

        point_events = []
        for point_number, detail in self.details.items():
            label_display = self.label_id_to_display(
                detail['label'], labelset_dict)
            if detail['result'] != not_changed_code:
                point_events.append(f"Point {point_number}: {label_display}")
        return dict(
            date=self.date,
            user=self.get_robot_display(self.classifier_id, self.date),
            events=point_events,
        )

    @property
    def summary_text(self):
        return (
            f"Image {self.image_id}"
            f" checked by classifier {self.classifier_id}"
        )

    @property
    def details_text(self, image_context=False):
        from images.models import Image

        if image_context:
            text = (
                f"Checked by classifier {self.classifier_id}"
                f"\n"
            )
        else:
            image = Image.objects.get(pk=self.image_id)
            text = (
                f"Image '{image.metadata.name}' (ID {self.image_id})"
                f" checked by classifier {self.classifier_id}"
                f"\n"
            )

        label_ids = set(
            [d['label'] for _, d in self.details.items()]
        )
        label_values = \
            Label.objects.filter(pk__in=label_ids).values('pk', 'name')
        label_ids_to_names = {
            vs['pk']: vs['name'] for vs in label_values
        }
        result_counter = Counter()

        for point_number, d in self.details.items():
            result = d['result']
            text += (
                f"\nPoint {point_number}"
                f" - {label_ids_to_names[d['label']]}"
                f" - {result}"
            )
            result_counter[result] += 1

        counter_line_items = []
        for result, count in result_counter.items():
            counter_line_items.append(f"{count} {result}")
        text += (
            "\n"
            "\nSummary: " + ", ".join(counter_line_items)
        )

        return text


class SourceCheckRequestEvent(Event):
    class Meta:
        proxy = True

    type_for_subclass = 'source_check_request'
    required_id_fields = ['source_id']
