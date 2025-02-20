import datetime

from django.test import override_settings
from django.utils import timezone
from django_migration_testcase import MigrationTest

from jobs.models import Job
from jobs.tests.utils import do_job
from lib.tests.utils import ClientTest
from ..models import ApiJob, ApiJobUnit


@override_settings(JOB_MAX_DAYS=30)
class JobCleanupTest(ClientTest):
    """
    Test cleanup of old API jobs.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()

    @staticmethod
    def create_unit(api_job, order):
        internal_job = Job(
            job_name='test', arg_identifier=f'{api_job.pk}_{order}')
        internal_job.save()
        unit = ApiJobUnit(
            parent=api_job, internal_job=internal_job,
            order_in_parent=order, request_json=[],
        )
        unit.save()
        return unit

    @staticmethod
    def run_and_get_result():
        do_job('clean_up_old_api_jobs')
        job = Job.objects.filter(
            job_name='clean_up_old_api_jobs',
            status=Job.Status.SUCCESS).latest('pk')
        return job.result_message

    def test_zero_jobs_message(self):
        """
        Check the result message when there are no API jobs to clean up.
        """
        self.assertEqual(
            self.run_and_get_result(), "No old API jobs to clean up")

    def test_job_selection(self):
        """
        Only jobs eligible for cleanup should be cleaned up.
        """
        thirty_one_days_ago = timezone.now() - datetime.timedelta(days=31)

        job = ApiJob(type='new job, no units', user=self.user)
        job.save()

        job = ApiJob(type='old job, no units', user=self.user)
        job.save()
        job.create_date = thirty_one_days_ago
        job.save()

        job = ApiJob(type='new job, recent unit work', user=self.user)
        job.save()
        self.create_unit(job, 1)
        self.create_unit(job, 2)

        job = ApiJob(type='old job, recent unit work', user=self.user)
        job.save()
        job.create_date = thirty_one_days_ago
        job.save()
        self.create_unit(job, 1)
        self.create_unit(job, 2)

        job = ApiJob(
            type='old job, mixed units', user=self.user)
        job.save()
        job.create_date = thirty_one_days_ago
        job.save()
        unit_1 = self.create_unit(job, 1)
        self.create_unit(job, 2)
        # Use QuerySet.update() instead of Model.save() so that the modify
        # date doesn't get auto-updated to the current time.
        Job.objects.filter(pk=unit_1.internal_job.pk).update(
            modify_date=thirty_one_days_ago)

        job = ApiJob(
            type='old job, old units', user=self.user)
        job.save()
        job.create_date = thirty_one_days_ago
        job.save()
        unit_1 = self.create_unit(job, 1)
        unit_2 = self.create_unit(job, 2)
        Job.objects.filter(pk=unit_1.internal_job.pk).update(
            modify_date=thirty_one_days_ago)
        Job.objects.filter(pk=unit_2.internal_job.pk).update(
            modify_date=thirty_one_days_ago)

        self.assertEqual(
            self.run_and_get_result(), "Cleaned up 2 old API job(s)")

        self.assertTrue(
            ApiJob.objects.filter(type='new job, no units').exists(),
            "Shouldn't clean up new jobs with no units yet")
        self.assertFalse(
            ApiJob.objects.filter(type='old job, no units').exists(),
            "Should clean up old jobs with no units")
        self.assertTrue(
            ApiJob.objects.filter(
                type='new job, recent unit work').exists(),
            "Shouldn't clean up new jobs with units")
        self.assertTrue(
            ApiJob.objects.filter(
                type='old job, recent unit work').exists(),
            "Shouldn't clean up old jobs if units were modified recently")
        self.assertTrue(
            ApiJob.objects.filter(
                type='old job, mixed units').exists(),
            "Shouldn't clean up old jobs if some units were modified recently")
        self.assertFalse(
            ApiJob.objects.filter(
                type='old job, old units').exists(),
            "Should clean up old jobs if no units were modified recently")

    def test_unit_cleanup(self):
        """
        The cleanup task should also clean up associated job units.
        """
        thirty_one_days_ago = timezone.now() - datetime.timedelta(days=31)

        job = ApiJob(type='new', user=self.user)
        job.save()
        for n in range(1, 5+1):
            self.create_unit(job, n)

        job = ApiJob(type='old', user=self.user)
        job.save()
        job.create_date = thirty_one_days_ago
        job.save()
        for n in range(1, 5+1):
            unit = self.create_unit(job, n)
            # Use QuerySet.update() instead of Model.save() so that the modify
            # date doesn't get auto-updated to the current date.
            Job.objects.filter(pk=unit.internal_job.pk).update(
                modify_date=thirty_one_days_ago)

        self.run_and_get_result()

        self.assertTrue(
            ApiJobUnit.objects.filter(parent__type='new').exists(),
            "Shouldn't clean up the new job's units")
        self.assertFalse(
            ApiJobUnit.objects.filter(parent__type='old').exists(),
            "Should clean up the old job's units")


class FinishDatePopulateMigrationTest(MigrationTest):

    before = [
        ('accounts', '0001_squashed_0012_field_string_attributes_to_unicode'),
        ('api_core', '0011_userapilimits'),
        ('jobs', '0019_hide_old_source_checks'),
    ]
    after = [
        ('api_core', '0013_apijob_finish_date_populate'),
    ]

    def create_unit(self, **kwargs):
        ApiJobUnit = self.get_model_before('api_core.ApiJobUnit')
        Job = self.get_model_before('jobs.Job')

        job = Job(
            job_name='name',
            arg_identifier=
                f'{kwargs["parent"].pk}_{kwargs["order_in_parent"]}',
        )
        job.save()
        unit = ApiJobUnit(internal_job=job, **kwargs)
        unit.save()
        return unit

    @staticmethod
    def finish_unit(unit):
        unit.result_json = {}
        unit.save()
        unit.internal_job.result_message = "message"
        unit.internal_job.save()

    def test(self):
        ApiJob = self.get_model_before('api_core.ApiJob')
        User = self.get_model_before('auth.User')

        user = User(username='username')
        user.save()
        unfinished_api_job = ApiJob(type='type', user=user)
        unfinished_api_job.save()
        finished_api_job = ApiJob(type='type', user=user)
        finished_api_job.save()

        self.create_unit(
            parent=unfinished_api_job, order_in_parent=1,
            request_json={}, result_json={})
        # This unit is unfinished, rendering the whole API job unfinished.
        self.create_unit(
            parent=unfinished_api_job, order_in_parent=2,
            request_json={})

        # These units start off unfinished, but we then finish them all,
        # in a different order from the creation order (so that we can tell
        # the logic later in this test is based on modify date).

        finished_api_job_unit_1 = self.create_unit(
            parent=finished_api_job, order_in_parent=1,
            request_json={})
        finished_api_job_unit_2 = self.create_unit(
            parent=finished_api_job, order_in_parent=2,
            request_json={})
        finished_api_job_unit_3 = self.create_unit(
            parent=finished_api_job, order_in_parent=3,
            request_json={})
        self.finish_unit(finished_api_job_unit_1)
        self.finish_unit(finished_api_job_unit_3)
        self.finish_unit(finished_api_job_unit_2)

        self.run_migration()

        ApiJob = self.get_model_after('api_core.ApiJob')

        unfinished_api_job = ApiJob.objects.get(pk=unfinished_api_job.pk)
        self.assertIsNone(unfinished_api_job.finish_date)
        finished_api_job = ApiJob.objects.get(pk=finished_api_job.pk)
        self.assertEqual(
            finished_api_job.finish_date,
            finished_api_job_unit_2.internal_job.modify_date,
            msg="Should be equal to the latest modify date among the units",
        )
