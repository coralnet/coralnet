import abc
from io import BytesIO
import json
from logging import getLogger
from typing import Type

from django.conf import settings
from django.core.files.storage import default_storage
from django.utils.module_loading import import_string
from spacer.messages import JobMsg, JobReturnMsg
from spacer.tasks import process_job

from config.constants import SpacerJobSpec

logger = getLogger(__name__)


class BaseQueue(abc.ABC):

    @abc.abstractmethod
    def submit_job(self, job: JobMsg, job_id: int, spec_level: SpacerJobSpec):
        raise NotImplementedError

    @abc.abstractmethod
    def get_collectable_jobs(self):
        raise NotImplementedError

    @abc.abstractmethod
    def collect_jobs(self, jobs: list) -> tuple[list[JobReturnMsg], list[str]]:
        raise NotImplementedError


def get_queue_class() -> Type[BaseQueue]:
    return import_string(settings.SPACER_QUEUE_CHOICE)


class LocalQueue(BaseQueue):
    """
    Used for testing the vision-backend Django tasks.
    Uses a local filesystem queue and calls spacer directly.
    """

    def submit_job(self, job: JobMsg, job_id: int, spec_level: SpacerJobSpec):

        # Process the job right away.
        return_msg = process_job(job)

        filepath = default_storage.path_join('backend_job_res', f'{job_id}.json')
        default_storage.save(
            filepath,
            BytesIO(json.dumps(return_msg.serialize()).encode()))

    def get_collectable_jobs(self):
        try:
            dir_names, filenames = default_storage.listdir('backend_job_res')
        except FileNotFoundError:
            # Perhaps this is a test run and no results files were created
            # yet (thus, the backend_job_res directory was not created).
            filenames = []

        # Sort by filename, which should also put them in job order
        filenames.sort()
        return filenames

    def collect_jobs(
        self, job_filenames: list[str]
    ) -> tuple[list[JobReturnMsg], list[str]]:

        results = []
        statuses = []

        for job_filename in job_filenames:
            # Read the job result message
            filepath = default_storage.path_join(
                'backend_job_res', job_filename)
            with default_storage.open(filepath) as results_file:
                return_msg = JobReturnMsg.deserialize(json.load(results_file))
            # Delete the job result file
            default_storage.delete(filepath)

            # Unlike BatchQueue, LocalQueue is only aware of the
            # jobs that successfully output their results.
            results.append(return_msg)
            statuses.append('SUCCEEDED')

        return results, statuses
