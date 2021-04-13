from django.core.management.base import BaseCommand

from images.models import Image, Source
from vision_backend.tasks import submit_features


class Command(BaseCommand):
    help = 'Tool for submitting feature extraction across sources. '

    def add_arguments(self, parser):

        parser.add_argument('mode', choices=['individual', 'parallel'], help="Invidual mode submits features "
                                                                             "for all images in sources given "
                                                                             "by --source_ids. paralell mode "
                                                                             "submits --nbr_images from all "
                                                                             "sources on the site. Optional "
                                                                             "argument --confirmed_only means "
                                                                             "that only images that are "
                                                                             "confirmed (annotated by a human) "
                                                                             "are considered.")
        parser.add_argument('--source_ids', type=int, nargs='+', help="List of source ids to process")
        parser.add_argument('--nbr_images', type=int, nargs=1, help="Number of images per source")
        parser.add_argument('--confirmed_only', type=int, default=1, nargs='?', help="Only process confirmed images")
        parser.add_argument('--force', type=int, default=0, nargs='?', help="Force extraction for all images")

    def handle(self, *args, **options):

        confirmed_only = options['confirmed_only']
        force = options['force']

        if options['mode'] == 'individual':
            assert options['source_ids']
            
            print("Running in individual mode and confirmed_only: {}".format(confirmed_only))
            for source_id in options['source_ids']:
                source = Source.objects.get(id=source_id)
                images = Image.objects.filter(source=source)
                if not force:
                    images = images.filter(features__extracted=False)
                if confirmed_only:
                    images = images.filter(annoinfo__confirmed=True)
                    
                print("Submitting {} jobs for {}... ".format(images.count(), source.name))
                
                for image in images:
                    submit_features.delay(image.id, force=force)

        elif options['mode'] == 'parallel':
            assert options['nbr_images']

            nbr_images = options['nbr_images'][0]

            print("Running in parallel mode with {} images and confirmed_only: {}".format(nbr_images, confirmed_only))
            for source in Source.objects.filter().order_by('-id'):

                images = Image.objects.filter(source=source, features__extracted=False)
                if confirmed_only:
                    images = images.filter(annoinfo__confirmed=True)
                images = images[:nbr_images]

                print("Submitting {} jobs for {}... ".format(images.count(), source.name))

                for image in images:
                    submit_features.delay(image.id)
