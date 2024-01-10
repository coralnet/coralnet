from collections import defaultdict
import json

from django.conf import settings
from django.core.files.storage import get_storage_class
from django.core.management.base import BaseCommand
from spacer.data_classes import ImageFeatures

from images.models import Image, Source
from ...utils import reset_features
from .utils import log


class Command(BaseCommand):
    help = "Crawls extracted features and checks that they align with " \
           "DB content. Optionally also correct them."

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.errors = defaultdict(list)
        self.storage = get_storage_class()()

    def add_arguments(self, parser):
        parser.add_argument(
            'mode', choices=['all_sources', 'source_ids', 'image_ids'],
            help="Pick a mode suitable for the images you want to check.")

        parser.add_argument(
            '--ids', type=int, nargs='+',
            help="(For source_ids and image_ids modes)"
                 " List of source/image IDs to check.")

        parser.add_argument(
            '--skip_to', type=int,
            help="(For all_sources mode) ID of source to skip to."
                 " Sources are scanned in ascending-ID order.")

        parser.add_argument(
            '--do_correct', action='store_true',
            help="If specified, fix erroneous features.")

    def log(self, message):
        log(message, 'inspect_features.log', self.stdout.write)

    def inspect_image(self, image, do_correct):
        if not image.features.extracted:
            return

        rowcols_from_db = [
            (p['row'], p['column'])
            for p in image.point_set.values('row', 'column')
        ]
        feature_loc = self.storage.spacer_data_loc(
            settings.FEATURE_VECTOR_FILE_PATTERN.format(
                full_image_path=image.original_file.name))

        try:
            # This may raise an AssertionError, ValueError,
            # or FileNotFoundError.
            features = ImageFeatures.load(feature_loc)

            if features.valid_rowcol:
                rowcols_from_features = [
                    (pf.row, pf.col)
                    for pf in features.point_features
                ]

                if not set(rowcols_from_db) == set(rowcols_from_features):
                    raise ValueError(
                        "Feature rowcols don't match the DB rowcols.")
            else:
                if not len(rowcols_from_db) == len(features.point_features):
                    raise ValueError(
                        "Legacy feature rowcols don't match the number of DB"
                        " rowcols.")

        except (AssertionError, ValueError, FileNotFoundError) as err:
            self.errors[image.source.id].append((image.id, repr(err)))
            self.log(f"Img: {image.id}, error: {err}")
            if do_correct:
                reset_features(image)

    def handle(self, *args, **options):

        command_str = (
            "Running vb_inspect_extracted_features with options: "
            + ", ".join([
                f"{option_name} = {options.get(option_name)}"
                for option_name in ['mode', 'ids', 'skip_to', 'do_correct']
            ])
        )
        self.log(command_str)

        mode = options['mode']

        if mode in ['source_ids', 'all_sources']:

            if mode == 'source_ids':
                sources = Source.objects.filter(pk__in=options['ids'])
            else:
                # 'all_sources'
                skip_to = options.get('skip_to')
                if skip_to:
                    sources = Source.objects.filter(pk__gte=skip_to)
                else:
                    sources = Source.objects.all()
            sources = sources.order_by('pk')

            source_count = len(sources)

            for source_num, source in enumerate(sources, 1):

                self.log(
                    f"Inspecting \"{source.name}\", ID {source.pk}"
                    f" [{source_num}/{source_count}]"
                    f" with {source.nbr_images} images")

                for image in source.image_set.order_by('pk'):
                    self.inspect_image(image, options['do_correct'])

        else:

            # mode is image_ids
            images = Image.objects.filter(pk__in=options['ids']).order_by('pk')
            for image in images:
                self.log(f"Inspecting image {image.pk}")
                self.inspect_image(image, options['do_correct'])

        # Log/output error summaries

        if len(self.errors) > 0:
            self.stdout.write(f"Errors per source:")
            for source_id in self.errors:
                self.stdout.write(f"{source_id}: {len(self.errors[source_id])}")

            feature_errors_filepath = 'feature_errors.json'
            with open(feature_errors_filepath, 'w') as fp:
                json.dump(self.errors, fp)
            self.stdout.write(f"Errors written to {feature_errors_filepath}.")
        else:
            self.stdout.write(f"No errors found.")
