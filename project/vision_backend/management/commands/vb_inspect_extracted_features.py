import json
import os
from collections import defaultdict

from django.conf import settings
from django.core.management.base import BaseCommand

from images.models import Source, Image, Point
from lib.utils import direct_s3_read

from vision_backend.tasks import reset_features

from utils import log


class Command(BaseCommand):
    help = "Crawls extracted features and checks that they align with " \
           "DB content. Optionally also correct them."

    def add_arguments(self, parser):

        parser.add_argument('--do_correct',
                            type=int,
                            nargs='?',
                            default=0,
                            help="If true, fix erroneous images.")

        parser.add_argument('--skip_to',
                            type=int,
                            default=0,
                            help="Index of source to skip to.")

    @staticmethod
    def log(message):
        log(message, 'inspect_features.log')

    def handle(self, *args, **options):

        errors = defaultdict(list)
        sources = Source.objects.filter().order_by('pk')

        arg_keys = ['do_correct', 'skip_to']
        args_str = ''
        for key in arg_keys:
            args_str += '{}: {}, '.format(key, options[key])

        self.log(u"Starting inspection of {} sources with args: [{}]\n{}".format(
            sources.count(), args_str, "-"*70))
        for itt, source in enumerate(sources):

            self.log(u"Inspecting {}, id:{}. [{}({})] with {} images...".format(
                source.name, source.pk, itt, len(sources) - 1,
                source.nbr_images))
            if itt < options['skip_to']:
                self.log(u"Skipping...")
                continue

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
                    self.log(u"Img: {}, error: {}".format(image.id, repr(err)))
                    if options['do_correct']:
                        reset_features.delay(image.id)
        with open('feature_errors.json', 'w') as fp:
            json.dump(errors, fp)
        for source_id in errors:
            print(source_id, len(errors[source_id]))
