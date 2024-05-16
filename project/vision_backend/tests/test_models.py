from datetime import datetime, timezone

from django_migration_testcase import MigrationTest
import numpy as np
from spacer.messages import ClassifyReturnMsg

from jobs.utils import schedule_job
from lib.tests.utils import ClientTest, sample_image_as_file
from images.models import Point
from ..common import Extractors
from ..models import BatchJob, Score
import vision_backend.task_helpers as th


class ImageInitialStatusTest(ClientTest):
    """
    Check a newly uploaded image's status (as relevant to the vision backend).
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

    def test_features_extracted_false(self):
        self.user = self.create_user()
        self.source = self.create_source(self.user)
        self.img1 = self.upload_image(self.user, self.source)
        self.assertFalse(self.img1.features.extracted)


class CascadeDeleteTest(ClientTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)
    
        labels = cls.create_labels(cls.user,
                                   ['A', 'B', 'C', 'D', 'E', 'F', 'G'],
                                   "Group1")

        cls.create_labelset(cls.user, cls.source, labels.filter(
            name__in=['A', 'B', 'C', 'D', 'E', 'F', 'G'])
        )

    def test_point_score_cascade(self):
        """
        If a point is deleted all scores for that point should be deleted.
        """
        img = self.upload_image(self.user, self.source)

        # Pre-fetch label objects
        label_objs = self.source.labelset.get_globals()

        # Check number of points per image
        nbr_points = Point.objects.filter(image=img).count()

        # Fake creation of scores.
        scores = []
        for i in range(nbr_points):
            scores.append(np.random.rand(label_objs.count()))

        return_msg = ClassifyReturnMsg(
            runtime=0.0,
            scores=[(0, 0, [float(s) for s in scrs]) for scrs in scores],
            classes=[label.pk for label in label_objs],
            valid_rowcol=False,
        )

        th.add_scores(img.pk, return_msg, label_objs)

        expected_nbr_scores = min(5, label_objs.count())
        self.assertEqual(Score.objects.filter(image=img).count(),
                         nbr_points * expected_nbr_scores)
        
        # remove one point
        points = Point.objects.filter(image=img)
        points[0].delete()

        # Now all scores for that point should be gone.
        self.assertEqual(Score.objects.filter(image=img).count(),
                         (nbr_points - 1) * expected_nbr_scores)

    def test_job_batchjob_cascade(self):
        """
        BatchJobs should be deleted when their corresponding Jobs are
        deleted.
        """
        job, _ = schedule_job('test')

        batch_job = BatchJob(internal_job=job)
        batch_job.save()
        batch_job_id = batch_job.pk

        job.delete()

        with self.assertRaises(
            BatchJob.DoesNotExist, msg="batch_job should be gone"
        ):
            BatchJob.objects.get(pk=batch_job_id)


class PopulateClassifierStatusTest(MigrationTest):

    app_name = 'vision_backend'
    before = '0002_classifier_status'
    after = '0003_populate_classifier_status'

    def test_migration(self):
        Source = self.get_model_before('images.Source')
        Classifier = self.get_model_before('vision_backend.Classifier')

        source = Source(name="Test source")
        source.save()
        classifier_accepted = Classifier(
            source=source, valid=True, accuracy=0.50)
        classifier_accepted.save()
        classifier_rejected = Classifier(
            source=source, valid=False, accuracy=0.50)
        classifier_rejected.save()
        classifier_error = Classifier(
            source=source, valid=False)
        classifier_error.save()

        self.run_migration()

        # Statuses should be populated based on the other fields
        classifier_accepted.refresh_from_db()
        self.assertEqual(
            classifier_accepted.status, 'AC')
        classifier_rejected.refresh_from_db()
        self.assertEqual(
            classifier_rejected.status, 'RJ')
        classifier_error.refresh_from_db()
        self.assertEqual(
            classifier_error.status, 'ER')


class DeletePreMigrationBatchJobsTest(MigrationTest):

    app_name = 'vision_backend'
    before = '0008_batchjob_add_internaljob'
    after = '0009_batchjob_delete_old_completed'

    def test_stop_if_uncompleted_exists(self):
        BatchJobBefore = self.get_model_before('vision_backend.BatchJob')

        BatchJobBefore(status='SUCCEEDED').save()
        BatchJobBefore(status='FAILED').save()
        # Uncompleted
        BatchJobBefore(status='SUBMITTED').save()

        with self.assertRaises(
            ValueError, msg="Migration should get an error"
        ):
            self.run_migration()

        self.assertEqual(
            BatchJobBefore.objects.count(), 3,
            "Should not have deleted any BatchJobs")

        # Manually delete the BatchJobs, so that the test's tearDown()
        # (which tries to get to the latest migrations) doesn't get an error.
        BatchJob.objects.all().delete()

    def test_delete_all(self):
        BatchJobBefore = self.get_model_before('vision_backend.BatchJob')

        BatchJobBefore(status='SUCCEEDED').save()
        BatchJobBefore(status='FAILED').save()
        BatchJobBefore(status='SUCCEEDED').save()

        self.run_migration()

        BatchJobAfter = self.get_model_after('vision_backend.BatchJob')

        self.assertEqual(
            BatchJobAfter.objects.count(), 0,
            "Should have deleted the BatchJobs")


class PopulateLoadedRemotelyTest(MigrationTest):

    before = [
        ('vision_backend', '0015_features_extractor_loaded_remotely'),
        ('images', '0001_squashed_0033_remove_image_annotation_progress'),
    ]
    after = [('vision_backend', '0016_populate_extractor_loaded_remotely')]

    def test_migration(self):
        User = self.get_model_before('auth.User')
        Source = self.get_model_before('images.Source')
        Metadata = self.get_model_before('images.Metadata')
        Image = self.get_model_before('images.Image')
        Features = self.get_model_before('vision_backend.Features')

        user = User(username='testuser')
        user.save()
        source = Source(name="Test source")
        source.save()
        images = []
        for value in [True, False, None]:
            metadata = Metadata()
            metadata.save()
            image = Image(
                original_file=sample_image_as_file('a.png'),
                uploaded_by=user,
                point_generation_method=source.default_point_generation_method,
                metadata=metadata,
                source=source,
            )
            image.save()
            images.append(image)

            features = Features(image=image, model_was_cached=value)
            features.save()

        self.assertTrue(images[0].features.model_was_cached)
        self.assertFalse(images[1].features.model_was_cached)
        self.assertIsNone(images[2].features.model_was_cached)

        self.run_migration()

        images[0].features.refresh_from_db()
        images[1].features.refresh_from_db()
        images[2].features.refresh_from_db()
        self.assertFalse(images[0].features.extractor_loaded_remotely)
        self.assertTrue(images[1].features.extractor_loaded_remotely)
        self.assertIsNone(images[2].features.extractor_loaded_remotely)


class PopulateHasRowcolsTest(MigrationTest):

    before = [
        # Start before the has_rowcols field was even added.
        # Then we'll extract features, then run migration 0020 to add the
        # field with nulls, then run migration 0021 to replace those nulls.
        ('vision_backend', '0019_batchjob_spec_level'),
        ('images', '0034_image_unprocessable_reason'),
    ]
    after = [('vision_backend', '0021_features_populate_has_rowcols')]

    def test_migration(self):
        User = self.get_model_before('auth.User')
        Source = self.get_model_before('images.Source')
        Metadata = self.get_model_before('images.Metadata')
        Image = self.get_model_before('images.Image')
        Features = self.get_model_before('vision_backend.Features')

        user = User(username='testuser')
        user.save()
        source = Source(name="Test source")
        source.save()
        images = []
        for extracted, extracted_dt_args in [
            # Should say no rowcols
            (True, (2020, 12, 30, 23, 0)),
            # Should say has rowcols
            (True, (2020, 12, 31, 1, 0)),
            # No features
            (False, (2020, 12, 31, 1, 0)),
        ]:
            metadata = Metadata()
            metadata.save()
            image = Image(
                original_file=sample_image_as_file('a.png'),
                uploaded_by=user,
                point_generation_method=source.default_point_generation_method,
                metadata=metadata,
                source=source,
            )
            image.save()
            images.append(image)

            features = Features(
                image=image, extracted=extracted,
                extracted_date=datetime(
                    *extracted_dt_args, tzinfo=timezone.utc))
            features.save()

        self.run_migration()

        Features = self.get_model_after('vision_backend.Features')

        has_rowcols_values = [
            Features.objects.get(pk=image.features.pk).has_rowcols
            for image in images
        ]
        self.assertFalse(has_rowcols_values[0])
        self.assertTrue(has_rowcols_values[1])
        self.assertIsNone(has_rowcols_values[2])


class PopulateFeaturesExtractorTest(MigrationTest):

    before = [
        ('sources', '0009_add_deployed_classifier_and_more'),
        ('vision_backend', '0023_source_fk_restore_constraint'),
    ]
    after = [('vision_backend', '0025_features_populate_extractor')]

    def test_migration(self):
        User = self.get_model_before('auth.User')
        Source = self.get_model_before('sources.Source')
        Metadata = self.get_model_before('images.Metadata')
        Image = self.get_model_before('images.Image')
        Features = self.get_model_before('vision_backend.Features')

        user = User(username='testuser')
        user.save()
        source_effnet = Source(
            name="EfficientNet source",
            feature_extractor_setting=Extractors.EFFICIENTNET.value)
        source_effnet.save()
        source_vgg = Source(
            name="VGG16 source",
            feature_extractor_setting=Extractors.VGG16.value)
        source_vgg.save()
        images = []
        for extracted, source in [
            (True, source_effnet),
            (True, source_vgg),
            (False, source_effnet),
            (False, source_vgg),
        ]:
            metadata = Metadata()
            metadata.save()
            image = Image(
                original_file=sample_image_as_file('a.png'),
                uploaded_by=user,
                point_generation_method=source.default_point_generation_method,
                metadata=metadata,
                source=source,
            )
            image.save()
            images.append(image)

            features = Features(image=image, extracted=extracted)
            features.save()

        self.run_migration()

        Features = self.get_model_after('vision_backend.Features')

        extractor_values = [
            Features.objects.get(pk=image.features.pk).extractor
            for image in images
        ]
        self.assertEqual(extractor_values[0], Extractors.EFFICIENTNET.value)
        self.assertEqual(extractor_values[1], Extractors.VGG16.value)
        self.assertEqual(extractor_values[2], '')
        self.assertEqual(extractor_values[3], '')
