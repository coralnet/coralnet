from spacer.data_classes import DataLocation
from spacer.messages import (
    ClassifyImageMsg,
    ClassifyReturnMsg,
    JobMsg,
    JobReturnMsg,
)

from annotations.models import Label
from api_core.models import ApiJob, ApiJobUnit
from jobs.models import Job
from jobs.tests.utils import fabricate_job
from lib.tests.utils import ClientTest
from ..common import Extractors
from ..task_helpers import SpacerClassifyResultHandler
from ..utils import get_extractor


class TestDeployCollector(ClientTest):

    @classmethod
    def setUpTestData(cls):

        super().setUpTestData()

        # Mock up the DB entries we need
        cls.user = cls.create_user()

        labels = cls.create_labels(cls.user, ['A', 'B', 'C', 'D'], "Group1")

        source = cls.create_source(cls.user)
        labelset = cls.create_labelset(cls.user, source, labels)
        classifier = cls.create_robot(source)

        # Set custom label codes, so we can confirm we're returning the
        # source's custom codes, not the default codes.
        for code in ['A', 'B', 'C', 'D']:
            local_label = labelset.locallabel_set.get(code=code)
            # A_mycode, B_mycode, etc.
            local_label.code = code + '_mycode'
            local_label.save()

        api_job = ApiJob(type='deploy', user=cls.user)
        api_job.save()

        internal_job = fabricate_job(
            'classify_image',
            api_job.pk, 1,
            status=Job.Status.IN_PROGRESS,
        )
        api_job_unit = ApiJobUnit(
            parent=api_job, order_in_parent=1,
            internal_job=internal_job,
            request_json={
                'url': 'URL 1',
                'points': 'abc',
                'classifier_id': classifier.pk,
            },
        )
        api_job_unit.save()
        cls.api_job_unit_pk = api_job_unit.pk

        cls.task = ClassifyImageMsg(
            job_token=str(internal_job.pk),
            image_loc=DataLocation(storage_type='url', key=''),
            extractor=get_extractor(Extractors.DUMMY.value),
            rowcols=[(100, 100), (200, 200)],
            classifier_loc=DataLocation(storage_type='memory', key=''),
        )
        cls.task_res = ClassifyReturnMsg(
            runtime=1.0,
            scores=[(100, 100, [.3, .2, .1]), (200, 200, [.2, .1, .3])],
            classes=[Label.objects.get(name='D').pk,
                     Label.objects.get(name='A').pk,
                     Label.objects.get(name='B').pk],
            valid_rowcol=True,
        )

    def test_nominal(self):
        job_res = JobReturnMsg(
            original_job=JobMsg(
                task_name='classify_image',
                tasks=[self.task],
            ),
            ok=True,
            results=[self.task_res],
            error_message=None,
        )

        SpacerClassifyResultHandler().handle_job_results([job_res])

        api_job_unit = ApiJobUnit.objects.get(pk=self.api_job_unit_pk)
        self.assertEqual(api_job_unit.status, Job.Status.SUCCESS)

        api_res = api_job_unit.result_json

        self.assertEqual(api_res['url'], api_job_unit.request_json['url'])
        self.assertEqual(len(api_res['points']), 2)

        # First point should be assigned D->A->B
        point = api_res['points'][0]
        self.assertEqual(point['row'], 100)
        self.assertEqual(point['column'], 100)
        self.assertEqual(point['classifications'][0]['label_code'], 'D_mycode')
        self.assertEqual(point['classifications'][1]['label_code'], 'A_mycode')
        self.assertEqual(point['classifications'][2]['label_code'], 'B_mycode')

        # Second point should be assigned B->D->A
        point = api_res['points'][1]
        self.assertEqual(point['row'], 200)
        self.assertEqual(point['column'], 200)
        self.assertEqual(point['classifications'][0]['label_code'], 'B_mycode')
        self.assertEqual(point['classifications'][1]['label_code'], 'D_mycode')
        self.assertEqual(point['classifications'][2]['label_code'], 'A_mycode')

    def test_error(self):
        job_res = JobReturnMsg(
            original_job=JobMsg(
                task_name='classify_image',
                tasks=[self.task]
            ),
            results=[self.task_res],
            ok=False,
            error_message='SomeError: File not found'
        )

        SpacerClassifyResultHandler().handle_job_results([job_res])

        api_job_unit = ApiJobUnit.objects.get(pk=self.api_job_unit_pk)
        self.assertEqual(api_job_unit.status, Job.Status.FAILURE)
        self.assertEqual(
            api_job_unit.result_message,
            'SomeError: File not found')
