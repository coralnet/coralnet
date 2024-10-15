from django_migration_testcase import MigrationTest


class HideOldSourceChecksTest(MigrationTest):

    app_name = 'jobs'
    before = '0018_job_hidden'
    after = '0019_hide_old_source_checks'

    def test_migration(self):
        Job = self.get_model_before('jobs.Job')

        other_job_1 = Job(job_name='extract_features')
        other_job_1.save()
        check_job = Job(job_name='check_source')
        check_job.save()
        other_job_2 = Job(job_name='generate_thumbnail')
        other_job_2.save()

        self.assertFalse(other_job_1.hidden)
        self.assertFalse(check_job.hidden)
        self.assertFalse(other_job_2.hidden)

        self.run_migration()

        Job = self.get_model_after('jobs.Job')

        # The check-source job should have gotten hidden
        self.assertFalse(Job.objects.get(pk=other_job_1.pk).hidden)
        self.assertTrue(Job.objects.get(pk=check_job.pk).hidden)
        self.assertFalse(Job.objects.get(pk=other_job_2.pk).hidden)
