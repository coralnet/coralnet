from jobs.utils import schedule_job
from lib.tests.utils import ClientTest
from ..models import BatchJob


class CascadeDeleteTest(ClientTest):

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
