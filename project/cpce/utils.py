import csv
from io import StringIO
from pathlib import PureWindowsPath
import re
from typing import List, Tuple

from django.conf import settings

from export.utils import create_zip_stream_response, write_zip
from images.models import Image
from lib.exceptions import FileProcessError
from sources.models import Source
from upload.utils import csv_to_dicts


def annotations_cpcs_to_dict(
        cpc_names_and_streams: List[Tuple[str, StringIO]],
        source: Source,
        label_mapping: str) -> List[dict]:

    cpc_info = []
    image_names_to_cpc_filenames = dict()

    for cpc_filename, stream in cpc_names_and_streams:

        try:
            cpc = CpcFileContent.from_stream(stream)
            image, annotations = cpc.get_image_and_annotations(
                source, label_mapping)
        except FileProcessError as error:
            raise FileProcessError(f"From file {cpc_filename}: {error}")

        if image is None:
            continue

        stream.seek(0)
        cpc_content = stream.read()

        image_name = image.metadata.name
        if image_name in image_names_to_cpc_filenames:
            raise FileProcessError(
                f"Image {image_name} has points from more than one .cpc file:"
                f" {image_names_to_cpc_filenames[image_name]}"
                f" and {cpc_filename}. There should be only one .cpc file"
                f" per image."
            )
        image_names_to_cpc_filenames[image_name] = cpc_filename

        cpc_info.append(dict(
            filename=cpc_filename,
            image_id=image.pk,
            annotations=annotations,
            cpc_content=cpc_content,
        ))

    if len(cpc_info) == 0:
        raise FileProcessError("No matching image names found in the source")

    return cpc_info


def create_zipped_cpcs_stream_response(cpc_strings, zip_filename):
    response = create_zip_stream_response(zip_filename)
    # Convert Unicode strings to byte strings
    cpc_byte_strings = dict([
        (cpc_filename, cpc_content.encode())
        for cpc_filename, cpc_content in cpc_strings.items()
    ])
    write_zip(response, cpc_byte_strings)
    return response


def get_previous_cpcs_status(image_set):
    if image_set.exclude(cpc_content='').exists():
        # At least 1 image has a previous CPC
        if image_set.filter(cpc_content='').exists():
            # Some, but not all images have previous CPCs
            return 'some'
        else:
            # All images have previous CPCs
            return 'all'
    else:
        # No images have previous CPCs
        return 'none'


def labelset_has_plus_code(labelset):
    """
    Returns True if the labelset has at least one label code with the
    + character, False otherwise. This is for CPCe upload/export.
    """
    return labelset.get_labels().filter(code__contains='+').exists()


def cpc_editor_csv_to_dicts(
        csv_stream: StringIO, fields_option: str) -> List[dict]:

    # Two acceptable formats, with notes and without notes.
    if fields_option == 'id_and_notes':
        label_spec = csv_to_dicts(
            csv_stream=csv_stream,
            required_columns=dict(
                old_id="Old ID",
                new_id="New ID",
            ),
            optional_columns=dict(
                old_notes="Old Notes",
                new_notes="New Notes",
            ),
            unique_keys=['old_id', 'old_notes'],
        )
        for spec_item in label_spec:
            # If one of the Notes columns isn't present, fill in '' values.
            if 'old_notes' not in spec_item:
                spec_item['old_notes'] = ''
            if 'new_notes' not in spec_item:
                spec_item['new_notes'] = ''
    else:
        # 'id_only'
        label_spec = csv_to_dicts(
            csv_stream=csv_stream,
            required_columns=dict(
                old_id="Old ID",
                new_id="New ID",
            ),
            optional_columns=dict(),
            unique_keys=['old_id'],
        )

    for spec_item in label_spec:
        # We'll use these dicts to build up preview info as well.
        spec_item['point_count'] = 0

    return label_spec


def cpc_edit_labels(
        cpc_stream: StringIO,
        label_spec: List[dict],
        fields_option: str,
) -> str:

    cpc = CpcFileContent.from_stream(cpc_stream)

    for point in cpc.points:
        for spec_item in label_spec:
            if fields_option == 'id_and_notes':
                if (point['id'] == spec_item['old_id']
                        and point['notes'] == spec_item['old_notes']):
                    point['id'] = spec_item['new_id']
                    point['notes'] = spec_item['new_notes']
                    spec_item['point_count'] += 1
                    # Don't allow multiple transformations on a single point
                    break
            else:
                # Look at ID only
                if point['id'] == spec_item['old_id']:
                    point['id'] = spec_item['new_id']
                    spec_item['point_count'] += 1
                    break

    out_stream = StringIO()
    cpc.write_cpc(out_stream)
    return out_stream.getvalue()


class CpcFileContent:
    """
    Reading, editing, and writing of CPC file format.
    """
    def __init__(
            self, code_filepath, image_filepath,
            image_width, image_height,
            display_width, display_height,
            annotation_area, points, headers,
    ):
        self.code_filepath = code_filepath
        self.image_filepath = image_filepath
        self.image_width = image_width
        self.image_height = image_height
        self.display_width = display_width
        self.display_height = display_height
        self.annotation_area = annotation_area
        self.points = points
        self.headers = headers

    @classmethod
    def from_stream(cls, cpc_stream: StringIO):

        # Each line of a .cpc file is like a CSV row.
        #
        # But different lines have different kinds of values, so we'll go
        # through the lines with next() instead of with a for loop.
        reader = csv.reader(cpc_stream, delimiter=',', quotechar='"')

        def read_line(num_tokens_expected):
            return cls.read_line(reader, num_tokens_expected)

        # Line 1: environment info and image dimensions
        code_filepath, image_filepath, \
            image_width, image_height, \
            display_width, display_height \
            = read_line(6)

        # Lines 2-5: annotation area bounds
        # CPCe saves these numbers anywhere from 0 to 4 decimal places.
        # We'll store these numbers as strings, since 1) storing exact
        # float values takes a bit more care compared to ints, and
        # 2) CoralNet doesn't have any reason to read/manipulate
        # these numeric values later on.
        annotation_area = dict(
            bottom_left=read_line(2),
            bottom_right=read_line(2),
            top_right=read_line(2),
            top_left=read_line(2),
        )

        # Line 6: number of points
        token = read_line(1)[0]
        try:
            num_points = int(token)
            if num_points <= 0:
                raise ValueError
        except ValueError:
            raise FileProcessError((
                f"Line {reader.line_num} is supposed to have"
                f" the number of points, but this line isn't a"
                f" positive integer: {token}"))

        # Next num_points lines: point positions
        points = []
        for _ in range(num_points):
            x, y = read_line(2)
            points.append(dict(x=x, y=y))

        # Next num_points lines: point ID/Notes data.
        # We're taking advantage of the fact that the previous section
        # and this section are both in point-number order. As long as we
        # maintain that order, we assign labels to the correct points.
        for point_index in range(num_points):
            p = points[point_index]
            # Token 1: CPCe gives a choice of using numbers or letters to
            # identify points, so this can be 1, 2, 3, ... or A, B, C, ...
            # Token 3 is always `Notes`.
            p['number_label'], p['id'], _, p['notes'] \
                = read_line(4)

        # Next 28 lines: header fields, one per line.
        # These lines may or may not be present. (Seems to be all or
        # nothing, but we won't enforce that here.)
        headers = []
        for _ in range(28):
            try:
                headers.append(next(reader)[0])
            except StopIteration:
                break

        return CpcFileContent(
            code_filepath,
            image_filepath,
            image_width,
            image_height,
            display_width,
            display_height,
            annotation_area,
            points,
            headers,
        )

    @staticmethod
    def read_line(reader, num_tokens_expected: int) -> List[str]:
        """
        Basically like calling next(reader), but with more controlled
        error handling.
        """
        try:
            line_tokens = [token.strip() for token in next(reader)]
        except StopIteration:
            raise FileProcessError(
                "File seems to have too few lines.")

        if len(line_tokens) != num_tokens_expected:
            raise FileProcessError((
                f"Line {reader.line_num} has"
                f" {len(line_tokens)} comma-separated tokens, but"
                f" {num_tokens_expected} were expected."))

        return line_tokens

    def write_cpc(self, cpc_stream: StringIO) -> None:
        # Each line is a series of comma-separated tokens. However, the
        # CSV module isn't quite able to imitate CPCe's behavior, because
        # CPCe unconditionally quotes some tokens and not others, even
        # varying the rule on the same line for line 1's case.
        # Also, the way CPCe does quoting is different from the CSV module.
        # So we'll manually write to the stream.

        def writerow(tokens):
            tokens = [str(t) for t in tokens]
            # CPCe is Windows software, so it's going to use Windows
            # newlines.
            newline = '\r\n'
            cpc_stream.write(','.join(tokens) + newline)
        def quoted(s):
            # CPCe does not seem to have a way of escaping quote chars.
            # If there are any quote chars within a value, CPCe likely
            # won't read the file properly.
            # To minimize the potential for server errors and multi-field
            # data corruption (in the event these CPC files keep getting
            # passed between CPCe/CoralNet), we'll remove any quote chars
            # from the value.
            s = s.replace('"', '')
            return f'"{s}"'

        # Line 1: environment info and image dimensions
        writerow([
            quoted(self.code_filepath),
            quoted(self.image_filepath),
            self.image_width,
            self.image_height,
            self.display_width,
            self.display_height,
        ])

        # Lines 2-5: annotation area bounds
        writerow(self.annotation_area['bottom_left'])
        writerow(self.annotation_area['bottom_right'])
        writerow(self.annotation_area['top_right'])
        writerow(self.annotation_area['top_left'])

        # Line 6: number of points
        writerow([len(self.points)])

        # Next num_points lines: point positions
        for point in self.points:
            writerow([point['x'], point['y']])

        # Next num_points lines: point ID/Notes data
        for point in self.points:
            writerow([
                quoted(point['number_label']),
                quoted(point['id']),
                quoted('Notes'),
                quoted(point['notes']),
            ])

        # Header fields
        for header in self.headers:
            writerow([quoted(header)])

    def find_matching_image(self, source):

        # The image filepath follows the rules of the OS running CPCe,
        # not the rules of the server OS. So we don't use Path.
        # CPCe only runs on Windows, so we can assume it's a Windows
        # path. That means using PureWindowsPath (WindowsPath can only
        # be instantiated on a Windows OS).
        cpc_image_filepath = PureWindowsPath(self.image_filepath)
        image_filename = cpc_image_filepath.name

        # Match up the CPCe image filepath to an image name on CoralNet.
        #
        # Let's say the image filepath is D:\Site A\Transect 1\01.jpg
        # Example image names:
        # D:\Site A\Transect 1\01.jpg: best match
        # Site A\Transect 1\01.jpg: 2nd best match
        # Transect 1\01.jpg: 3rd best match
        # 01.jpg: 4th best match
        # Transect 1/01.jpg: same as with backslash
        # /Transect 1/01.jpg: same as without leading slash
        # 23.jpg: non-match 1
        # 4501.jpg: non-match 2
        # sect 1\01.jpg: non-match 3
        # (No, it's not as good as 01.jpg, it's just a non-match)
        #
        # First get names consisting of 01.jpg preceded by /, \, or nothing.
        # This avoids non-match 1 and non-match 2, presumably narrowing
        # things down to only a few image candidates.
        regex_escaped_filename = re.escape(image_filename)
        name_regex = r'^(.*[\\|/])?{fn}$'.format(fn=regex_escaped_filename)
        image_candidates = source.image_set.filter(
            metadata__name__regex=name_regex)

        # Find the best match while avoiding non-match 3. To do so, we
        # basically iterate over best match, 2nd best match, 3rd best
        # match, etc. and see if they exist.
        parts_to_match = cpc_image_filepath.parts
        while len(parts_to_match) > 0:
            for image_candidate in image_candidates:
                candidate_parts = PureWindowsPath(
                    image_candidate.metadata.name).parts
                # Ignore leading slashes.
                if candidate_parts[0] == '\\':
                    candidate_parts = candidate_parts[1:]
                # See if it's a match.
                if parts_to_match == candidate_parts:
                    # It's a match.
                    return image_candidate
            # No match this time; try to match one fewer part.
            parts_to_match = parts_to_match[1:]

        # There could be no matching image names in the source, in which
        # case this would be None. It could be an image the user is
        # planning to upload later, or an image they're not planning
        # to upload but are still tracking in their records.
        return None

    def get_image_dir(self, image_id: int) -> str:
        """
        Using the CPC's image filepath and the passed Image's name,
        deduce the directory where the CPC could reside on the origin PC.
        This is a best-effort function, not meant to be super reliable.
        """
        image = Image.objects.get(pk=image_id)
        cpc_path_parts = PureWindowsPath(self.image_filepath).parts
        image_name_path_parts = PureWindowsPath(image.metadata.name).parts

        # Find the longest match, starting from the right,
        # between cpc's and image name's paths.
        n = len(cpc_path_parts)
        while n > 0:
            if cpc_path_parts[-n:] == image_name_path_parts[-n:]:
                # Get the non-matching part of the cpc's path.
                image_dir = PureWindowsPath(*cpc_path_parts[:-n])
                return str(image_dir)
            n -= 1
        # Couldn't match.
        return ''

    def get_pixel_scale_factor(self, image):
        """
        Detect pixel scale factor - the scale of the x, y units CPCe used to
        express the point locations.

        This is normally 15 units per pixel, but
        that only holds when CPCe runs in 96 DPI. Earlier versions of CPCe
        (such as CPCe 3.5) did not enforce 96 DPI, so for example, it is
        possible to run in 120 DPI and get a scale of 12 units per pixel.

        We can figure out the scale factor by reading the .cpc file's image
        resolution values. These values are in CPCe's scale, and we know the
        resolution in pixels, so we can solve for the scale factor.
        """
        try:
            cpce_scale_width = int(self.image_width)
            cpce_scale_height = int(self.image_height)
        except ValueError:
            raise FileProcessError(
                "The image width and height on line 1 must be integers.")

        x_scale = cpce_scale_width / image.original_width
        y_scale = cpce_scale_height / image.original_height
        if (not x_scale.is_integer()
                or not y_scale.is_integer()
                or x_scale != y_scale):
            raise FileProcessError(
                "Could not establish an integer scale factor from line 1.")
        return x_scale

    def get_image_and_annotations(self, source, label_mapping):
        """
        Process the .cpc info as annotations for an image in the given source.
        """
        image = self.find_matching_image(source)
        if not image:
            return None, []

        image_name = image.metadata.name

        pixel_scale_factor = self.get_pixel_scale_factor(image)

        point_count = len(self.points)
        if point_count > settings.MAX_POINTS_PER_IMAGE:
            raise FileProcessError(
                f"Found {point_count} points, which exceeds the"
                f" maximum allowed of {settings.MAX_POINTS_PER_IMAGE}")

        annotations = []

        for point_number, cpc_point in enumerate(self.points, 1):

            # Check that row/column are integers within the image dimensions.
            # Convert from CPCe units to pixels in the meantime.

            try:
                y = int(cpc_point['y'])
                if y < 0:
                    raise ValueError
            except ValueError:
                raise FileProcessError((
                    f"Point {point_number}:"
                    f" Row should be a non-negative integer,"
                    f" not {cpc_point['y']}"))

            try:
                x = int(cpc_point['x'])
                if x < 0:
                    raise ValueError
            except ValueError:
                raise FileProcessError((
                    f"Point {point_number}:"
                    f" Column should be a non-negative integer,"
                    f" not {cpc_point['x']}"))

            # CPCe units -> pixels conversion.
            row = int(round(y / pixel_scale_factor))
            column = int(round(x / pixel_scale_factor))
            point_dict = dict(
                row=row,
                column=column,
            )

            if row > image.max_row:
                raise FileProcessError(
                    f"Point {point_number}:"
                    f" Row value of {y} corresponds to pixel {row}, but"
                    f" image {image_name} is only {image.original_height}"
                    f" pixels high (accepted values are 0~{image.max_row})")

            if column > image.max_column:
                raise FileProcessError(
                    f"Point {point_number}:"
                    f" Column value of {x} corresponds to pixel {column}, but"
                    f" image {image_name} is only {image.original_width}"
                    f" pixels wide (accepted values are 0~{image.max_column})")

            label_code = None
            cpc_id = cpc_point.get('id')
            cpc_notes = cpc_point.get('notes')
            if cpc_id:
                if cpc_notes and label_mapping == 'id_and_notes':
                    # Assumption: label code in CoralNet source's labelset
                    # == {ID}+{Notes} in the .cpc file (case insensitive).
                    label_code = \
                        f'{cpc_id}+{cpc_notes}'
                else:
                    # Assumption: label code in CoralNet source's labelset
                    # == label code in the .cpc file (case insensitive).
                    label_code = cpc_id

            if label_code:
                # Check that the label is in the labelset
                global_label = source.labelset.get_global_by_code(label_code)
                if not global_label:
                    raise FileProcessError(
                        f"Point {point_number}:"
                        f" No label of code {label_code} found"
                        f" in this source's labelset")
                point_dict['label'] = label_code

            annotations.append(point_dict)

        return image, annotations
