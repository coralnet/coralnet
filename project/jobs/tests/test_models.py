from django_migration_testcase import MigrationTest


class PopulateJobClassifierTest(MigrationTest):

    before = [
        ('vision_backend', '0033_classifier_train_job_related_name'),
        ('jobs', '0021_job_classifier'),
    ]
    after = [
        ('vision_backend', '0033_classifier_train_job_related_name'),
        ('jobs', '0022_job_classifier_populate'),
    ]

    def test_migration(self):
        Source = self.get_model_before('sources.Source')
        Job = self.get_model_before('jobs.Job')
        Classifier = self.get_model_before('vision_backend.Classifier')

        source = Source()
        source.save()

        # job3 and classifier3 aren't connected to anything.
        job1 = Job(job_name='train', arg_identifier='1')
        job1.save()
        job2 = Job(job_name='train', arg_identifier='2')
        job2.save()
        job3 = Job(job_name='train', arg_identifier='3')
        job3.save()
        classifier1 = Classifier(train_job=job1, source=source)
        classifier1.save()
        classifier2 = Classifier(train_job=job2, source=source)
        classifier2.save()
        classifier3 = Classifier(source=source)
        classifier3.save()

        self.run_migration()

        job1.refresh_from_db()
        self.assertEqual(job1.classifier_id, classifier1.pk)
        job2.refresh_from_db()
        self.assertEqual(job2.classifier_id, classifier2.pk)
        job3.refresh_from_db()
        self.assertIsNone(job3.classifier_id)


class PopulateClassifierTrainJobTest(MigrationTest):

    before = [
        ('vision_backend', '0033_classifier_train_job_related_name'),
        ('jobs', '0022_job_classifier_populate'),
    ]
    after = [
        ('vision_backend', '0033_classifier_train_job_related_name'),
        ('jobs', '0021_job_classifier'),
    ]

    def test_migration(self):
        Source = self.get_model_before('sources.Source')
        Job = self.get_model_before('jobs.Job')
        Classifier = self.get_model_before('vision_backend.Classifier')

        source = Source()
        source.save()

        # job3 and classifier3 aren't connected to anything.
        classifier1 = Classifier(source=source)
        classifier1.save()
        classifier2 = Classifier(source=source)
        classifier2.save()
        classifier3 = Classifier(source=source)
        classifier3.save()
        job1 = Job(
            job_name='train', arg_identifier='1', classifier=classifier1)
        job1.save()
        job2 = Job(
            job_name='train', arg_identifier='2', classifier=classifier2)
        job2.save()
        job3 = Job(job_name='train', arg_identifier='3')
        job3.save()

        self.run_migration()

        classifier1.refresh_from_db()
        self.assertEqual(classifier1.train_job_id, job1.pk)
        classifier2.refresh_from_db()
        self.assertEqual(classifier2.train_job_id, job2.pk)
        classifier3.refresh_from_db()
        self.assertIsNone(classifier3.train_job_id)
