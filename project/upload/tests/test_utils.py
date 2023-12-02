from io import BytesIO, StringIO

from lib.tests.utils import BaseTest
from ..utils import csv_to_dicts, text_file_to_unicode_stream


class CsvToDictsTest(BaseTest):

    def test_missing_optional_column(self):
        lines = [
            'A,B',
            '1,2',
        ]
        csv_content = ''.join([line + '\n' for line in lines])
        dicts = csv_to_dicts(
            StringIO(csv_content),
            required_columns=dict(a='A', b='B'),
            optional_columns=dict(c='C'),
            unique_keys=[],
        )
        self.assertDictEqual(
            dicts[0], dict(a='1', b='2'),
            msg="dict should not have key for optional column")

    def test_missing_optional_cell(self):
        # Optional column is present, but cell is not; note how there's
        # no comma after the 2.
        lines = [
            'A,B,C',
            '1,2',
        ]
        csv_content = ''.join([line + '\n' for line in lines])
        dicts = csv_to_dicts(
            StringIO(csv_content),
            required_columns=dict(a='A', b='B'),
            optional_columns=dict(c='C'),
            unique_keys=[],
        )
        self.assertDictEqual(
            dicts[0], dict(a='1', b='2', c=''),
            msg="dict should have key for optional column")

    def test_blank_optional_cell(self):
        # Cell under the optional column is present, but blank; note how
        # there's a comma after the 2.
        # Since this is hard to distinguish from a missing optional cell,
        # we want the behavior to be the same as that case.
        # (But not necessarily the same as when the column header is absent.)
        lines = [
            'A,B,C',
            '1,2,',
        ]
        csv_content = ''.join([line + '\n' for line in lines])
        dicts = csv_to_dicts(
            StringIO(csv_content),
            required_columns=dict(a='A', b='B'),
            optional_columns=dict(c='C'),
            unique_keys=[],
        )
        self.assertDictEqual(
            dicts[0], dict(a='1', b='2', c=''),
            msg="dict should have key for optional column")


class TextFileToUnicodeTest(BaseTest):

    def test_chinese_utf8(self):
        byte_stream = BytesIO(
            b'1.\xe5\xb0\x88\xe6\xa1\x88\xe8\xa8\x88\xe7\x95\xab\\'
            b'10.\xe5\xbe\x8c\xe7\x81\xa3\xe4\xb8\xbb\xe9\xa1\x8c'
            b'\xe8\xa8\x88\xe7\x95\xab\\20150610~11_HW'
        )
        unicode_stream = text_file_to_unicode_stream(byte_stream)
        self.assertEqual(
            unicode_stream.read(), '1.專案計畫\\10.後灣主題計畫\\20150610~11_HW')

    def test_chinese_big5(self):
        # This came up in production. chardet and charset-normalizer should
        # agree on Big5. Fails to decode as utf-8.
        byte_stream = BytesIO(
            b'1.\xb1M\xae\xd7\xadp\xb5e\\'
            b'10.\xab\xe1\xc6W\xa5D\xc3D\xadp\xb5e\\20140619~20_HW'
        )
        unicode_stream = text_file_to_unicode_stream(byte_stream)
        self.assertEqual(
            unicode_stream.read(), '1.專案計畫\\10.後灣主題計畫\\20140619~20_HW')

    def test_xe9(self):
        # This came up in production. chardet says ISO-8859-1,
        # charset-normalizer says windows-1250, and fails to decode as utf-8.
        # (Can decode as either of the first 2 guesses.)
        byte_stream = BytesIO(
            b'Tri\xe9\\1 H\xe9lice'
        )
        unicode_stream = text_file_to_unicode_stream(byte_stream)
        self.assertEqual(unicode_stream.read(), 'Trié\\1 Hélice')
