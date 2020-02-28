import json
import os
from collections import defaultdict

from django.conf import settings
from django.core.management.base import BaseCommand

from images.models import Source, Image, Point
from lib.utils import direct_s3_read

from vision_backend.tasks import reset_features


class Command(BaseCommand):
    help = "Crawls extracted features and checks that they align with " \
           "DB content. Optionally also correct them."

    def add_arguments(self, parser):

        parser.add_argument('--do_correct',
                            type=int,
                            nargs='?',
                            default=0,
                            help="If true, fix erroneous images.")

    def handle(self, *args, **options):

        errors = defaultdict(list)
        for source in Source.objects.filter():
            print(u"Inspecting source: {}".format(source.name))

            for image in Image.objects.filter(source=source):
                if not image.features.extracted:
                    continue

                try:
                    feats = direct_s3_read(
                        settings.FEATURE_VECTOR_FILE_PATTERN.format(
                            full_image_path=os.path.join(
                                settings.AWS_LOCATION,
                                image.original_file.name)), 'json')
                    n_pts = Point.objects.filter(image=image).count()
                    assert n_pts == len(feats), \
                        "n_pts ({}) neq len(feats) ({})".format(n_pts,
                                                                len(feats))
                    assert len(feats[0]) == 4096, "Feats dim: ({}) neq 4096".\
                        format(len(feats[0]))

                    # TODO: once we have the new feature structure from
                    # TODO: spacer, we can assert that the row, col information
                    # TODO: matches also.
                except Exception as err:
                    errors[source.id].append((image.id, repr(err)))
                    print("Img: {}, error: {}".format(image.id, repr(err)))
                    if options['do_correct']:
                        reset_features.delay(image.id)
        with open('feature_errors.json', 'w') as fp:
            json.dump(errors, fp)
        for source_id in errors:
            print(source_id, len(errors[source_id]))
