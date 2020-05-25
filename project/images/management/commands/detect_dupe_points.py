from __future__ import unicode_literals
from backports import csv
from io import open
import os

from django.conf import settings
from django.core.management.base import BaseCommand
from tqdm import tqdm

from images.models import Source


class Command(BaseCommand):
    help = "Detect Images which have 2+ Points on the same pixel location."

    def handle(self, *args, **options):

        csv_filepath = os.path.join(
            settings.SITE_DIR, 'tmp', 'images_with_dupe_points.csv')

        with open(csv_filepath, 'w', newline='', encoding='utf-8') as f:

            fieldnames = [
                "Source name", "Source id", "Image name",
                "Image id", "Dupe point count", "Point count",
                "Point generation", "Annotation area",
                "Resolution", "Annotation status",
            ]
            writer = csv.DictWriter(f, fieldnames)
            writer.writeheader()

            images_with_dupes_count = 0

            # Splitting loops into sources and images, instead of just
            # images, seems to avoid a bug where nothing is printed and the
            # command gets killed after 2 minutes.
            sources = Source.objects.all()

            for source in tqdm(sources, disable=settings.TQDM_DISABLE):

                for image in source.image_set.all():

                    points = image.point_set
                    distinct_points = \
                        points.values_list('column', 'row').distinct()

                    if points.count() != distinct_points.count():

                        output_line = (
                            '{source_name} (source {source_id})'
                            ' - image {image_id}'.format(
                                source_name=source.name,
                                source_id=source.pk,
                                image_id=image.pk))
                        self.stdout.write(output_line)

                        dupe_point_count = \
                            points.count() - distinct_points.count()
                        writer.writerow({
                            "Source name": source.name,
                            "Source id": source.pk,
                            "Image name": image.metadata.name,
                            "Image id": image.pk,
                            "Dupe point count": dupe_point_count,
                            "Point count": points.count(),
                            "Point generation":
                                image.point_gen_method_display(),
                            "Annotation area":
                                image.annotation_area_display(),
                            "Resolution": "{w} x {h}".format(
                                w=image.original_width,
                                h=image.original_height),
                            "Annotation status":
                                image.get_annotation_status_str(),
                        })

                        images_with_dupes_count += 1

        self.stdout.write(
            "Number of images with duplicate points: {}".format(
                images_with_dupes_count))
        self.stdout.write(
            "Results have been written to {}".format(csv_filepath))
