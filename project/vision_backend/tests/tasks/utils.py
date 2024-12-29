from django.conf import settings
from django.core.files.storage import default_storage
from django.test import override_settings

from annotations.tests.utils import UploadAnnotationsCsvTestMixin
from images.model_utils import PointGen
from jobs.models import Job
from jobs.tests.utils import do_job, JobUtilsMixin
from jobs.utils import abort_job
from lib.tests.utils import ClientTest
from ...models import Classifier


def do_collect_spacer_jobs():
    return do_job('collect_spacer_jobs')


def source_check_is_scheduled(source_id):
    try:
        Job.objects.get(
            job_name='check_source',
            source_id=source_id,
            status=Job.Status.PENDING,
        )
    except Job.DoesNotExist:
        return False
    return True


def ensure_source_check_not_scheduled(source_id):
    try:
        job = Job.objects.get(
            job_name='check_source',
            source_id=source_id,
            status=Job.Status.PENDING,
        )
    except Job.DoesNotExist:
        pass
    else:
        abort_job(job.pk)


@override_settings(
    SPACER_QUEUE_CHOICE='vision_backend.queues.LocalQueue',
    # Sometimes it helps to run certain periodic jobs (particularly
    # collect_spacer_jobs) only when we explicitly want to.
    ENABLE_PERIODIC_JOBS=False,
)
class BaseTaskTest(ClientTest, UploadAnnotationsCsvTestMixin, JobUtilsMixin):
    """Base test class for testing the backend's 'main' tasks."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user,
            default_point_generation_method=dict(type='simple', points=5))
        cls.labels = cls.create_labels(cls.user, ['A', 'B', 'C'], "Group1")
        cls.create_labelset(cls.user, cls.source, cls.labels)

    def setUp(self):
        super().setUp()
        self.source.refresh_from_db()

    def assertExistsInStorage(self, filepath):
        self.assertTrue(default_storage.exists(filepath))

    def source_check_and_assert(
        self,
        expected_message,
        expected_hidden: bool = None,
        assert_msg="Job result message should be as expected",
        source=None,
    ):
        source = source or self.source

        do_job('check_source', source.pk, source_id=source.pk)
        self.assert_job_result_message(
            'check_source', expected_message, assert_msg=assert_msg)

        if expected_hidden is not None:
            job = self.get_latest_job_by_name('check_source')
            self.assertEqual(
                job.hidden, expected_hidden,
                msg=f"Hidden value should be {expected_hidden}")

    @classmethod
    def upload_image_with_annotations(
        cls, filename,
        source=None, annotation_scheme='cycle', label_codes=None,
    ):
        source = source or cls.source
        img = cls.upload_image(
            cls.user, source, image_options=dict(filename=filename))
        label_codes = label_codes or ['A', 'B']

        match annotation_scheme:
            case 'cycle':
                # As long as there are at least 2 points per image, this will
                # ensure the data has at least 2 unique labels.
                annotations = {
                    num: label_codes[num % len(label_codes)]
                    for num in range(1, img.point_set.count()+1)
                }
            case code if code in label_codes:
                # All the same label.
                annotations = {
                    num: code
                    for num in range(1, img.point_set.count()+1)
                }
            case _:
                assert False, "label_choices should be a valid option"

        cls.add_annotations(cls.user, img, annotations)
        return img

    @classmethod
    def upload_images_for_training(
        cls, source=None, train_image_count=None, val_image_count=1,
        annotation_scheme='cycle', label_codes=None,
    ):
        source = source or cls.source

        if train_image_count is None:
            # Provide enough data for initial training
            train_image_count = settings.TRAINING_MIN_IMAGES

        train_images = []
        val_images = []

        for _ in range(train_image_count):
            train_images.append(
                cls.upload_image_with_annotations(
                    'train{}.png'.format(cls.image_count),
                    source=source,
                    annotation_scheme=annotation_scheme,
                    label_codes=label_codes,
                )
            )
        for _ in range(val_image_count):
            val_images.append(
                cls.upload_image_with_annotations(
                    'val{}.png'.format(cls.image_count),
                    source=source,
                    annotation_scheme=annotation_scheme,
                    label_codes=label_codes,
                )
            )

        return train_images, val_images

    @classmethod
    def upload_data_and_train_classifier(
        cls, source=None, new_train_images_count=None,
    ):
        source = source or cls.source
        train_images, val_images = cls.upload_images_for_training(
            source=source,
            train_image_count=new_train_images_count,
            val_image_count=1,
        )
        # Extract features
        # In most cases, run_scheduled_jobs_until_empty() would be equivalent
        # to these do_job() calls, but sometimes it's useful to make sure no
        # other job runs in the meantime.
        for image in [*train_images, *val_images]:
            do_job('extract_features', image.pk, source_id=source.pk)
        do_collect_spacer_jobs()
        # Train classifier
        job = do_job(
            'train_classifier', source.pk, source_id=source.pk)
        do_collect_spacer_jobs()

        return Classifier.objects.get(train_job_id=job.pk)

    @classmethod
    def upload_image_for_classification(cls, source=None):
        source = source or cls.source

        # Image without annotations
        image = cls.upload_image(cls.user, source)
        # Extract features
        do_job('extract_features', image.pk, source_id=source.pk)
        do_collect_spacer_jobs()

        image.refresh_from_db()
        return image

    @classmethod
    def upload_image_and_machine_classify(cls, source=None):
        source = source or cls.source

        # Image without annotations, with features extracted
        image = cls.upload_image_for_classification(source=source)
        # Classify image (assumes there's already a classifier)
        do_job('classify_features', image.pk, source_id=source.pk)

        image.refresh_from_db()
        return image

    def upload_image_with_dupe_points(self, filename, with_labels=False):
        img = self.upload_image(
            self.user, self.source, image_options=dict(filename=filename))

        # Upload points, including a duplicate.
        if with_labels:
            rows = [
                ['Name', 'Row', 'Column', 'Label'],
                [filename, 50, 50, 'A'],
                [filename, 40, 60, 'B'],
                [filename, 50, 50, 'A'],
            ]
        else:
            rows = [
                ['Name', 'Row', 'Column'],
                [filename, 50, 50],
                [filename, 40, 60],
                [filename, 50, 50],
            ]
        csv_file = self.make_annotations_file('A.csv', rows)
        self.preview_annotations(
            self.user, self.source, csv_file)
        self.upload_annotations(self.user, self.source)

        img.refresh_from_db()
        self.assertEqual(
            PointGen(type='imported', points=3).db_value,
            img.point_generation_method,
            "Points should be saved successfully")

        return img

    rowcols_with_dupes_included = [(40, 60), (50, 50), (50, 50)]
