import os
import tempfile
from unittest import mock, skip

from images.models import Point
from lib.tests.utils import ManagementCommandTest


def save_without_checks(self, *args, **kwargs):
    """
    Mock version of Point.save().
    Doesn't run assertions, so we can save any row/column values we want.
    """
    # Must use the 2-arg super() form when using super() in a
    # function defined outside of a class.
    super(Point, self).save(*args, **kwargs)


@skip(
    "This test is unreliable for some unknown reason, both on Windows dev"
    " machine and on Travis. Example error:"
    r" `AssertionError: '102 4' not found in '102 3\n103 4'`")
class RemovePointOutliersTest(ManagementCommandTest):

    @staticmethod
    def update_point(point, row=None, column=None):
        if row is not None:
            point.row = row
        if column is not None:
            point.column = column
        with mock.patch.object(Point, 'save', save_without_checks):
            point.save()

    def test_all_modes(self):
        # Set up data
        user = self.create_user()
        source = self.create_source(
            user,
            default_point_generation_method=dict(type='simple', points=5))
        labels = self.create_labels(user, ['A', 'B'], 'GroupA')
        self.create_labelset(user, source, labels)

        img1 = self.upload_image(
            user, source, image_options=dict(width=40, height=50))
        points = img1.point_set.all()
        # These points are in range
        self.update_point(points[0], column=0, row=0)
        self.update_point(points[1], column=39, row=49)
        self.update_point(points[2], column=20, row=25)

        img2 = self.upload_image(
            user, source, image_options=dict(width=40, height=50))
        points = img2.point_set.all()
        # These columns are out of range
        self.update_point(points[0], column=-7)
        self.update_point(points[1], column=-1)
        self.update_point(points[2], column=40)
        self.update_point(points[3], column=47)

        img3 = self.upload_image(
            user, source, image_options=dict(width=40, height=50))
        points = img3.point_set.all()
        # These rows are out of range
        self.update_point(points[4], row=-15)
        self.update_point(points[3], row=-1)
        self.update_point(points[2], row=50)
        self.update_point(points[1], row=472)

        with tempfile.NamedTemporaryFile(delete=False) as temporary_file:
            # The command opens the file from the pathname, so close it first.
            temporary_file.close()

            # Scan for outliers
            args = ['scan', temporary_file.name]
            self.call_command_and_get_output(
                'images', 'removepointoutliers', args=args)

            # Print outliers
            args = ['print', temporary_file.name]
            stdout_text, _ = self.call_command_and_get_output(
                'images', 'removepointoutliers', args=args)

            # Clean up outliers
            args = ['clean', temporary_file.name]
            self.call_command_and_get_output(
                'images', 'removepointoutliers', args=args)

            os.remove(temporary_file.name)

        # Verify output
        self.assertIn("{} 4".format(img2.pk), stdout_text)
        self.assertIn("{} 4".format(img3.pk), stdout_text)

        # Verify data changes: should have deleted 4 points from img2,
        # 4 points from img3
        img1.refresh_from_db()
        self.assertEqual(img1.point_set.all().count(), 5)
        img2.refresh_from_db()
        self.assertEqual(img2.point_set.all().count(), 1)
        img3.refresh_from_db()
        self.assertEqual(img3.point_set.all().count(), 1)
