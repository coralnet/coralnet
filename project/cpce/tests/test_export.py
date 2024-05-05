from io import BytesIO
from zipfile import ZipFile

from bs4 import BeautifulSoup
from django.core.files.base import ContentFile
from django.urls import reverse
from django.utils.html import escape as html_escape

from images.models import Image
from lib.tests.utils import BasePermissionTest, ClientTest
from upload.tests.utils import UploadAnnotationsCsvTestMixin
from ..utils import get_previous_cpcs_status


class PermissionTest(BasePermissionTest):

    def test_cpc_create_ajax(self):
        url = reverse(
            'cpce:export_prepare_ajax', args=[self.source.pk])

        self.source_to_private()
        self.assertPermissionLevel(
            url, self.SOURCE_EDIT, is_json=True, post_data={})
        self.source_to_public()
        self.assertPermissionLevel(
            url, self.SOURCE_EDIT, is_json=True, post_data={})

    def test_cpc_serve(self):
        # Without session variables from export-prepare, this should redirect
        # to browse images.
        url = reverse('cpce:export_serve', args=[self.source.pk])
        template = 'visualization/browse_images.html'

        self.source_to_private()
        self.assertPermissionLevel(url, self.SOURCE_EDIT, template=template)
        self.source_to_public()
        self.assertPermissionLevel(url, self.SOURCE_EDIT, template=template)


class CPCExportBaseTest(ClientTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        # Image search parameters
        cls.default_search_params = dict(
            image_form_type='search',
            aux1='', aux2='', aux3='', aux4='', aux5='',
            height_in_cm='', latitude='', longitude='', depth='',
            photographer='', framing='', balance='',
            photo_date_0='', photo_date_1='', photo_date_2='',
            photo_date_3='', photo_date_4='',
            image_name='', annotation_status='',
            last_annotated_0='', last_annotated_1='', last_annotated_2='',
            last_annotated_3='', last_annotated_4='',
            last_annotator_0='', last_annotator_1='',
            sort_method='name', sort_direction='asc',
        )
        cls.default_export_params = cls.default_search_params.copy()
        cls.default_export_params.update(
            override_filepaths='no',
            local_code_filepath='D:/Surveys/Codefile.txt',
            local_image_dir='D:/Surveys/Images',
            annotation_filter='confirmed_only',
            label_mapping='id_only',
        )

    def export_cpcs(self, post_data):
        """
        :param post_data: The POST data for the CPC-creation Ajax view.
        :return: The response object from the CPC-serving view. Should be a
          zip file raw string if the view ran without errors.
        """
        self.client.force_login(self.user)
        prepare_response = self.client.post(
            reverse('cpce:export_prepare_ajax', args=[self.source.pk]),
            post_data,
        )
        timestamp = prepare_response.json()['session_data_timestamp']
        return self.client.get(
            reverse('cpce:export_serve', args=[self.source.pk]),
            dict(session_data_timestamp=timestamp),
        )

    @staticmethod
    def export_response_to_cpc(response, cpc_filename):
        zf = ZipFile(BytesIO(response.content))
        # Use decode() to get a Unicode string
        return zf.read(cpc_filename).decode()

    def upload_cpcs(self, cpc_files, label_mapping='id_only'):
        self.client.force_login(self.user)
        self.client.post(
            reverse('cpce:upload_preview_ajax', args=[self.source.pk]),
            {'cpc_files': cpc_files, 'label_mapping': label_mapping})
        self.client.post(
            reverse('cpce:upload_confirm_ajax', args=[self.source.pk]))

    def assert_cpc_content_equal(self, actual_cpc_content, expected_lines):
        """
        Tests that an entire CPC's content is as expected.

        :param actual_cpc_content: CPC content from the export view's response.
        :param expected_lines: List of strings, without newline characters,
          representing the expected line contents. Note that this is a
          different format from actual_cpc_content, just because it's easier
          to type non-newline strings in Python code.
        Throws AssertionError if actual and expected CPCs are not equal.
        """
        actual_lines = actual_cpc_content.splitlines()

        # Yes, CPCe does put a newline at the end
        expected_cpc_content = '\r\n'.join(expected_lines) + '\r\n'

        # Compare individual lines (so that if we get a mismatch, the error
        # message will be readable)
        for line_num, actual_line in enumerate(actual_lines, 1):
            expected_line = expected_lines[line_num-1]
            self.assertEqual(actual_line, expected_line, msg=(
                "Line {line_num} not equal | Actual: {actual_line}"
                " | Expected: {expected_line}").format(
                line_num=line_num, actual_line=actual_line,
                expected_line=expected_line,
            ))
        # Compare entire file (to ensure line separator types are correct too)
        self.assertEqual(actual_cpc_content, expected_cpc_content)

    def assert_cpc_label_lines_equal(
            self, actual_cpc_content, expected_point_lines):
        """
        Tests that a CPC's label lines (the lines with the label codes)
        are as expected.
        """
        actual_lines = actual_cpc_content.splitlines()

        # The "point lines" are located before the final 28 lines (the header
        # lines).
        point_count = len(expected_point_lines)
        actual_point_lines = actual_lines[-(28+point_count):-28]

        # Compare individual lines (so that if we get a mismatch, the error
        # message will be readable)
        for point_num, actual_line in enumerate(actual_point_lines, 1):
            expected_line = expected_point_lines[point_num-1]
            self.assertEqual(actual_line, expected_line, msg=(
                "Line for point {point_num} not equal | Actual: {actual_line}"
                " | Expected: {expected_line}").format(
                point_num=point_num, actual_line=actual_line,
                expected_line=expected_line,
            ))

    @staticmethod
    def get_form_soup(response):
        response_soup = BeautifulSoup(response.content, 'html.parser')
        return response_soup.find(
            'form', dict(id='export-annotations-cpc-ajax-form'))

    def assert_field_hidden(self, response, field_name):
        field = self.get_form_soup(response).find(
            'input', dict(name=field_name))
        self.assertEqual(field.attrs.get('type'), 'hidden')

    def assert_field_not_hidden(self, response, field_name):
        field = self.get_form_soup(response).find(
            'input', dict(name=field_name))
        self.assertNotEqual(field.attrs.get('type'), 'hidden')


class FilepathFieldsTest(CPCExportBaseTest):
    """
    Ensure the code filepath, image directory, and override filepaths form
    fields work as intended.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user,
            # 1 point per image
            default_point_generation_method=dict(
                type='uniform', cell_rows=1, cell_columns=1),
            confidence_threshold=80,
        )
        labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, labels)

        # The X and Y suffixes allow us to group at least two images together
        # when searching by image name.
        cls.img1 = cls.upload_image(
            cls.user, cls.source,
            dict(filename='1_X.jpg', width=400, height=300))
        cls.img2 = cls.upload_image(
            cls.user, cls.source,
            dict(filename='2_X.jpg', width=400, height=300))
        cls.img3 = cls.upload_image(
            cls.user, cls.source,
            dict(filename='3_Y.jpg', width=400, height=300))

    def upload_cpc(self, code_filepath, image_filepath, cpc_filename):
        cpc_lines = [
            ('"' + code_filepath + '",'
             '"' + image_filepath + '",6000,4500,20000,25000'),
            '285,4035',
            '5685,4035',
            '5685,435',
            '285,435',
            '1',
            '1000,1000',
            '"1","A","Notes","AC"',
        ]
        cpc_lines.extend(['""']*28)
        cpc_content = '\r\n'.join(cpc_lines) + '\r\n'

        f = ContentFile(cpc_content, name=cpc_filename)
        self.upload_cpcs([f])

    def assert_form_filepaths_equal(
            self, response, code_filepath, image_dir):

        code_filepath_field = self.get_form_soup(response).find(
            'input', dict(id='id_local_code_filepath'))
        self.assertEqual(code_filepath_field.attrs.get('value'), code_filepath)

        image_dir_field = self.get_form_soup(response).find(
            'input', dict(id='id_local_image_dir'))
        self.assertEqual(image_dir_field.attrs.get('value'), image_dir)

    def test_form_init_when_all_images_in_search_have_cpcs(self):
        # Upload CPC for images 1 and 2
        self.upload_cpc(r'C:\codefile.txt', r'C:\Reef data\1_X.jpg', '1_X.cpc')
        self.upload_cpc(r'C:\codefile.txt', r'C:\Reef data\2_X.jpg', '2_X.cpc')

        # Search includes images 1 and 2, but not 3
        self.client.force_login(self.user)
        post_data = self.default_search_params.copy()
        post_data.update(image_name='X')
        response = self.client.post(
            reverse('browse_images', args=[self.source.pk]),
            data=post_data, follow=True)

        self.assert_form_filepaths_equal(
            response, r'C:\codefile.txt', r'C:\Reef data')
        self.assert_field_not_hidden(response, 'override_filepaths')
        self.assertContains(
            response,
            "<strong>All of the images</strong> in this search"
            " have previously-uploaded CPC files available.")

    def test_form_init_when_some_images_in_search_have_cpcs(self):
        # Upload CPC for images 1 and 2
        self.upload_cpc(r'C:\codefile.txt', r'C:\Reef data\1_X.jpg', '1_X.cpc')
        self.upload_cpc(r'C:\codefile.txt', r'C:\Reef data\2_X.jpg', '2_X.cpc')

        # Search includes all images (1, 2, and 3)
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('browse_images', args=[self.source.pk]))

        self.assert_form_filepaths_equal(
            response, r'C:\codefile.txt', r'C:\Reef data')
        self.assert_field_not_hidden(response, 'override_filepaths')
        self.assertContains(
            response,
            "<strong>Some of the images</strong> in this search"
            " have previously-uploaded CPC files available.")

    def test_form_init_when_no_images_in_search_have_cpcs(self):
        # Upload CPC for images 1 and 2
        self.upload_cpc(r'C:\codefile.txt', r'C:\Reef data\1_X.jpg', '1_X.cpc')
        self.upload_cpc(r'C:\codefile.txt', r'C:\Reef data\2_X.jpg', '2_X.cpc')

        # Search includes image 3 only
        self.client.force_login(self.user)
        post_data = self.default_search_params.copy()
        post_data.update(image_name='Y')
        response = self.client.post(
            reverse('browse_images', args=[self.source.pk]),
            data=post_data, follow=True)

        self.assert_form_filepaths_equal(
            response, r'C:\codefile.txt', r'C:\Reef data')
        self.assert_field_hidden(response, 'override_filepaths')
        self.assertContains(
            response,
            "<strong>None of the images</strong> in this search"
            " have previously-uploaded CPC files available.")

    def test_form_init_when_no_cpcs_ever_uploaded(self):
        # All images
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('browse_images', args=[self.source.pk]))

        # Blank fields
        self.assert_form_filepaths_equal(
            response, None, None)
        self.assertContains(
            response,
            "<strong>None of the images</strong> in this search"
            " have previously-uploaded CPC files available.")

    def test_form_init_uses_values_from_latest_cpc_upload(self):
        # Upload CPC for images 1 and 2. Use different codefile and image dir
        # for each.
        self.upload_cpc(r'C:\codefile_1.txt', r'C:\Reef 1\1_X.jpg', '1_X.cpc')
        self.upload_cpc(r'C:\codefile_2.txt', r'C:\Reef 2\2_X.jpg', '2_X.cpc')

        # All images
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('browse_images', args=[self.source.pk]))

        # The later upload's data should be used, not the earlier upload's data
        self.assert_form_filepaths_equal(
            response, r'C:\codefile_2.txt', r'C:\Reef 2')

    def test_form_init_uses_values_from_latest_cpc_export(self):
        # Upload a CPC
        self.upload_cpc(r'C:\codefile_2.txt', r'C:\Reef 2\2_X.jpg', '2_X.cpc')

        # Do a CPC export
        post_data = self.default_export_params.copy()
        post_data.update(
            # CPC prefs
            local_code_filepath=r'C:\codefile_1.txt',
            local_image_dir=r'C:\Reef 1',
        )
        self.export_cpcs(post_data)

        response = self.client.get(
            reverse('browse_images', args=[self.source.pk]))

        # The export's data should be used, not the earlier upload's data
        self.assert_form_filepaths_equal(
            response, r'C:\codefile_1.txt', r'C:\Reef 1')

    def test_code_filepath_required(self):
        post_data = self.default_export_params.copy()
        post_data.update(
            local_code_filepath=r'',
            local_image_dir=r'C:\Reef 1',
        )
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('cpce:export_prepare_ajax', args=[self.source.pk]),
            post_data)

        self.assertEqual(
            response.json()['error'], "Code file: This field is required.")

    def test_image_dir_required(self):
        post_data = self.default_export_params.copy()
        post_data.update(
            local_code_filepath=r'C:\codefile_1.txt',
            local_image_dir='',
        )
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('cpce:export_prepare_ajax', args=[self.source.pk]),
            post_data)

        self.assertEqual(
            response.json()['error'],
            "Folder with images: This field is required.")

    def test_image_search_params_must_be_valid(self):
        post_data = self.default_export_params.copy()
        post_data.update(
            local_code_filepath=r'C:\codefile_1.txt',
            local_image_dir=r'C:\Reef 1',
            photo_date_0='date',
            photo_date_2='not a date',
        )
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('cpce:export_prepare_ajax', args=[self.source.pk]),
            post_data)

        self.assertEqual(
            response.json()['error'],
            "Image-search parameters were invalid.")

    def test_override_filepaths_no(self):
        # Upload a CPC
        self.upload_cpc(r'C:\uploaded.txt', r'C:\Uploaded\2_X.jpg', '2_X.cpc')

        # Export CPCs for all images, with fields specifying a different
        # codefile and image dir
        post_data = self.default_export_params.copy()
        post_data.update(
            local_code_filepath=r'C:\fields.txt',
            local_image_dir=r'C:\Fields',
            override_filepaths='no',
        )
        response = self.export_cpcs(post_data)

        cpc_1_content = self.export_response_to_cpc(response, '1_X.cpc')
        first_line = cpc_1_content.splitlines()[0]
        self.assertTrue(
            first_line.startswith(r'"C:\fields.txt","C:\Fields\1_X.jpg",'),
            msg="CPC for image 1 should use the form's values")

        cpc_2_content = self.export_response_to_cpc(response, '2_X.cpc')
        first_line = cpc_2_content.splitlines()[0]
        self.assertTrue(
            first_line.startswith(r'"C:\uploaded.txt","C:\Uploaded\2_X.jpg",'),
            msg="CPC for image 2 should use the previously-uploaded values")

    def test_override_filepaths_yes(self):
        # Upload a CPC
        self.upload_cpc(r'C:\uploaded.txt', r'C:\Uploaded\2_X.jpg', '2_X.cpc')

        # Export CPCs for all images, with fields specifying a different
        # codefile and image dir
        post_data = self.default_export_params.copy()
        post_data.update(
            local_code_filepath=r'C:\fields.txt',
            local_image_dir=r'C:\Fields',
            override_filepaths='yes',
        )
        response = self.export_cpcs(post_data)

        cpc_1_content = self.export_response_to_cpc(response, '1_X.cpc')
        first_line = cpc_1_content.splitlines()[0]
        self.assertTrue(
            first_line.startswith(r'"C:\fields.txt","C:\Fields\1_X.jpg",'),
            msg="CPC for image 1 should use the form's values")

        cpc_2_content = self.export_response_to_cpc(response, '2_X.cpc')
        first_line = cpc_2_content.splitlines()[0]
        self.assertTrue(
            first_line.startswith(r'"C:\fields.txt","C:\Fields\2_X.jpg",'),
            msg="CPC for image 2 should use the form's values")


class AnnotationAreaTest(
        CPCExportBaseTest, UploadAnnotationsCsvTestMixin):
    """
    Test the annotation area values of the exported CPCs, using various ways
    of setting the annotation area.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user,
            image_annotation_area=dict(min_x=5, max_x=95, min_y=10, max_y=90))
        labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, labels)

        cls.img1 = cls.upload_image(
            cls.user, cls.source,
            dict(filename='1.jpg', width=400, height=300))

    def test_percentages(self):
        """Test using source-default annotation area."""
        response = self.export_cpcs(self.default_export_params)

        cpc_content = self.export_response_to_cpc(response, '1.cpc')
        actual_area_lines = cpc_content.splitlines()[1:5]

        # Width ranges from 5% to 95% of 400. That's pixel 19 to pixel 379.
        # Height ranges from 10% to 90% of 300. That's pixel 29 to pixel 269.
        # 19*15 = 285, 379*15 = 4035, 29*15 = 435, 269*15 = 5685
        expected_area_lines = [
            '285,4035',
            '5685,4035',
            '5685,435',
            '285,435',
        ]
        self.assertListEqual(
            actual_area_lines, expected_area_lines)


    def test_pixels(self):
        """Test using an image-specific annotation area."""
        self.client.force_login(self.user)
        self.client.post(
            reverse('annotation_area_edit', args=[self.img1.pk]),
            data=dict(min_x=50, max_x=200, min_y=100, max_y=290),
        )

        response = self.export_cpcs(self.default_export_params)

        cpc_content = self.export_response_to_cpc(response, '1.cpc')
        actual_area_lines = cpc_content.splitlines()[1:5]

        # Width ranges from 50*15 to 200*15.
        # Height ranges from 100*15 to 290*15.
        expected_area_lines = [
            '750,4350',
            '3000,4350',
            '3000,1500',
            '750,1500',
        ]
        self.assertListEqual(
            actual_area_lines, expected_area_lines)

    def test_imported(self):
        """
        Test after CSV-importing points, which means we just use the full image
        as the annotation area.
        """
        rows = [
            ['Name', 'Column', 'Row'],
            ['1.jpg', 50, 50],
            ['1.jpg', 60, 40],
        ]
        csv_file = self.make_annotations_file('A.csv', rows)
        self.preview_annotations(
            self.user, self.source, csv_file)
        self.upload_annotations(self.user, self.source)

        response = self.export_cpcs(self.default_export_params)

        cpc_content = self.export_response_to_cpc(response, '1.cpc')
        actual_area_lines = cpc_content.splitlines()[1:5]

        # Width ranges from 0*15 to (400-1)*15.
        # Height ranges from 0*15 to (300-1)*15.
        expected_area_lines = [
            '0,4485',
            '5985,4485',
            '5985,0',
            '0,0',
        ]
        self.assertListEqual(
            actual_area_lines, expected_area_lines)

    def test_after_cpc_upload(self):
        """
        Test after CPC-importing points, which means we use the annotation
        area from the CPC.
        """
        cpc_lines = [
            (r'"C:\codefile_1.txt",'
             r'"C:\Reef 1\1.jpg",6000,4500,20000,25000'),
            # Different annotation area from the source's default
            '210,4101',
            '5329,4101',
            '5329,607',
            '210,607',
            # Points
            '1',
            (str(319*15) + ',' + str(88*15)),
            # Labels/notes
            '"1","A","Notes","AC"',
        ]
        cpc_lines.extend(['"Header value goes here"']*28)
        # Yes, CPCe does put a newline at the end
        cpc_content = '\r\n'.join(cpc_lines) + '\r\n'

        f = ContentFile(cpc_content, name='1.cpc')
        self.upload_cpcs([f])

        response = self.export_cpcs(self.default_export_params)

        cpc_content = self.export_response_to_cpc(response, '1.cpc')
        actual_area_lines = cpc_content.splitlines()[1:5]

        # Should match the uploaded CPC.
        expected_area_lines = [
            '210,4101',
            '5329,4101',
            '5329,607',
            '210,607',
        ]
        self.assertListEqual(
            actual_area_lines, expected_area_lines)


class PointLocationsTest(CPCExportBaseTest, UploadAnnotationsCsvTestMixin):
    """
    Test the point location values of the exported CPCs.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user,
            # 2 points per image
            default_point_generation_method=dict(
                type='uniform', cell_rows=1, cell_columns=2))
        labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, labels)

        cls.img1 = cls.upload_image(
            cls.user, cls.source,
            dict(filename='1.jpg', width=400, height=300))

    def test_generated_points(self):
        """Test using points generated on image-upload time."""
        response = self.export_cpcs(self.default_export_params)

        cpc_content = self.export_response_to_cpc(response, '1.cpc')
        actual_point_lines = cpc_content.splitlines()[6:8]

        expected_point_lines = [
            # 99*15, 149*15
            '1485,2235',
            # 299*15, 149*15
            '4485,2235',
        ]
        self.assertListEqual(
            actual_point_lines, expected_point_lines)

    def test_csv_imported_points(self):
        """Test using points imported from CSV."""
        rows = [
            ['Name', 'Column', 'Row'],
            ['1.jpg', 50, 50],
            ['1.jpg', 60, 40],
        ]
        csv_file = self.make_annotations_file('A.csv', rows)
        self.preview_annotations(
            self.user, self.source, csv_file)
        self.upload_annotations(self.user, self.source)

        response = self.export_cpcs(self.default_export_params)

        cpc_content = self.export_response_to_cpc(response, '1.cpc')
        actual_point_lines = cpc_content.splitlines()[6:8]

        expected_point_lines = [
            # 50*15, 50*15
            '750,750',
            # 60*15, 40*15
            '900,600',
        ]
        self.assertListEqual(
            actual_point_lines, expected_point_lines)

    # CPC-import case is tested in CPCFullContentsTest. Upload CPC, then
    # export, get same CPC back.


class CPCFullContentsTest(CPCExportBaseTest, UploadAnnotationsCsvTestMixin):
    """
    Test the full contents of the exported CPCs.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)
        labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, labels)

        cls.img1 = cls.upload_image(
            cls.user, cls.source,
            dict(filename='1.jpg', width=400, height=300))
        cls.img2 = cls.upload_image(
            cls.user, cls.source, dict(filename='2.jpg'))

    def test_export_with_no_cpcs_saved(self):
        """
        Export in the case where we don't have a previously uploaded CPC file
        available, meaning we have to write a CPC from scratch.
        """
        # Upload points via CSV.
        rows = [
            ['Name', 'Column', 'Row'],
            ['1.jpg', 50, 50],
            ['1.jpg', 60, 40],
        ]
        csv_file = self.make_annotations_file('A.csv', rows)
        self.preview_annotations(
            self.user, self.source, csv_file)
        self.upload_annotations(self.user, self.source)

        # Add annotations. Not to all points, so we can test the label
        # lines with and without labels.
        self.add_annotations(
            self.user, self.img1, {1: 'A'})

        # Export, and get exported CPC content
        post_data = self.default_export_params.copy()
        post_data.update(
            # CPC prefs
            local_code_filepath=r'C:\CPCe codefiles\My codes.txt',
            local_image_dir=r'C:\Panama dataset',
        )
        response = self.export_cpcs(post_data)
        actual_cpc_content = self.export_response_to_cpc(response, '1.cpc')

        # This is what we expect to get in our export
        expected_lines = [
            # Should match the CPC-prefs code filepath, CPC-prefs image dir,
            # uploaded image filename, and uploaded image resolution
            (r'"C:\CPCe codefiles\My codes.txt",'
             r'"C:\Panama dataset\1.jpg",6000,4500,14400,10800'),
            # Should match the annotation area (full image, due to
            # CSV-imported points)
            '0,4485',
            '5985,4485',
            '5985,0',
            '0,0',
            # Should match the number of points
            '2',
            # Should match the point positions
            (str(50*15) + ',' + str(50*15)),
            (str(60*15) + ',' + str(40*15)),
            # Should match the annotations that were added. Without a previous
            # CPC, we just have blank notes
            '"1","A","Notes",""',
            '"2","","Notes",""',
        ]
        # Blank header fields
        expected_lines.extend(['""']*28)

        self.assert_cpc_content_equal(actual_cpc_content, expected_lines)

    def test_upload_cpc_then_export(self):
        """
        Upload .cpc for an image, then export .cpc for that same image. Should
        get the same .cpc contents back.
        """
        cpc_lines = [
            # Different working resolution (last two numbers) from the default
            (r'"C:\CPCe codefiles\My codes.txt",'
             r'"C:\Panama dataset\1.jpg",6000,4500,20000,25000'),
            # Different annotation area from the source's default
            '210,4101',
            '5329,4101',
            '5329,607',
            '210,607',
            # Different number of points from the source's default
            '3',
            (str(319*15) + ',' + str(88*15)),
            (str(78*15) + ',' + str(209*15)),
            (str(198*15) + ',' + str(209*15)),
            # Include notes codes
            '"1","A","Notes","AC"',
            '"2","B","Notes","BD"',
            '"3","","Notes","AC"',
        ]
        # Add some non-blank header values
        cpc_lines.extend(['"Header value goes here"']*28)
        # Yes, CPCe does put a newline at the end
        cpc_content = '\r\n'.join(cpc_lines) + '\r\n'

        # Upload with a CPC filename different from the image filename
        f = ContentFile(cpc_content, name='Panama_1.cpc')
        self.upload_cpcs([f])

        # Export, and get exported CPC content
        post_data = self.default_export_params.copy()
        post_data.update(
            # CPC prefs
            local_code_filepath=r'C:\CPCe codefiles\My codes.txt',
            local_image_dir=r'C:\Panama dataset',
        )
        response = self.export_cpcs(post_data)
        actual_cpc_content = self.export_response_to_cpc(
            response, 'Panama_1.cpc')

        self.assert_cpc_content_equal(actual_cpc_content, cpc_lines)

    def test_upload_cpc_then_change_annotations_then_export(self):
        """
        Upload .cpc for an image, then change annotations on the image, then
        export .cpc.
        """
        cpc_lines = [
            # Different working resolution (last two numbers) from the default
            (r'"C:\CPCe codefiles\My codes.txt",'
             r'"C:\Panama dataset\1.jpg",6000,4500,20000,25000'),
            # Different annotation area from the source's default
            '210,4101',
            '5329,4101',
            '5329,607',
            '210,607',
            # Different number of points from the source's default
            '3',
            (str(319*15) + ',' + str(88*15)),
            (str(78*15) + ',' + str(209*15)),
            (str(198*15) + ',' + str(209*15)),
            # Include notes codes
            '"1","A","Notes","AC"',
            '"2","B","Notes","BD"',
            '"3","","Notes","AC"',
        ]
        # Add some non-blank header values
        cpc_lines.extend(['"Header value goes here"']*28)
        # Yes, CPCe does put a newline at the end
        cpc_content = '\r\n'.join(cpc_lines) + '\r\n'

        # Upload with a CPC filename different from the image filename
        f = ContentFile(cpc_content, name='Panama_1.cpc')
        self.upload_cpcs([f])

        # Change some annotations; we expect the CPC file to be the same
        # except for the changed labels. Notes codes should be preserved.
        # 1 = unchanged, 2 = changed, 3 = new.
        annotations = {2: 'A', 3: 'B'}
        self.add_annotations(self.user, self.img1, annotations)
        expected_lines = cpc_lines[:]
        expected_lines[10] = '"2","A","Notes","BD"'
        expected_lines[11] = '"3","B","Notes","AC"'

        # Export, and get exported CPC content
        post_data = self.default_export_params.copy()
        post_data.update(
            # CPC prefs
            local_code_filepath=r'C:\CPCe codefiles\My codes.txt',
            local_image_dir=r'C:\Panama dataset',
        )
        response = self.export_cpcs(post_data)
        actual_cpc_content = self.export_response_to_cpc(
            response, 'Panama_1.cpc')

        self.assert_cpc_content_equal(actual_cpc_content, expected_lines)


class AnnotationFilterTest(CPCExportBaseTest):
    """
    Ensure the annotation filter preference of the CPC prefs form works.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user,
            default_point_generation_method=dict(type='simple', points=3),
            confidence_threshold=80,
        )
        labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, labels)

        cls.img1 = cls.upload_image(
            cls.user, cls.source, dict(filename='1.jpg'))

        # Unconfirmed annotations
        cls.add_robot_annotations(
            cls.create_robot(cls.source), cls.img1,
            # 1. Dummy, to be replaced with confirmed. This function wants
            # annotations for all points.
            # 2. Less than confidence threshold
            # 3. Greater than threshold
            # We're dealing with floats in general, so equality isn't all
            # that useful to test.
            {1: ('A', 60), 2: ('B', 79), 3: ('A', 81)})
        # Confirmed annotations
        cls.add_annotations(
            cls.user, cls.img1, {1: 'A'})

    def test_only_show_field_if_confidence_threshold_less_than_100(self):
        self.client.force_login(self.user)

        # 0 confidence: the field is shown, no special styling
        self.source.confidence_threshold = 0
        self.source.save()
        response = self.client.get(
            reverse('browse_images', args=[self.source.pk]))
        self.assert_field_not_hidden(response, 'annotation_filter')

        # 99 confidence: the field is shown, no special styling
        self.source.confidence_threshold = 99
        self.source.save()
        response = self.client.get(
            reverse('browse_images', args=[self.source.pk]))
        self.assert_field_not_hidden(response, 'annotation_filter')

        # 100 confidence: the field is hidden via inline style
        self.source.confidence_threshold = 100
        self.source.save()
        response = self.client.get(
            reverse('browse_images', args=[self.source.pk]))
        self.assert_field_hidden(response, 'annotation_filter')

    def test_confirmed_only(self):
        """
        Requesting confirmed annotations only.
        """
        post_data = self.default_export_params.copy()
        post_data.update(
            annotation_filter='confirmed_only',
        )
        response = self.export_cpcs(post_data)
        actual_cpc_content = self.export_response_to_cpc(response, '1.cpc')

        expected_point_lines = [
            '"1","A","Notes",""',
            '"2","","Notes",""',
            '"3","","Notes",""',
        ]
        self.assert_cpc_label_lines_equal(
            actual_cpc_content, expected_point_lines)

    def test_with_unconfirmed_confident(self):
        """
        Including unconfirmed confident annotations.
        """
        post_data = self.default_export_params.copy()
        post_data.update(
            annotation_filter='confirmed_and_confident',
        )
        response = self.export_cpcs(post_data)
        actual_cpc_content = self.export_response_to_cpc(response, '1.cpc')

        expected_point_lines = [
            '"1","A","Notes",""',
            '"2","","Notes",""',
            '"3","A","Notes",""',
        ]
        self.assert_cpc_label_lines_equal(
            actual_cpc_content, expected_point_lines)


class LabelMappingTest(CPCExportBaseTest):
    """
    Ensure the label mapping option works.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user,
            default_point_generation_method=dict(type='simple', points=3),
        )
        labels = cls.create_labels(
            cls.user, ['A', 'B+X', 'C+Y+Z'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, labels)

        cls.img1 = cls.upload_image(
            cls.user, cls.source,
            dict(filename='1.jpg', width=100, height=100))

    def test_id_and_notes(self):
        self.add_annotations(
            self.user, self.img1, {1: 'A', 2: 'B+X', 3: 'C+Y+Z'})

        post_data = self.default_export_params.copy()
        post_data.update(
            label_mapping='id_and_notes',
        )
        response = self.export_cpcs(post_data)
        actual_cpc_content = self.export_response_to_cpc(response, '1.cpc')

        expected_point_lines = [
            '"1","A","Notes",""',
            '"2","B","Notes","X"',
            '"3","C","Notes","Y+Z"',
        ]
        self.assert_cpc_label_lines_equal(
            actual_cpc_content, expected_point_lines)

    def test_id_only(self):
        self.add_annotations(
            self.user, self.img1, {1: 'A', 2: 'B+X', 3: 'C+Y+Z'})

        post_data = self.default_export_params.copy()
        post_data.update(
            label_mapping='id_only',
        )
        response = self.export_cpcs(post_data)
        actual_cpc_content = self.export_response_to_cpc(response, '1.cpc')

        expected_point_lines = [
            '"1","A","Notes",""',
            '"2","B+X","Notes",""',
            '"3","C+Y+Z","Notes",""',
        ]
        self.assert_cpc_label_lines_equal(
            actual_cpc_content, expected_point_lines)

    def test_upload_and_export_with_notes(self):
        point_lines = [
            '"1","A","Notes",""',
            '"2","B","Notes","X"',
            '"3","C","Notes","Y+Z"',
        ]
        cpc_lines = [
            # Different working resolution (last two numbers) from the default
            (r'"C:\CPCe codefiles\My codes.txt",'
             r'"C:\Panama dataset\1.jpg",1500,1500,3000,3000'),
            '0,1485',
            '1485,1485',
            '1485,0',
            '0,0',
            '3',
            (str(50*15) + ',' + str(50*15)),
            (str(60*15) + ',' + str(40*15)),
            (str(70*15) + ',' + str(30*15)),
        ]
        cpc_lines.extend(point_lines)
        # Write some non-blank header values to ensure those are kept in
        # the upload -> export process.
        cpc_lines.extend(['"Header value"']*28)
        cpc_content = '\r\n'.join(cpc_lines) + '\r\n'

        # Upload
        f = ContentFile(cpc_content, name='1.cpc')
        self.upload_cpcs([f], label_mapping='id_and_notes')

        # Export
        post_data = self.default_export_params.copy()
        post_data.update(
            label_mapping='id_and_notes',
        )
        response = self.export_cpcs(post_data)
        actual_cpc_content = self.export_response_to_cpc(response, '1.cpc')

        self.assert_cpc_content_equal(actual_cpc_content, cpc_lines)

    def test_form_init_no_plus_code(self):
        # Ensure the labelset has no label codes with + chars in them.
        local_bx = self.source.labelset.get_labels().get(code='B+X')
        local_bx.code = 'B'
        local_bx.save()
        local_cyz = self.source.labelset.get_labels().get(code='C+Y+Z')
        local_cyz.code = 'C'
        local_cyz.save()

        self.client.force_login(self.user)
        response = self.client.get(
            reverse('browse_images', args=[self.source.pk]))

        response_soup = BeautifulSoup(response.content, 'html.parser')
        label_mapping_selected_radio = response_soup.find(
            'input', dict(name='label_mapping'), checked=True)
        self.assertEqual(
            label_mapping_selected_radio.attrs.get('value'), 'id_only',
            "Should select ID only by default")

    def test_form_init_with_plus_code(self):
        # Keep the labelset as-is, with label codes with + chars.

        self.client.force_login(self.user)
        response = self.client.get(
            reverse('browse_images', args=[self.source.pk]))

        response_soup = BeautifulSoup(response.content, 'html.parser')
        label_mapping_selected_radio = response_soup.find(
            'input', dict(name='label_mapping'), checked=True)
        self.assertEqual(
            label_mapping_selected_radio.attrs.get('value'), 'id_and_notes',
            "Should select ID and notes by default")


class CPCDirectoryTreeTest(CPCExportBaseTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)
        labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, labels)

        # Upload images with names that indicate a directory tree
        cls.img1 = cls.upload_image(
            cls.user, cls.source, dict(filename='Site A/Transect I/1.jpg'))
        cls.img2 = cls.upload_image(
            cls.user, cls.source, dict(filename='Site A/Transect I/2.jpg'))
        cls.img3 = cls.upload_image(
            cls.user, cls.source, dict(filename='Site A/Transect II/1.jpg'))
        cls.img4 = cls.upload_image(
            cls.user, cls.source, dict(filename='Site B/Transect I/2.jpg'))
        cls.img5 = cls.upload_image(
            cls.user, cls.source, dict(filename='Site B/Transect III/4.jpg'))

    def test_export_directory_tree_of_cpcs(self):
        post_data = self.default_export_params.copy()
        post_data.update(
            # CPC prefs
            local_code_filepath=r'D:\codefile_1.txt',
            local_image_dir=r'D:\GBR',
        )
        response = self.export_cpcs(post_data)

        cpc = self.export_response_to_cpc(response, 'Site A/Transect I/1.cpc')
        first_line = cpc.splitlines()[0]
        self.assertTrue(first_line.startswith(
            r'"D:\codefile_1.txt","D:\GBR\Site A\Transect I\1.jpg"'))

        cpc = self.export_response_to_cpc(response, 'Site A/Transect I/2.cpc')
        first_line = cpc.splitlines()[0]
        self.assertTrue(first_line.startswith(
            r'"D:\codefile_1.txt","D:\GBR\Site A\Transect I\2.jpg"'))

        cpc = self.export_response_to_cpc(response, 'Site A/Transect II/1.cpc')
        first_line = cpc.splitlines()[0]
        self.assertTrue(first_line.startswith(
            r'"D:\codefile_1.txt","D:\GBR\Site A\Transect II\1.jpg"'))

        cpc = self.export_response_to_cpc(response, 'Site B/Transect I/2.cpc')
        first_line = cpc.splitlines()[0]
        self.assertTrue(first_line.startswith(
            r'"D:\codefile_1.txt","D:\GBR\Site B\Transect I\2.jpg"'))

        cpc = self.export_response_to_cpc(response, 'Site B/Transect III/4.cpc')
        first_line = cpc.splitlines()[0]
        self.assertTrue(first_line.startswith(
            r'"D:\codefile_1.txt","D:\GBR\Site B\Transect III\4.jpg"'))


class UnicodeTest(CPCExportBaseTest):
    """Test that non-ASCII characters don't cause problems. Don't know if CPC
    with non-ASCII is possible in practice, but might as well test that it
    works."""
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(
            cls.user,
            default_point_generation_method=dict(type='simple', points=3),
        )

        labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, labels)
        # Unicode custom label code
        local_label = cls.source.labelset.locallabel_set.get(code='B')
        local_label.code = 'い'
        local_label.save()

        cls.img1 = cls.upload_image(
            cls.user, cls.source, dict(
                filename='あ.jpg', width=100, height=100))

    def test(self):
        self.add_annotations(
            self.user, self.img1, {1: 'い'})

        post_data = self.default_export_params.copy()
        post_data.update(
            # CPC prefs
            local_code_filepath=r'C:\CPCe codefiles\コード.txt',
            local_image_dir=r'C:\パナマ',
        )
        response = self.export_cpcs(post_data)
        actual_cpc_content = self.export_response_to_cpc(response, 'あ.cpc')

        expected_first_line_beginning = (
            r'"C:\CPCe codefiles\コード.txt","C:\パナマ\あ.jpg",'
        )
        self.assertTrue(
            actual_cpc_content.splitlines()[0].startswith(
                expected_first_line_beginning))

        expected_point_lines = [
            '"1","い","Notes",""',
            '"2","","Notes",""',
            '"3","","Notes",""',
        ]
        self.assert_cpc_label_lines_equal(
            actual_cpc_content, expected_point_lines)


class DiscardCPCAfterPointsChangeTest(
        CPCExportBaseTest, UploadAnnotationsCsvTestMixin):
    """
    Test discarding of previously-saved CPC content after changing points
    for an image.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)
        labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, labels)

    def test_cpc_discarded_after_point_regeneration(self):
        img1 = self.upload_image(self.user, self.source)
        img1.cpc_content = 'Some CPC file contents go here'
        img1.save()

        self.client.force_login(self.user)
        self.client.post(reverse('image_regenerate_points', args=[img1.pk]))

        img1.refresh_from_db()
        self.assertEqual('', img1.cpc_content)

    def test_cpc_discarded_after_points_reset_to_source_default(self):
        img1 = self.upload_image(self.user, self.source)
        img1.cpc_content = 'Some CPC file contents go here'
        img1.save()

        self.client.force_login(self.user)
        self.client.post(
            reverse('image_reset_point_generation_method', args=[img1.pk]))

        img1.refresh_from_db()
        self.assertEqual('', img1.cpc_content)

    def test_cpc_discarded_after_annotation_area_reset_to_source_default(self):
        img1 = self.upload_image(self.user, self.source)
        img1.cpc_content = 'Some CPC file contents go here'
        img1.save()

        self.client.force_login(self.user)
        self.client.post(
            reverse('image_reset_annotation_area', args=[img1.pk]))

        img1.refresh_from_db()
        self.assertEqual('', img1.cpc_content)

    def test_cpc_discarded_after_importing_points_from_csv(self):
        img1 = self.upload_image(
            self.user, self.source, dict(filename='1.jpg'))
        img1.cpc_content = 'Some CPC file contents go here'
        img1.save()

        rows = [
            ['Name', 'Column', 'Row'],
            ['1.jpg', 50, 50],
            ['1.jpg', 60, 40],
        ]
        csv_file = self.make_annotations_file('A.csv', rows)
        self.preview_annotations(
            self.user, self.source, csv_file)
        self.upload_annotations(self.user, self.source)

        img1.refresh_from_db()
        self.assertEqual('', img1.cpc_content)

    def test_cpc_not_discarded_for_unaffected_images(self):
        img1 = self.upload_image(self.user, self.source)
        img2 = self.upload_image(self.user, self.source)
        img1.cpc_content = 'Some CPC file contents go here'
        img1.save()
        img2.cpc_content = 'More CPC file contents go here'
        img2.save()

        self.client.force_login(self.user)
        self.client.post(reverse('image_regenerate_points', args=[img1.pk]))

        img1.refresh_from_db()
        self.assertEqual(
            '', img1.cpc_content,
            msg="img1's CPC content should be discarded")
        img2.refresh_from_db()
        self.assertEqual(
            'More CPC file contents go here', img2.cpc_content,
            msg="img2's CPC content should be unchanged")


class SessionErrorTest(ClientTest):
    """Test session-related error cases on the serve view."""
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)

    def test_no_session_data_timestamp(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('cpce:export_serve', args=[self.source.pk]),
            dict(session_data_timestamp=''),
            follow=True,
        )

        self.assertRedirects(
            response, reverse('browse_images', args=[self.source.pk]))
        self.assertContains(
            response,
            html_escape(
                "Export failed: Request data doesn't have a"
                " session_data_timestamp."),
        )

    def test_no_session_data(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('cpce:export_serve', args=[self.source.pk]),
            dict(session_data_timestamp='123'),
            follow=True,
        )

        self.assertRedirects(
            response, reverse('browse_images', args=[self.source.pk]))
        self.assertContains(
            response,
            html_escape(
                "Export failed: We couldn't find the expected data"
                " in your session."),
        )

    def test_mismatched_timestamp(self):
        self.client.force_login(self.user)

        # To modify the session and then save it, it must be stored in a
        # variable first.
        # https://docs.djangoproject.com/en/dev/topics/testing/tools/#django.test.Client.session
        session = self.client.session
        session['cpc_export'] = dict(
            timestamp='123', data=dict())
        session.save()

        response = self.client.get(
            reverse('cpce:export_serve', args=[self.source.pk]),
            dict(session_data_timestamp='456'),
            follow=True,
        )

        self.assertRedirects(
            response, reverse('browse_images', args=[self.source.pk]))
        self.assertContains(
            response,
            html_escape(
                "Export failed: Session data timestamp didn't match."),
        )


class UtilsTest(ClientTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)
        labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, labels)
        cls.img1 = cls.upload_image(
            cls.user, cls.source,
            dict(filename='1.jpg', width=400, height=300))
        cls.img2 = cls.upload_image(cls.user, cls.source)

    def test_get_previous_cpcs_status(self):
        image_set = Image.objects.filter(source=self.source)
        self.assertEqual(get_previous_cpcs_status(image_set), 'none')

        self.img1.cpc_content = 'Some CPC file contents go here'
        self.img1.save()
        image_set = Image.objects.filter(source=self.source)
        self.assertEqual(get_previous_cpcs_status(image_set), 'some')

        self.img2.cpc_content = 'More CPC file contents go here'
        self.img2.save()
        image_set = Image.objects.filter(source=self.source)
        self.assertEqual(get_previous_cpcs_status(image_set), 'all')
