from lib.tests.utils import ClientTest

from annotations.models import Label

from api_core.models import ApiJob, ApiJobUnit
from vision_backend.task_helpers import deploycollector, deploy_fail, \
    encode_spacer_job_token

from spacer.messages import ClassifyImageMsg, JobMsg, JobReturnMsg, \
    ClassifyReturnMsg, DataLocation


class TestDeployCollector(ClientTest):

    @classmethod
    def setUpTestData(cls):

        super(TestDeployCollector, cls).setUpTestData()

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
        api_job_unit = ApiJobUnit(job=api_job,
                                  type='deploy',
                                  request_json={'url': 'URL 1',
                                                'points': 'abc',
                                                'classifier_id': classifier.pk})
        api_job_unit.save()
        cls.api_job_unit_pk = api_job_unit.pk

        cls.task = ClassifyImageMsg(
            job_token=encode_spacer_job_token([api_job_unit.pk]),
            image_loc=DataLocation(storage_type='url', key=''),
            feature_extractor_name='dummy',
            rowcols=[(100, 100), (200, 200)],
            classifier_loc=DataLocation(storage_type='memory', key='')
        )
        cls.res = ClassifyReturnMsg(
            runtime=1.0,
            scores=[(100, 100, [.3, .2, .1]), (200, 200, [.2, .1, .3])],
            classes=[Label.objects.get(name='D').pk,
                     Label.objects.get(name='A').pk,
                     Label.objects.get(name='B').pk],
            valid_rowcol=True
        )

    def test_nominal(self):

        deploycollector(self.task, self.res)

        api_job_unit = ApiJobUnit.objects.get(pk=self.api_job_unit_pk)
        self.assertEqual(api_job_unit.status, 'SC')

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
            results=[self.res],
            ok=False,
            error_message='File not found'
        )

        deploy_fail(job_res)

        api_job_unit = ApiJobUnit.objects.get(pk=self.api_job_unit_pk)
        self.assertEqual(api_job_unit.status, 'FL')
        self.assertEqual(len(api_job_unit.result_json['errors']), 1)
        self.assertEqual(
            api_job_unit.result_json['errors'][0], 'File not found')
