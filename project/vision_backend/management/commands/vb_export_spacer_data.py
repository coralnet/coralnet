import json
import posixpath

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db.models import F
from storages.backends.s3boto3 import S3Boto3Storage
from tqdm import tqdm

from annotations.models import Label, Annotation
from sources.models import Source
from sources.utils import filter_out_test_sources
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

    def log(self, message):
        log(message, 'export_data.log', self.stdout.write)

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
                         col=F('point__column')):
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
        self.log("Starting data export with args: [{}]\n{}".
                 format(args_str, '-'*70))

        export_storage = S3Boto3Storage(
            bucket_name=options['bucket'], location='')

        # Start by exporting the label-set
        export_storage.save(
            options['name'] + '/' + 'label_set.json',
            ContentFile(self.labelset_json))

        # Filter sources
        sources = Source.objects.filter()
        sources = filter_out_test_sources(sources)
        sources = [s for s in sources if
                   s.nbr_confirmed_images > options['min_required_imgs']]

        # Iterate over sources
        for itt, source in enumerate(sources):
            self.log("Exporting {}, id:{}. [{}({})] with {} images...".format(
                source.name, source.pk, itt, len(sources) - 1,
                source.nbr_confirmed_images))

            # Establish a new connection for each source.
            export_storage = S3Boto3Storage(
                bucket_name=options['bucket'], location='')
            # When we copy files from one bucket to another, we'll need to
            # access the boto interface at a lower level.
            export_bucket = export_storage.connection.get_bucket(
                options['bucket'])
            main_bucket_name = settings.AWS_STORAGE_BUCKET_NAME

            if itt < options['skip_to']:
                self.log("Skipping...")
                continue
            source_prefix = options['name']+'/'+'s'+str(source.pk)

            # Export source meta
            export_storage.save(
                source_prefix + '/' + 'meta.json',
                ContentFile(self.source_meta_json(source)))

            images_prefix = source_prefix + '/' + 'images'

            for image in tqdm(
                source.image_set.confirmed().with_features()
            ):

                image_prefix = images_prefix + '/i' + str(image.pk)

                # Export image meta
                export_storage.save(
                    image_prefix + '.meta.json',
                    ContentFile(self.image_meta_json(image)))

                # Export image annotations
                export_storage.save(
                    image_prefix + '.anns.json',
                    ContentFile(self.image_annotations_json(image)))

                # Set image source and target keys.
                source_image_key = posixpath.join(settings.AWS_LOCATION,
                                                  image.original_file.name)
                source_feature_key = settings.FEATURE_VECTOR_FILE_PATTERN.\
                    format(full_image_path=source_image_key)
                target_image_key = image_prefix + '.jpg'
                target_feature_key = image_prefix + '.features.json'

                # Copy feature file
                if options['feature_level'] > 0:
                    key = export_bucket.get_key(target_feature_key)
                    if key is None or options['feature_level'] == 2:
                        # Nothing exported, or overwrite anyways:
                        export_bucket.copy_key(
                            target_feature_key,
                            main_bucket_name,
                            source_feature_key
                        )

                # Copy image file
                image_key = export_bucket.get_key(target_image_key)
                if image_key is None:
                    export_bucket.copy_key(
                        target_image_key,
                        main_bucket_name,
                        source_image_key
                    )
