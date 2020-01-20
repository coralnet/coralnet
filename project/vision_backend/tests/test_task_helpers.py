from lib.tests.utils import ClientTest

from annotations.models import Label

from api_core.models import ApiJob, ApiJobUnit
from vision_backend.task_helpers import _deploycollector


class TestDeployCollector(ClientTest):

    @classmethod
    def setUpTestData(cls):

        super(TestDeployCollector, cls).setUpTestData()

        # Mock up the DB entries we need
        cls.user = cls.create_user()

        cls.create_labels(cls.user, ['A', 'B', 'C', 'D'], "Group1")

        api_job = ApiJob(type='deploy', user=cls.user)
        api_job.save()
        api_job_unit = ApiJobUnit(job=api_job,
                                  type='deploy',
                                  request_json={'url': 'URL 1',
                                                'points': 'abc'})
        api_job_unit.save()
        cls.api_job_unit_pk = api_job_unit.pk

    def test_nominal(self):

        messagebody = {
            u'original_job': {
                u'task': u'deploy',
                u'payload': {
                    u'rowcols': [[100, 100], [200, 200]],
                    u'modelname': u'vgg16_coralnet_ver1',
                    u'bucketname': u'coralnet-beijbom-dev',
                    u'im_url': u'https://coralnet-beijbom-dev.s3-us-west-2.'
                               u'amazonaws.com/media/images/04yv0o1o88.jpg',
                    u'pk': 0,
                    u'model': u'media/classifiers/14.model'
                    }
                },
            u'result': {
                u'scores': [[.3, .2, .1],
                            [.2, .1, .3]],
                u'classes': [0, 1, 2],
                u'model_was_cashed': True,
                u'runtime': {
                    u'core': 20,
                    u'total': 21,
                    u'per_point': 10
                },
                u'ok': 1
            }
        }
        # Assign the right classes. Deliberately leave 'C' out and shuffle
        # order to make sure we handle non-sequential labels in set.
        messagebody['result']['classes'] = [
            Label.objects.get(name='D').pk,
            Label.objects.get(name='A').pk,
            Label.objects.get(name='B').pk
        ]
        messagebody['original_job']['payload']['pk'] = self.api_job_unit_pk

        _deploycollector(messagebody)

        api_job_unit = ApiJobUnit.objects.get(pk=self.api_job_unit_pk)
        self.assertEqual(api_job_unit.status, 'SC')

        results = api_job_unit.result_json

        self.assertEqual(results['url'],
                         api_job_unit.request_json['url'])
        self.assertEqual(len(results['points']), 2)

        # First point should be assigned D->A->B
        point = results['points'][0]
        self.assertEqual(point['row'], 100)
        self.assertEqual(point['column'], 100)
        self.assertEqual(point['classifications'][0]['label_code'], 'D')
        self.assertEqual(point['classifications'][1]['label_code'], 'A')
        self.assertEqual(point['classifications'][2]['label_code'], 'B')

        # Second point should be assigned B->D->A
        point = results['points'][1]
        self.assertEqual(point['row'], 200)
        self.assertEqual(point['column'], 200)
        self.assertEqual(point['classifications'][0]['label_code'], 'B')
        self.assertEqual(point['classifications'][1]['label_code'], 'D')
        self.assertEqual(point['classifications'][2]['label_code'], 'A')

    def test_error(self):

        messagebody = {
            u'original_job': {
                u'task': u'deploy',
                u'payload': {
                    u'rowcols': [[100, 100], [200, 200]],
                    u'modelname': u'vgg16_coralnet_ver1',
                    u'bucketname': u'coralnet-beijbom-dev',
                    u'im_url': u'https://coralnet-beijbom-dev.s3-us-west-2.'
                               u'amazonaws.com/media/images/04yv0o1o88.jpg',
                    u'pk': 0,
                    u'model': u'media/classifiers/14.model'
                }
            },
            u'result': {
                u'error': 'File not found',
                u'ok': 0
            }
        }

        messagebody['original_job']['payload']['pk'] = self.api_job_unit_pk

        _deploycollector(messagebody)

        api_job_unit = ApiJobUnit.objects.get(pk=self.api_job_unit_pk)
        self.assertEqual(api_job_unit.status, 'FL')
        self.assertEqual(api_job_unit.result_json['error'],
                         'File not found')
