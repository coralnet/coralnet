from io import BytesIO
import json
from unittest import mock
from zipfile import ZipFile

from django.core.files.base import ContentFile
from django.urls import reverse

from lib.exceptions import FileProcessError
from lib.tests.utils import BasePermissionTest, ClientTest


class PermissionTest(BasePermissionTest):

    def test_page(self):
        url = reverse('cpce:cpc_batch_editor')
        template = 'cpce/cpc_batch_editor.html'

        self.assertPermissionLevel(
            url, self.SIGNED_IN, template=template,
            deny_type=self.REQUIRE_LOGIN)

    def test_process(self):
        url = reverse('cpce:cpc_batch_editor_process_ajax')

        self.assertPermissionLevel(
            url, self.SIGNED_IN, is_json=True, post_data={},
            deny_type=self.REQUIRE_LOGIN)

    def test_serve(self):
        # Without session variables from the process view, this should
        # redirect to the batch editor page.
        url = reverse('cpce:cpc_batch_editor_file_serve')
        template = 'cpce/cpc_batch_editor.html'

        self.assertPermissionLevel(
            url, self.SIGNED_IN, template=template,
            deny_type=self.REQUIRE_LOGIN)


class BaseCpcBatchEditTest(ClientTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()

    @staticmethod
    def make_cpc_lines(
        line1='"a","b",0,0,0,0',
        area_lines=None,
        point_count_line='1',
        point_position_lines=None,
        point_label_lines=None,
        header_lines=None,
    ):
        if area_lines is None:
            area_lines = ['0,0']*4
        if point_position_lines is None:
            point_position_lines = ['0,0']
        if point_label_lines is None:
            point_label_lines = ['"1","","Notes",""']
        if header_lines is None:
            header_lines = ['""']*28

        return (
            [line1] + area_lines + [point_count_line]
            + point_position_lines + point_label_lines + header_lines
        )

    def process(self, post_data):
        self.client.force_login(self.user)
        return self.client.post(
            reverse('cpce:cpc_batch_editor_process_ajax'),
            post_data,
        )

    def batch_edit(self, post_data):
        process_response = self.process(post_data)
        timestamp = process_response.json()['session_data_timestamp']

        self.client.force_login(self.user)
        return self.client.get(
            reverse('cpce:cpc_batch_editor_file_serve'),
            dict(session_data_timestamp=timestamp),
        )


class MainTest(BaseCpcBatchEditTest):

    def test_ids_only(self):
        cpc_lines = self.make_cpc_lines(
            point_count_line='4',
            point_position_lines=['0,0']*4,
            point_label_lines=[
                '"1","A","Notes",""',
                '"2","B","Notes",""',
                '"3","C","Notes",""',   # Line matching no rule
                '"4","A","Notes","X"',  # Second line matching same rule
            ],
        )
        cpc_content = ''.join([line + '\n' for line in cpc_lines])
        cpc_file = ContentFile(cpc_content, name='1.cpc')

        csv_lines = [
            'Old ID,New ID',
            'A,B',
            'B,C',
        ]
        csv_content = ''.join([line + '\n' for line in csv_lines])
        csv_file = ContentFile(csv_content, name='spec.csv')

        post_data = dict(
            cpc_files=[cpc_file],
            cpc_filepaths=json.dumps({'1.cpc': '1.cpc'}),
            label_spec_fields='id_only',
            label_spec_csv=csv_file,
        )
        response = self.batch_edit(post_data)

        zf = ZipFile(BytesIO(response.content))
        # Use decode() to get a Unicode string
        actual_cpc_content = zf.read('1.cpc').decode()

        expected_cpc_lines = self.make_cpc_lines(
            point_count_line='4',
            point_position_lines=['0,0']*4,
            point_label_lines=[
                '"1","B","Notes",""',
                '"2","C","Notes",""',
                '"3","C","Notes",""',
                '"4","B","Notes","X"',
            ],
        )
        self.assertListEqual(
            actual_cpc_content.splitlines(), expected_cpc_lines)

    def test_ids_and_notes(self):
        cpc_lines = self.make_cpc_lines(
            point_count_line='8',
            point_position_lines=['0,0']*8,
            point_label_lines=[
                '"1","A","Notes","X"',
                '"2","A","Notes","Y"',  # Matching different rule with same ID
                '"3","A","Notes","Z"',  # Matching ID but non-matching Notes
                '"4","A","Notes",""',   # Matching ID but non-matching Notes
                '"5","B","Notes","X"',
                '"6","B","Notes",""',   # Matching rule with blank Notes
                '"7","A","Notes","X"',  # Second line matching same rule
                '"8","C","Notes","X"',  # Non-matching ID
            ],
        )
        cpc_content = ''.join([line + '\n' for line in cpc_lines])
        cpc_file = ContentFile(cpc_content, name='1.cpc')

        csv_lines = [
            'Old ID,Old Notes,New ID,New Notes',
            'A,X,B,Y',
            'A,Y,A,Z',
            'B,X,B,',   # New Notes blank
            'B,,C,X',   # Old Notes blank
        ]
        csv_content = ''.join([line + '\n' for line in csv_lines])
        csv_file = ContentFile(csv_content, name='spec.csv')

        post_data = dict(
            cpc_files=[cpc_file],
            cpc_filepaths=json.dumps({'1.cpc': '1.cpc'}),
            label_spec_fields='id_and_notes',
            label_spec_csv=csv_file,
        )
        response = self.batch_edit(post_data)

        zf = ZipFile(BytesIO(response.content))
        actual_cpc_content = zf.read('1.cpc').decode()

        expected_cpc_lines = self.make_cpc_lines(
            point_count_line='8',
            point_position_lines=['0,0']*8,
            point_label_lines=[
                '"1","B","Notes","Y"',
                '"2","A","Notes","Z"',
                '"3","A","Notes","Z"',
                '"4","A","Notes",""',
                '"5","B","Notes",""',
                '"6","C","Notes","X"',
                '"7","B","Notes","Y"',
                '"8","C","Notes","X"',
            ],
        )
        self.assertListEqual(
            actual_cpc_content.splitlines(), expected_cpc_lines)

    def test_filepaths(self):
        cpc_lines = self.make_cpc_lines(line1='"1","b",0,0,0,0')
        cpc_content = ''.join([line + '\n' for line in cpc_lines])
        cpc_file_1 = ContentFile(cpc_content, name='1.cpc')

        cpc_lines = self.make_cpc_lines(line1='"2","b",0,0,0,0')
        cpc_content = ''.join([line + '\n' for line in cpc_lines])
        cpc_file_2 = ContentFile(cpc_content, name='2.cpc')

        csv_lines = [
            'Old ID,New ID',
            'A,B',
        ]
        csv_content = ''.join([line + '\n' for line in csv_lines])
        csv_file = ContentFile(csv_content, name='spec.csv')

        post_data = dict(
            # Send files out of order
            cpc_files=[cpc_file_2, cpc_file_1],
            cpc_filepaths=json.dumps({
                '1.cpc': '0001.cpc',
                '2.cpc': 'Surveys/Panama/0002.cpc',
            }),
            label_spec_fields='id_only',
            label_spec_csv=csv_file,
        )
        response = self.batch_edit(post_data)

        zf = ZipFile(BytesIO(response.content))

        cpc_content = zf.read('0001.cpc').decode()
        self.assertTrue(
            cpc_content.startswith('"1"'),
            "First CPC's filepath was mapped correctly")

        cpc_content = zf.read('Surveys/Panama/0002.cpc').decode()
        self.assertTrue(
            cpc_content.startswith('"2"'),
            "Second CPC's filepath was mapped correctly")


def raise_process_error(*_args):
    raise FileProcessError("A process error")


class ErrorCasesTest(BaseCpcBatchEditTest):

    def test_cpc_file_process_error(self):

        # Minimal valid inputs.
        cpc_lines = self.make_cpc_lines(
            point_count_line='1',
            point_position_lines=['0,0']*1,
            point_label_lines=['"1","A","Notes",""'],
        )
        cpc_content = ''.join([line + '\n' for line in cpc_lines])
        cpc_file = ContentFile(cpc_content, name='1.cpc')

        csv_lines = ['Old ID,New ID', 'A,B']
        csv_content = ''.join([line + '\n' for line in csv_lines])
        csv_file = ContentFile(csv_content, name='spec.csv')

        post_data = dict(
            cpc_files=[cpc_file],
            cpc_filepaths=json.dumps({'1.cpc': '1.cpc'}),
            label_spec_fields='id_only',
            label_spec_csv=csv_file,
        )

        with mock.patch(
            'cpce.views.text_file_to_unicode_stream',
            raise_process_error,
        ):
            response = self.process(post_data)

        self.assertDictEqual(
            response.json(), dict(error="A process error"),
            "Response JSON should be as expected")
