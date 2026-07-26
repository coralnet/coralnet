# Tests specific to taking CPC data into the CoralNet DB.
# If it's related to parsing the CPC format, it probably goes in
# test_cpc_format.py.
# If the test semantics apply to CSV as well, it probably goes in
# test_upload_general_cases.py.

from io import StringIO

from bs4 import BeautifulSoup
from django.core.files.base import ContentFile
from django.urls import reverse

from accounts.utils import get_imported_user
from lib.tests.utils import CnStandardTest
from .utils import UploadAnnotationsCpcTestMixin


class CPCPixelScaleFactorTest(CnStandardTest, UploadAnnotationsCpcTestMixin):
    """
    Tests CPC pixel scale factor detection, based on line 1 of the CPC.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)
        labels = cls.create_labels(cls.user, ['A', 'B'], 'Group1')
        cls.create_labelset(cls.user, cls.source, labels)

        cls.img1 = cls.upload_image(
            cls.user, cls.source,
            image_options=dict(filename='1.png', width=100, height=200))

    def preview(self, line_1, point_positions=None):
        """
        line_1 should be the content of the .cpc file's first line.

        point_positions should be a list of (col, row) tuples, in CPCe-scale
        units.

        This method writes valid content for the rest of the .cpc file,
        and then calls the preview view.
        """
        if point_positions is None:
            point_positions = [(0, 0)]

        stream = StringIO()
        # Line 1
        stream.writelines(['{}\n'.format(line_1)])
        # Lines 2-5
        stream.writelines(['1,2\n']*4)
        # Line 6
        stream.writelines(['{}\n'.format(len(point_positions))])
        # Point positions
        stream.writelines(
            ['{},{}\n'.format(pos[0], pos[1]) for pos in point_positions])
        # Labels
        stream.writelines(['"","A","",""\n' for _ in point_positions])
        # Header lines
        stream.writelines(['""']*28)

        cpc_file = ContentFile(stream.getvalue(), name='1.cpc')
        # Return the preview response
        return self.preview_annotations(
            self.user, self.source, [cpc_file])

    def test_width_not_integer(self):
        preview_response = self.preview(line_1='a,1.png,c,3000,e,f')

        self.assertDictEqual(
            preview_response.json(),
            dict(error=(
                "From file 1.cpc: The image width and height on line 1"
                " must be integers.")))

    def test_height_not_integer(self):
        preview_response = self.preview(line_1='a,1.png,1500,3000.0,e,f')

        self.assertDictEqual(
            preview_response.json(),
            dict(error=(
                "From file 1.cpc: The image width and height on line 1"
                " must be integers.")))

    def test_x_scale_not_integer(self):
        preview_response = self.preview(line_1='a,1.png,1050,2100,e,f')

        self.assertDictEqual(
            preview_response.json(),
            dict(error=(
                "From file 1.cpc: Could not establish an integer scale"
                " factor from line 1.")))

    def test_y_scale_not_integer(self):
        preview_response = self.preview(line_1='a,1.png,1500,2999,e,f')

        self.assertDictEqual(
            preview_response.json(),
            dict(error=(
                "From file 1.cpc: Could not establish an integer scale"
                " factor from line 1.")))

    def test_xy_scales_not_equal(self):
        preview_response = self.preview(line_1='a,1.png,1200,3000,e,f')

        self.assertDictEqual(
            preview_response.json(),
            dict(error=(
                "From file 1.cpc: Could not establish an integer scale"
                " factor from line 1.")))

    def test_scale_of_15(self):
        """This is the common case and arises from usage at 96 DPI."""
        self.preview(
            line_1='a,1.png,1500,3000,e,f', point_positions=[(1200, 900)])
        self.upload_annotations(self.user, self.source)

        values_set = set(
            self.img1.point_set.all()
            .values_list('column', 'row', 'point_number'))
        self.assertSetEqual(values_set, {(80, 60, 1)})

    def test_scale_of_12(self):
        """This arises from usage at 120 DPI, and should also be accepted."""
        self.preview(
            line_1='a,1.png,1200,2400,e,f', point_positions=[(960, 720)])
        self.upload_annotations(self.user, self.source)

        values_set = set(
            self.img1.point_set.all()
            .values_list('column', 'row', 'point_number'))
        self.assertSetEqual(values_set, {(80, 60, 1)})


class LabelMappingTest(CnStandardTest, UploadAnnotationsCpcTestMixin):
    """
    Ensure the label_mapping preference works.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user,)
        labels = cls.create_labels(
            cls.user, ['A', 'B', 'B+X', 'C', 'C+Y+Z'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, labels)

        cls.img1 = cls.upload_image(
            cls.user, cls.source,
            image_options=dict(filename='1.png', width=100, height=100))

        cls.image_dimensions = (100, 100)

    def test_id_and_notes(self):
        cpc_files = [
            self.make_annotations_file(
                self.image_dimensions, '1.cpc',
                r"C:\My Photos\2017-05-13 GBR\1.png", [
                    (50*15, 50*15, 'A'),
                    (60*15, 40*15, 'B', 'X'),
                    (70*15, 30*15, 'C', 'Y+Z')]),
        ]
        preview_response = self.preview_annotations(
            self.user, self.source, cpc_files, label_mapping='id_and_notes')
        upload_response = self.upload_annotations(self.user, self.source)

        self.check_annotations(
            preview_response, upload_response,
            expected_label_codes=['A', 'B+X', 'C+Y+Z'])

    def test_id_only(self):
        cpc_files = [
            self.make_annotations_file(
                self.image_dimensions, '1.cpc',
                r"C:\My Photos\2017-05-13 GBR\1.png", [
                    (50*15, 50*15, 'A'),
                    (60*15, 40*15, 'B', 'X'),
                    (70*15, 30*15, 'C', 'Y+Z')]),
        ]
        preview_response = self.preview_annotations(
            self.user, self.source, cpc_files, label_mapping='id_only')
        upload_response = self.upload_annotations(self.user, self.source)

        self.check_annotations(
            preview_response, upload_response,
            expected_label_codes=['A', 'B', 'C'])

    def check_annotations(
            self, preview_response, upload_response, expected_label_codes):

        self.assertDictEqual(
            preview_response.json(),
            dict(
                success=True,
                previewTable=[
                    dict(
                        name=self.img1.metadata.name,
                        link=reverse(
                            'annotation_tool',
                            kwargs=dict(image_id=self.img1.pk)),
                        createInfo="Will create 3 points, 3 annotations",
                    ),
                ],
                previewDetails=dict(
                    numImages=1,
                    totalPoints=3,
                    totalAnnotations=3,
                    numImagesWithExistingAnnotations=0,
                ),
            ),
        )

        self.assertDictEqual(upload_response.json(), dict(success=True))

        values_set = set(
            self.img1.point_set
            .values_list('column', 'row', 'point_number', 'image_id'))
        self.assertSetEqual(values_set, {
            (50, 50, 1, self.img1.pk),
            (60, 40, 2, self.img1.pk),
            (70, 30, 3, self.img1.pk),
        })

        annotations = self.img1.annotation_set.all()
        values_set = set(
            (a.label_code, a.point.pk, a.image.pk)
            for a in annotations
        )
        self.assertSetEqual(values_set, {
            (expected_label_codes[0], self.img1.point_set.get(
                point_number=1).pk, self.img1.pk),
            (expected_label_codes[1], self.img1.point_set.get(
                point_number=2).pk, self.img1.pk),
            (expected_label_codes[2], self.img1.point_set.get(
                point_number=3).pk, self.img1.pk),
        })
        for annotation in annotations:
            self.assertEqual(annotation.source.pk, self.source.pk)
            self.assertEqual(annotation.user.pk, get_imported_user().pk)
            self.assertEqual(annotation.robot_version, None)
            self.assertLess(
                self.source.create_date, annotation.annotation_date)

    def test_form_init_no_plus_code(self):
        # Ensure the labelset has no label codes with + chars in them.
        local_bx = self.source.labelset.get_labels().get(code='B+X')
        local_bx.code = 'D'
        local_bx.save()
        local_cyz = self.source.labelset.get_labels().get(code='C+Y+Z')
        local_cyz.code = 'E'
        local_cyz.save()

        self.client.force_login(self.user)
        response = self.client.get(
            reverse('cpce:upload_page', args=[self.source.pk]))

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
            reverse('cpce:upload_page', args=[self.source.pk]))

        response_soup = BeautifulSoup(response.content, 'html.parser')
        label_mapping_selected_radio = response_soup.find(
            'input', dict(name='label_mapping'), checked=True)
        self.assertEqual(
            label_mapping_selected_radio.attrs.get('value'), 'id_and_notes',
            "Should select ID and notes by default")


class SaveCPCInfoTest(CnStandardTest, UploadAnnotationsCpcTestMixin):
    """
    Tests for saving of CPC file info when uploading CPCs.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)
        labels = cls.create_labels(cls.user, ['A', 'B'], 'Group1')
        cls.create_labelset(cls.user, cls.source, labels)

        cls.img1 = cls.upload_image(
            cls.user, cls.source,
            image_options=dict(filename='1.jpg', width=100, height=100))
        cls.img2 = cls.upload_image(
            cls.user, cls.source,
            image_options=dict(filename='2.jpg', width=100, height=100))

        cls.image_dimensions = (100, 100)

    def test_cpc_content_one_image(self):
        cpc_files = [
            self.make_annotations_file(
                self.image_dimensions, '1.cpc',
                r"C:\My Photos\2017-05-13 GBR\1.jpg", [
                    (49*15, 49*15, 'A'),
                    (59*15, 39*15, 'B')]),
        ]
        # Save the file content for comparison purposes.
        img1_expected_cpc_content = cpc_files[0].read()
        # Reset the file pointer so that the views can read from the start.
        cpc_files[0].seek(0)

        self.preview_annotations(self.user, self.source, cpc_files)
        self.upload_annotations(self.user, self.source)

        self.img1.refresh_from_db()
        self.assertEqual(self.img1.cpc_content, img1_expected_cpc_content)
        self.assertEqual(self.img1.cpc_filename, '1.cpc')
        self.img2.refresh_from_db()
        self.assertEqual(self.img2.cpc_content, '')
        self.assertEqual(self.img2.cpc_filename, '')

    def test_cpc_content_multiple_images(self):
        cpc_files = [
            self.make_annotations_file(
                self.image_dimensions, 'GBR_1.cpc',
                r"C:\My Photos\2017-05-13 GBR\1.jpg", [
                    (49*15, 49*15, 'A'),
                    (59*15, 39*15, 'B')]),
            self.make_annotations_file(
                self.image_dimensions, 'GBR_2.cpc',
                r"C:\My Photos\2017-05-13 GBR\2.jpg", [
                    (69*15, 29*15, 'A'),
                    (79*15, 19*15, 'A')]),
        ]
        # Save the file content for comparison purposes.
        img1_expected_cpc_content = cpc_files[0].read()
        img2_expected_cpc_content = cpc_files[1].read()
        # Reset the file pointer so that the views can read from the start.
        cpc_files[0].seek(0)
        cpc_files[1].seek(0)

        self.preview_annotations(self.user, self.source, cpc_files)
        self.upload_annotations(self.user, self.source)

        self.img1.refresh_from_db()
        self.assertEqual(self.img1.cpc_content, img1_expected_cpc_content)
        self.assertEqual(self.img1.cpc_filename, 'GBR_1.cpc')
        self.img2.refresh_from_db()
        self.assertEqual(self.img2.cpc_content, img2_expected_cpc_content)
        self.assertEqual(self.img2.cpc_filename, 'GBR_2.cpc')

    def test_codes_filepath(self):
        cpc_files = [
            self.make_annotations_file(
                self.image_dimensions, '1.cpc',
                r"C:\My Photos\2017-05-13 GBR\1.jpg", [
                    (49*15, 49*15, 'A'),
                    (59*15, 39*15, 'B')],
                codes_filepath=r'C:\PROGRA~4\CPCE_4~1\SHALLO~1.TXT'),
            self.make_annotations_file(
                self.image_dimensions, '2.cpc',
                r"C:\My Photos\2017-05-13 GBR\2.jpg", [
                    (69*15, 29*15, 'A'),
                    (79*15, 19*15, 'A')],
                codes_filepath=r'C:\My Photos\CPCe codefiles\GBR codes.txt'),
        ]
        self.preview_annotations(self.user, self.source, cpc_files)
        self.upload_annotations(self.user, self.source)

        self.source.refresh_from_db()
        # Although it's an implementation detail and not part of spec,
        # the first uploaded CPC should have its values used in a multi-CPC
        # upload.
        self.assertEqual(
            self.source.cpce_code_filepath,
            r'C:\PROGRA~4\CPCE_4~1\SHALLO~1.TXT')

    def test_image_dir(self):
        self.upload_image(
            self.user, self.source,
            image_options=dict(filename='3.jpg', width=100, height=100))
        self.upload_image(
            self.user, self.source,
            image_options=dict(
                filename=r'GBR\2017\4.jpg', width=100, height=100))

        # Filename match
        cpc_files = [
            self.make_annotations_file(
                self.image_dimensions, '3.cpc',
                r"C:\Reef Surveys\GBR\2017\3.jpg", [
                    (49*15, 49*15, 'A'),
                    (59*15, 39*15, 'B')]),
        ]
        self.preview_annotations(self.user, self.source, cpc_files)
        self.upload_annotations(self.user, self.source)
        self.source.refresh_from_db()
        self.assertEqual(
            self.source.cpce_image_dir, r'C:\Reef Surveys\GBR\2017')

        # Subdir match
        cpc_files = [
            self.make_annotations_file(
                self.image_dimensions, '4.cpc',
                r"C:\Reef Surveys\GBR\2017\4.jpg", [
                    (49*15, 49*15, 'A'),
                    (59*15, 39*15, 'B')]),
        ]
        self.preview_annotations(self.user, self.source, cpc_files)
        self.upload_annotations(self.user, self.source)
        self.source.refresh_from_db()
        self.assertEqual(
            self.source.cpce_image_dir, r'C:\Reef Surveys')


class CPCImageMatchingTest(CnStandardTest, UploadAnnotationsCpcTestMixin):
    """
    Tests for matching uploaded CPCs to images in the source.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)
        labels = cls.create_labels(cls.user, ['A', 'B'], 'Group1')
        cls.create_labelset(cls.user, cls.source, labels)

    def upload_image_with_name(self, image_name):
        img = self.upload_image(
            self.user, self.source, image_options=dict(width=100, height=100))
        img.metadata.name = image_name
        img.metadata.save()
        return img

    def upload_preview_for_image_name(self, image_name):
        cpc_files = [
            self.make_annotations_file(
                dimensions=(100, 100),
                cpc_filename='1.cpc',
                image_filepath=image_name,
                points=[(9*15, 9*15, 'A')],
                codes_filepath=r'C:\PROGRA~4\CPCE_4~1\SHALLO~1.TXT'),
        ]
        return self.preview_annotations(self.user, self.source, cpc_files)

    def assertImageInPreview(self, img, preview_response):
        self.assertDictEqual(
            preview_response.json()['previewTable'][0],
            dict(
                name=img.metadata.name,
                link=reverse('annotation_tool', args=[img.pk]),
                createInfo="Will create 1 points, 1 annotations"))

    def test_favor_longer_path_suffix_matches(self):
        # Scramble the upload order, to ensure the matching logic doesn't
        # depend on order.
        img1 = self.upload_image_with_name(r'D:\Site A\Transect 1\01.jpg')
        img4 = self.upload_image_with_name(r'01.jpg')
        img2 = self.upload_image_with_name(r'Site A\Transect 1\01.jpg')
        img3 = self.upload_image_with_name(r'Transect 1\01.jpg')

        preview_response = self.upload_preview_for_image_name(
            r'D:\Site A\Transect 1\01.jpg')
        self.assertImageInPreview(img1, preview_response)

        preview_response = self.upload_preview_for_image_name(
            r'C:\Site A\Transect 1\01.jpg')
        self.assertImageInPreview(img2, preview_response)

        preview_response = self.upload_preview_for_image_name(
            r'D:\Site B\Transect 1\01.jpg')
        self.assertImageInPreview(img3, preview_response)

        preview_response = self.upload_preview_for_image_name(
            r'D:\Site A\Transect 8\01.jpg')
        self.assertImageInPreview(img4, preview_response)

    def test_do_not_partial_match_filenames(self):
        self.upload_image_with_name(r'IMG_0001.JPG')

        # 'Superstring'
        preview_response = self.upload_preview_for_image_name(
            r'D:\Site A\Transect 1\Quadrant_5_IMG_0001.JPG')
        self.assertDictEqual(
            preview_response.json(),
            dict(error="No matching image names found in the source"))

        # Substring
        preview_response = self.upload_preview_for_image_name(
            r'0001.JPG')
        self.assertDictEqual(
            preview_response.json(),
            dict(error="No matching image names found in the source"))

    def test_do_not_partial_match_subdirs(self):
        self.upload_image_with_name(r'Transect 1\IMG_0001.JPG')

        # 'Superstring'
        preview_response = self.upload_preview_for_image_name(
            r'D:\Site A Transect 1\IMG_0001.JPG')
        self.assertDictEqual(
            preview_response.json(),
            dict(error="No matching image names found in the source"))

        # Substring
        preview_response = self.upload_preview_for_image_name(
            r'D:\Site A\sect 1\IMG_0001.JPG')
        self.assertDictEqual(
            preview_response.json(),
            dict(error="No matching image names found in the source"))

    def test_slash_direction_does_not_matter(self):
        self.upload_image_with_name(r'01.jpg')

        # Forward in image name, back in CPC
        transect_img = self.upload_image_with_name(r'Transect 1/01.jpg')
        preview_response = self.upload_preview_for_image_name(
            r'D:\Site A\Transect 1\01.jpg')
        self.assertImageInPreview(transect_img, preview_response)

        # Back in image name, forward in CPC
        quadrat_img = self.upload_image_with_name(r'Quadrat 3\01.jpg')
        preview_response = self.upload_preview_for_image_name(
            r'D:/Site A/Quadrat 3/01.jpg')
        self.assertImageInPreview(quadrat_img, preview_response)

    def test_leading_slash_ignored(self):
        """
        Leading slashes may seem innocuous to Windows / non-technical users,
        and it's unlikely to indicate anything significant in a CPCe context.
        So ignore such a slash (i.e. don't interpret it as root).
        """
        img1 = self.upload_image_with_name(r'/01.jpg')
        preview_response = self.upload_preview_for_image_name(
            r'D:\Site A\Transect 1\01.jpg')
        self.assertImageInPreview(img1, preview_response)

        img2 = self.upload_image_with_name(r'\Transect 1\02.jpg')
        preview_response = self.upload_preview_for_image_name(
            r'D:\Site A\Transect 1\02.jpg')
        self.assertImageInPreview(img2, preview_response)

    def test_multiple_cpcs_for_one_image(self):
        self.upload_image_with_name(r'01.jpg')

        cpc_files = [
            self.make_annotations_file(
                dimensions=(100, 100),
                cpc_filename='1.cpc',
                image_filepath=r'01.jpg',
                points=[(9*15, 9*15, 'A')]),
            self.make_annotations_file(
                dimensions=(100, 100),
                cpc_filename='2.cpc',
                image_filepath=r'01.jpg',
                points=[(9*15, 9*15, 'A')]),
        ]
        preview_response = self.preview_annotations(
            self.user, self.source, cpc_files)
        self.assertDictEqual(
            preview_response.json(),
            dict(error=(
                "Image 01.jpg has points from more than one .cpc file:"
                " 1.cpc and 2.cpc. There should be only one .cpc file"
                " per image.")))
