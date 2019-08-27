import boto
import json
import os
from boto.s3.key import Key
from tqdm import tqdm

from django.db.models import F
from django.core.management.base import BaseCommand
from django.conf import settings

from images.models import Source, Image
from images.utils import filter_out_test_sources
from annotations.models import Label, Annotation


class Command(BaseCommand):
    help = 'Tool for uploading images and sources to spacer.'

    def add_arguments(self, parser):

        parser.add_argument('--min_required_imgs', type=int, nargs='?', default=200,
                            help="Min number of confirmed images required to include a source.")
        parser.add_argument('--bucket', type=str, default='spacer-trainingdata', help="bucket name to export to")
        parser.add_argument('--name', type=str, default='debug-export', help="Export name")
        parser.add_argument('--skip_to', type=int, default=0,
                            help="Index of source to skip to.")

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
    def image_meta_json(metadata):
        return json.dumps(metadata.to_dict(), indent=2)

    @staticmethod
    def image_annotations_json(image):
        rowcols = []
        for ann in Annotation.objects.filter(image=image).\
                annotate(row=F('point__row'),
                         col=F('point__column'),
                         label_id=F('label__pk')):
            rowcols.append({'row': ann.row, 'col': ann.col, 'label': ann.label_id})
        return json.dumps(rowcols, indent=2)

    def handle(self, *args, **options):

        # Start by exporting the label-set
        c = boto.connect_s3(settings.AWS_ACCESS_KEY_ID, settings.AWS_SECRET_ACCESS_KEY)
        bucket = c.get_bucket(options['bucket'])
        label_set_key = Key(bucket, name=options['name']+'/' + 'label_set.json')
        label_set_key.set_contents_from_string(self.labelset_json)

        # Filter sources
        sources = Source.objects.filter()
        sources = filter_out_test_sources(sources)
        sources = [s for s in sources if
                   s.nbr_confirmed_images > options['min_required_imgs']]
        sources = sources[options['skip_to']:]

        # Iterate over sources
        for itt, source in enumerate(sources):
            print("Exporting source id:{}. [{}({})] with {} images...".format(source.pk, itt+1, len(sources),
                                                                              source.nbr_confirmed_images))
            source_prefix = options['name']+'/'+'s'+str(source.pk)

            # Export source meta
            source_meta_key = Key(bucket, name=source_prefix + '/' + 'meta.json')
            source_meta_key.set_contents_from_string(self.source_meta_json(source))

            images_prefix = source_prefix + '/' + 'images'

            for image in tqdm(Image.objects.filter(source=source,
                                                   confirmed=True,
                                                   features__extracted=True)):

                image_prefix = images_prefix + '/i' + str(image.pk)
                image_key = Key(bucket, name=image_prefix+'.jpg')
                if image_key.exists():
                    # Since we write the image file last, if this exists,
                    # we have already exported this image.
                    continue

                # Export image meta
                source_meta_key = Key(bucket, name=image_prefix + '.meta.json')
                source_meta_key.set_contents_from_string(self.image_meta_json(image.metadata))

                # Export image annotations
                source_meta_key = Key(bucket, name=image_prefix + '.anns.json')
                source_meta_key.set_contents_from_string(self.image_annotations_json(image))

                # Copy image features
                # Check again since state may have changed
                # since the filtering was applied
                image_path = os.path.join(settings.AWS_LOCATION,
                                          image.original_file.name)
                if image.features.extracted:
                    features_path = settings.FEATURE_VECTOR_FILE_PATTERN.format(full_image_path=image_path)
                    bucket.copy_key(image_prefix + '.features.json',
                                    settings.AWS_STORAGE_BUCKET_NAME,
                                    features_path)

                # Copy image file
                bucket.copy_key(image_prefix + '.jpg',
                                settings.AWS_STORAGE_BUCKET_NAME,
                                image_path)

