from io import BytesIO, StringIO

from lib.exceptions import FileProcessError
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

    def test_binary_file(self):
        # Example start of an Excel (XLSX) file.
        #
        # Including only about 20% of this resulted in ISO-8859-1,
        # and including about 50% resulted in MacCyrillic. So it does need
        # to be about this long to make the encoding guesser give up.
        byte_stream = BytesIO(
            b'PK\x03\x04\x14\x00\x08\x08\x08\x00\xac\xbb\xec\\\x00\x00'
            b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x1a\x00\x00\x00'
            b'xl/_rels/workbook.xml.rels\xadRAj\xc30\x10\xbc\xe7\x15b'
            b'\xef\xb5\xec\xa4\x84R,\xe7\x12\n\xb9\xa6\xe9\x03\x84\xbc\xb6'
            b'LlIh7m\xf2\xfb\xaaMh\x1c\x08\xa1\x07\x9f\xc4\xccjg\x86a\xcb'
            b'\xd5q\xe8\xc5\'F\xea\xbcSPd9\x08t\xc6\xd7\x9dk\x15|\xec\xde'
            b'\x9e^`U\xcd\xca-\xf6\x9a\xd3\x17\xb2] \x91v\x1c)\xb0\xcc\xe1'
            b'UJ2\x16\x07M\x99\x0f\xe8\xd2\xa4\xf1q\xd0\x9c`le\xd0f\xaf['
            b'\x94\xf3<_\xca8\xd6\x80\xeaFSlj\x05qS\x17 v\xa7\x80\xff'
            b'\xd1\xf6M\xd3\x19\\{s\x18\xd0\xf1\x1d\x0b\xc9i\x17\x93\xa0'
            b'\x8e-\xb2\x82_x&\x8b,\x89\x81\xbc\x9fa>e\x06\xe2S\x8ft\rq\xc6'
        )

        with self.assertRaises(FileProcessError) as cm:
            text_file_to_unicode_stream(byte_stream)
        self.assertEqual(
            str(cm.exception),
            f"<file stream>: Failed to decode text file content."
            " Could it be in a binary format like Excel (XLSX)?")
