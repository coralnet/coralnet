import posixpath

import boto
import json
from boto.s3.key import Key

from images.models import Source, Image, Point
from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = 'Tool for submitting feature extraction across sources. '

    def add_arguments(self, parser):

        parser.add_argument('source_id', type=int, nargs='?', help="Source to export")
        parser.add_argument('--nbr_images', type=int, nargs='?', default=10, help="Max number of images to process")
        parser.add_argument('--bucket', type=str, help="bucket name to export to")

    def handle(self, *args, **options):
        # TODO: Update this code in NEXT PR
        raise NotImplementedError('THIS MANAGEMENT TOOL IS NOT COMPLETE NOR TESTED')

        # source = Source.objects.get(id=options['source_id'])
        # images = Image.objects.filter(source=source)[:options['nbr_images']]
        # print('Copying {} images from {} to {}'.format(len(images), settings.AWS_STORAGE_BUCKET_NAME,
        #                                                options['bucket']))
        # c = boto.connect_s3(settings.AWS_ACCESS_KEY_ID, settings.AWS_SECRET_ACCESS_KEY)
        # dst = c.get_bucket(options['bucket'])
        # for img in images:
        #
        #     full_image_path = posixpath.join(settings.AWS_LOCATION, img.original_file.name)
        #     from_name = settings.FEATURE_VECTOR_FILE_PATTERN.format(full_image_path=full_image_path)
        #     to_name = img.metadata.name + '.features.json'
        #     dst.copy_key(to_name, settings.AWS_STORAGE_BUCKET_NAME, from_name)
        #
        #     rowcols = [[point.row, point.column] for point in Point.objects.filter(image=img).order_by('id')]
        #     k = Key(dst)
        #     k.key = img.metadata.name + '.rowcol.json'
        #     k.set_contents_from_string(json.dumps(rowcols))