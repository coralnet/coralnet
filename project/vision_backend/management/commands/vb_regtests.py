from django.core.management.base import BaseCommand

from lib.regtest_utils import VisionBackendRegressionTest


class Command(BaseCommand):
    help = 'Run vision backend regtests.'

    def add_arguments(self, parser):
        parser.add_argument('scope', choices=['small', 'medium', 'large'],
                            help='Chose size: Small ~ 50 images; medium ~ 400 images; large ~ 1600 images')

    def handle(self, *args, **options):
        raise NotImplementedError("The with_anns flag doesn't work currently. All images are uploaded without anns.")
        scope = options['scope']
        if scope == 'small':
            # Only use a small fraction of each source
            for source_id in [372, 504]:
                s = VisionBackendRegressionTest(source_id, scope.upper())
                s.upload_images(20, with_anns=True)
                s.upload_images(5, with_anns=False)

        elif scope == 'medium':
            # Use all from 504, more from 372
            s = VisionBackendRegressionTest(504, scope.upper())
            s.upload_images(100, with_anns=True)
            s.upload_images(15, with_anns=False)

            s = VisionBackendRegressionTest(372, scope.upper())
            s.upload_images(250, with_anns=True)
            s.upload_images(30, with_anns=False)

        elif scope == 'large':
            # Use all from both
            s = VisionBackendRegressionTest(504, scope.upper())
            s.upload_images(100, with_anns=True)
            s.upload_images(15, with_anns=False)

            s = VisionBackendRegressionTest(372, scope.upper())
            s.upload_images(1400, with_anns=True)
            s.upload_images(50, with_anns=False)