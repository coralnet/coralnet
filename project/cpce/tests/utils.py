from abc import ABC
from io import StringIO

from django.core.files.base import ContentFile
from django.urls import reverse

from annotations.tests.utils import UploadAnnotationsTestMixin


class UploadAnnotationsCpcTestMixin(UploadAnnotationsTestMixin, ABC):

    @staticmethod
    def make_annotations_file(
            dimensions, cpc_filename, image_filepath, points,
            codes_filepath=r'C:\PROGRA~4\CPCE_4~1\SHALLO~1.TXT'):
        """
        :param dimensions: image dimensions in pixels, as a (width, height)
          tuple.
        :param cpc_filename: filename of the .cpc to be created.
        :param image_filepath: image filepath for line 1.
        :param points: list of (column, row, label code)
          or (column, row, label code, notes) tuples.
        :param codes_filepath: codes filepath for line 1.
        """
        # 4-tuples or 3-tuples are accepted for points. 4th element is the
        # Notes field. If it's not present, add an empty string for it.
        points_full = []
        for point in points:
            if len(point) == 4:
                points_full.append(point)
            elif len(point) == 3:
                points_full.append((point[0], point[1], point[2], ""))
            else:
                raise ValueError("Pass points as 3-tuples or 4-tuples.")
        points = points_full

        stream = StringIO()
        # Line 1
        line1_nums = '{},{},9000,4500'.format(
            dimensions[0]*15, dimensions[1]*15)
        stream.writelines([
            '"{codes_filepath}","{image_filepath}",{line1_nums}\n'.format(
                codes_filepath=codes_filepath,
                image_filepath=image_filepath,
                line1_nums=line1_nums,
            )
        ])

        # Annotation area
        stream.writelines([
            '0,1500\n',
            '2000,1500\n',
            '2000,302.35\n',
            '0,302.35\n',
        ])

        # Number of points
        stream.writelines([
            '{num_points}\n'.format(num_points=len(points)),
        ])

        # Point positions
        stream.writelines(
            ['{x},{y}\n'.format(x=x, y=y) for x, y, _, _ in points]
        )

        # Label codes and notes
        label_code_lines = []
        for point_number, point in enumerate(points):
            _, _, cpc_id, cpc_notes = point
            label_code_lines.append(
                f'"{point_number}","{cpc_id}","Notes","{cpc_notes}"\n')
        stream.writelines(label_code_lines)

        # Headers
        stream.writelines(['""\n']*28)

        f = ContentFile(stream.getvalue(), name=cpc_filename)
        return f

    def preview_annotations(
            self, user, source, cpc_files, label_mapping='id_only'):
        self.client.force_login(user)
        return self.client.post(
            reverse('cpce:upload_preview_ajax', args=[source.pk]),
            {'cpc_files': cpc_files, 'label_mapping': label_mapping},
        )

    def upload_annotations(self, user, source):
        self.client.force_login(user)
        return self.client.post(
            reverse('cpce:upload_confirm_ajax', args=[source.pk]),
        )
