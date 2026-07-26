# Tests (mostly error cases) specific to reading/writing CPC format.
# If the test semantics make sense in CSV format as well, then it
# probably goes in test_upload_general_cases.py.

from io import StringIO

from django.test import SimpleTestCase

from lib.exceptions import FileProcessError
from ..utils import CpcFileContent


class CpcFormatTest(SimpleTestCase):

    @classmethod
    def read_cpc_as_lines(
        cls,
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
            point_label_lines = ['"1","A","Notes",""']
        if header_lines is None:
            header_lines = ['""']*28

        lines = (
            [line1] + area_lines + [point_count_line]
            + point_position_lines + point_label_lines + header_lines
        )
        cpc_string = ''.join(line + '\r\n' for line in lines)
        return cls.read_cpc_as_string(cpc_string)

    @staticmethod
    def read_cpc_as_string(cpc_string):
        return CpcFileContent.from_stream(StringIO(cpc_string, newline=''))

    def write_cpc_as_lines(self, cpc):
        stream = StringIO(newline='')
        cpc.write_cpc(stream)
        stream.seek(0)
        return stream.readlines()

    def test_one_line(self):
        with self.assertRaises(FileProcessError) as cm:
            cpc = self.read_cpc_as_string('"a","b",0,0,0,0\r\n')
        self.assertEqual(
            str(cm.exception), "File seems to have too few lines.")

    def test_line_1_not_enough_tokens(self):
        with self.assertRaises(FileProcessError) as cm:
            cpc = self.read_cpc_as_lines(line1='"abc"')
        self.assertEqual(
            str(cm.exception),
            "Line 1 has 1 comma-separated tokens, but 6 were expected.")

    def test_line_1_too_many_tokens(self):
        with self.assertRaises(FileProcessError) as cm:
            cpc = self.read_cpc_as_lines(line1='"a","b",0,0,0,0,0')
        self.assertEqual(
            str(cm.exception),
            "Line 1 has 7 comma-separated tokens, but 6 were expected.")

    def test_line_1_quoted_commas_accepted(self):
        """Any commas between quotes should be considered part of a
        token, instead of a token separator."""
        cpc = self.read_cpc_as_lines(line1='"a,b","c",0,0,0,0')
        self.assertEqual(cpc.code_filepath, 'a,b')

    def test_write_filepath_with_double_quote(self):
        """Should remove double-quote chars when writing."""
        cpc = self.read_cpc_as_lines()
        cpc.code_filepath = 'C:/CPCe/Code"file.txt'
        cpc.image_filepath = '"D:/Survey"/IMG_0001.JPG'
        cpc_lines = self.write_cpc_as_lines(cpc)
        self.assertEqual(
            cpc_lines[0],
            '"C:/CPCe/Codefile.txt","D:/Survey/IMG_0001.JPG",0,0,0,0\r\n')

    def test_line_2_wrong_number_of_tokens(self):
        with self.assertRaises(FileProcessError) as cm:
            cpc = self.read_cpc_as_lines(area_lines=['0,0,0']*4)
        self.assertEqual(
            str(cm.exception),
            "Line 2 has 3 comma-separated tokens, but 2 were expected.")

    def test_line_6_wrong_number_of_tokens(self):
        with self.assertRaises(FileProcessError) as cm:
            cpc = self.read_cpc_as_lines(point_count_line='1,2')
        self.assertEqual(
            str(cm.exception),
            "Line 6 has 2 comma-separated tokens, but 1 were expected.")

    def test_line_6_not_number(self):
        with self.assertRaises(FileProcessError) as cm:
            cpc = self.read_cpc_as_lines(point_count_line='abc')
        self.assertEqual(
            str(cm.exception),
            "Line 6 is supposed to have the number of points,"
            " but this line isn't a positive integer: abc")

    def test_line_6_number_below_1(self):
        with self.assertRaises(FileProcessError) as cm:
            cpc = self.read_cpc_as_lines(point_count_line='0')
        self.assertEqual(
            str(cm.exception),
            "Line 6 is supposed to have the number of points,"
            " but this line isn't a positive integer: 0")

    def test_point_position_line_wrong_number_of_tokens(self):
        """One way this can manifest is by having one too few point
        position lines, so that a point label line is read as a point
        position line."""
        with self.assertRaises(FileProcessError) as cm:
            cpc = self.read_cpc_as_lines(
                point_count_line='10',
                # One line too few
                point_position_lines=['0,0']*9,
                point_label_lines=['"n","A","Notes",""']*10,
            )
        self.assertEqual(
            str(cm.exception),
            "Line 16 has 4 comma-separated tokens, but 2 were expected.")

    def test_label_line_wrong_number_of_tokens(self):
        """One way this can manifest is by having one too many point
        position lines, so that a point position line is read as a point
        label line."""
        with self.assertRaises(FileProcessError) as cm:
            cpc = self.read_cpc_as_lines(
                point_count_line='10',
                point_position_lines=['0,0']*11,
                point_label_lines=['"n","A","Notes",""']*10,
            )
        self.assertEqual(
            str(cm.exception),
            "Line 17 has 2 comma-separated tokens, but 4 were expected.")

    def test_not_enough_label_lines(self):
        with self.assertRaises(FileProcessError) as cm:
            cpc = self.read_cpc_as_lines(
                point_count_line='10',
                point_position_lines=['0,0']*10,
                # One too few
                point_label_lines=['"n","A","Notes",""']*9,
                # Have the file end at the last point label line
                header_lines=[],
            )
        self.assertEqual(
            str(cm.exception), "File seems to have too few lines.")

    def test_write_point_id_with_double_quote(self):
        """Should remove double-quote chars when writing."""
        cpc = self.read_cpc_as_lines()
        cpc.points[0]['id'] = 'CC"A'
        cpc_lines = self.write_cpc_as_lines(cpc)
        self.assertEqual(cpc_lines[7], '"1","CCA","Notes",""\r\n')

    def test_no_header_lines(self):
        """
        It should be OK to have no header-value lines at the end of the file.
        CoralNet doesn't have a use for them, and CPCe 3.5 does not seem to
        create header lines.
        """
        cpc = self.read_cpc_as_lines(
            header_lines=[],
        )
        self.assertListEqual(cpc.headers, [])

    def test_header_with_backslash(self):
        """No special treatment for backslashes."""
        cpc = self.read_cpc_as_lines(
            header_lines=[r'"\,\\\"'] + ['""']*27,
        )
        self.assertEqual(cpc.headers[0], '/,///'.replace('/', '\\'))

    def test_header_with_comma(self):
        """This shouldn't confuse the reader or writer."""
        cpc = self.read_cpc_as_lines(
            header_lines=['"La Jolla, CA"'] + ['""']*27,
        )
        self.assertEqual(cpc.headers[0], 'La Jolla, CA')

    def test_header_purely_numeric(self):
        """
        No special treatment for purely-numeric headers; CPCe
        does not follow a 'quote anything non-numeric' rule, it
        just quotes specific fields.
        """
        cpc = self.read_cpc_as_lines(
            header_lines=['"123"'] + ['""']*27,
        )
        self.assertEqual(cpc.headers[0], '123')

    def test_write_header_with_double_quote(self):
        """Should remove double-quote chars when writing."""
        cpc = self.read_cpc_as_lines()
        cpc.headers[0] = 'Header "value"'
        cpc_lines = self.write_cpc_as_lines(cpc)
        self.assertEqual(cpc_lines[8], '"Header value"\r\n')
