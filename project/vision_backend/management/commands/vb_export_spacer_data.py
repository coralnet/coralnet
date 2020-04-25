import json
import posixpath

import boto
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import F
from tqdm import tqdm

from annotations.models import Label, Annotation
from images.models import Source, Image
from images.utils import filter_out_test_sources
from .utils import log


class Command(BaseCommand):
    help = 'Tool for uploading images and sources to spacer.'

    def add_arguments(self, parser):

        parser.add_argument('--min_required_imgs',
                            type=int,
                            nargs='?',
                            default=200,
                            help="Min number of confirmed images required "
                                 "to include a source.")
        parser.add_argument('--bucket',
                            type=str,
                            default='spacer-trainingdata',
                            help="bucket name to export to")
        parser.add_argument('--name',
                            type=str,
                            default='debug-export',
                            help="Export name")
        parser.add_argument('--skip_to',
                            type=int,
                            default=0,
                            help="Index of source to skip to.")
        parser.add_argument('--feature_level',
                            type=int,
                            default=0,
                            help="Level of feature export"
                                 "0 = no export, "
                                 "1 = export if do not already exist,"
                                 "2 = export and overwrite.")

    @staticmethod
    def log(message):
        log(message, 'export_data.log')

    @property
    def labelset_json(self):
        cont = []
        for label in Label.objects.filter():
            cont.append({'id': label.pk,
                         'name': label.name,
                         'code': label.default_code,
                         'group': label.group.name,
                         'duplicate_of': str(label.duplicate),
                         'is_verified': label.verified,
                         'ann_count': label.ann_count})
        return json.dumps(cont, indent=2)

    @staticmethod
    def source_meta_json(source):
        return json.dumps(source.to_dict(), indent=2)

    @staticmethod
    def image_meta_json(image):
        # Read out default image metadata.
        metadata_dict = image.metadata.to_dict()
        # Add details re. train vs valset.
        metadata_dict['in_trainset'] = image.trainset
        metadata_dict['in_valset'] = image.valset
        return json.dumps(metadata_dict, indent=2)

    @staticmethod
    def image_annotations_json(image):
        rowcols = []
        for ann in Annotation.objects.filter(image=image). \
            order_by('point__id'). \
                annotate(row=F('point__row'),
                         col=F('point__column'),
                         label_id=F('label__pk')):
            rowcols.append({'row': ann.row,
                            'col': ann.col,
                            'label': ann.label_id})
        return json.dumps(rowcols, indent=2)

    def handle(self, *args, **options):

        arg_keys = ['min_required_imgs', 'bucket', 'name', 'skip_to',
                    'feature_level']
        args_str = ''
        for key in arg_keys:
            args_str += '{}: {}, '.format(key, options[key])
        self.log(u"Starting data export with args: [{}]\n{}".
                 format(args_str, '-'*70))

        # Start by exporting the label-set
        c = boto.connect_s3(settings.AWS_ACCESS_KEY_ID,
                            settings.AWS_SECRET_ACCESS_KEY)
        bucket = c.get_bucket(options['bucket'])
        label_set_key = bucket.new_key(options['name']+'/' + 'label_set.json')
        label_set_key.set_contents_from_string(self.labelset_json)

        # Filter sources
        sources = Source.objects.filter()
        sources = filter_out_test_sources(sources)
        sources = [s for s in sources if
                   s.nbr_confirmed_images > options['min_required_imgs']]

        # Iterate over sources
        for itt, source in enumerate(sources):
            self.log(u"Exporting {}, id:{}. [{}({})] with {} images...".format(
                source.name, source.pk, itt, len(sources) - 1,
                source.nbr_confirmed_images))

            # Establish a new connection for each source.
            c = boto.connect_s3(settings.AWS_ACCESS_KEY_ID,
                                settings.AWS_SECRET_ACCESS_KEY)
            bucket = c.get_bucket(options['bucket'])

            if itt < options['skip_to']:
                self.log(u"Skipping...")
                continue
            source_prefix = options['name']+'/'+'s'+str(source.pk)

            # Export source meta
            source_meta_key = bucket.new_key(source_prefix + '/' + 'meta.json')
            source_meta_key.set_contents_from_string(
                self.source_meta_json(source))

            images_prefix = source_prefix + '/' + 'images'

            for image in tqdm(Image.objects.filter(source=source,
                                                   confirmed=True,
                                                   features__extracted=True)):

                image_prefix = images_prefix + '/i' + str(image.pk)

                # Export image meta
                source_meta_key = bucket.new_key(image_prefix + '.meta.json')
                source_meta_key.set_contents_from_string(
                    self.image_meta_json(image))

                # Export image annotations
                source_meta_key = bucket.new_key(image_prefix + '.anns.json')
                source_meta_key.set_contents_from_string(
                    self.image_annotations_json(image))

                # Set image source and target keys.
                source_image_key = posixpath.join(settings.AWS_LOCATION,
                                                  image.original_file.name)
                source_feature_key = settings.FEATURE_VECTOR_FILE_PATTERN.\
                    format(full_image_path=source_image_key)
                target_image_key = image_prefix + '.jpg'
                target_feature_key = image_prefix + '.features.json'

                # Copy feature file
                if options['feature_level'] > 0:
                    key = bucket.get_key(target_feature_key)
                    if key is None or options['feature_level'] == 2:
                        # Nothing exported, or overwrite anyways:
                        bucket.copy_key(target_feature_key,
                                        settings.AWS_STORAGE_BUCKET_NAME,
                                        source_feature_key)

                # Copy image file
                image_key = bucket.get_key(target_image_key)
                if image_key is None:
                    bucket.copy_key(target_image_key,
                                    settings.AWS_STORAGE_BUCKET_NAME,
                                    source_image_key)
