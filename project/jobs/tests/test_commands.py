from datetime import timedelta

from lib.tests.utils import ManagementCommandTest
from ..models import Job
from ..utils import queue_job


class AbortJobTest(ManagementCommandTest):

    def test_abort(self):
        job_1 = Job(job_name='1')
        job_1.save()
        job_2 = Job(job_name='2')
        job_2.save()
        job_3 = Job(job_name='3')
        job_3.save()

        stdout_text, _ = self.call_command_and_get_output(
            'jobs', 'abort_job', args=[job_1.pk, job_3.pk])
        self.assertIn(
            f"The 2 specified Job(s) have been aborted.",
            stdout_text)

        job_details = {
            (job.job_name, job.status, job.result_message)
            for job in Job.objects.all()
        }
        self.assertSetEqual(
            job_details,
            {
                ('1', Job.Status.FAILURE, "Aborted manually"),
                ('2', Job.Status.PENDING, ""),
                ('3', Job.Status.FAILURE, "Aborted manually"),
            },
            "Only jobs 1 and 3 should have been aborted",
        )


class ExpediteJobTest(ManagementCommandTest):

    def test_expedite(self):
        # Queue 3 jobs days into the future. 2 pending, 1 in progress.
        job_1 = queue_job(
            name='1', delay=timedelta(days=3))
        job_2 = queue_job(
            name='2', delay=timedelta(days=3),
            initial_status=Job.Status.IN_PROGRESS)
        job_3 = queue_job(
            name='3', delay=timedelta(days=3))
        original_start_dates = [
            job_1.scheduled_start_date,
            job_2.scheduled_start_date,
            job_3.scheduled_start_date,
        ]

        # Try to expedite each job. Should work for the pending ones only.
        stdout_text, _ = self.call_command_and_get_output(
            'jobs', 'expedite_job', args=[job_1.pk, job_2.pk, job_3.pk])
        self.assertIn(
            f"Job {job_1.pk} has been expedited.", stdout_text)
        self.assertIn(
            f"Job {job_2.pk} isn't pending; no action taken.", stdout_text)
        self.assertIn(
            f"Job {job_3.pk} has been expedited.", stdout_text)

        job_1.refresh_from_db()
        job_2.refresh_from_db()
        job_3.refresh_from_db()
        new_start_dates = [
            job_1.scheduled_start_date,
            job_2.scheduled_start_date,
            job_3.scheduled_start_date,
        ]
        self.assertLess(new_start_dates[0], original_start_dates[0])
        self.assertEqual(new_start_dates[1], original_start_dates[1])
        self.assertLess(new_start_dates[2], original_start_dates[2])
