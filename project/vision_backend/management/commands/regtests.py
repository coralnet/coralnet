import pickle
import json
import glob


import os.path as osp

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

from lib.regtest_utils import RegressionTest


class Command(BaseCommand):
    help = 'Run vision backend regtests.'

    def add_arguments(self, parser):
        parser.add_argument('scope', choices=['small', 'medium', 'large'], help='Chose size of regtests. Small ~ 50 images; medium ~ 250 images; large ~ 1200 images; huge ~ 10000 images total.')

    def handle(self, *args, **options):
        scope = options['scope']
        if scope == 'small':
            # Only use a small fraction of each source
            for source_id in [372, 504]:
                s = RegressionTest(source_id, scope.upper())
                s.upload_images(20, with_anns = True)
                s.upload_images(5, with_anns = False)

        elif scope == 'medium':
            # Use all from 504, more from 372
            s = RegressionTest(504, scope.upper())
            s.upload_images(100, with_anns = True)
            s.upload_images(15, with_anns = False)

            s = RegressionTest(372, scope.upper())
            s.upload_images(250, with_anns = True)
            s.upload_images(30, with_anns = False)

        elif scope == 'large':
            # Use all from both
            s = RegressionTest(504, scope.upper())
            s.upload_images(100, with_anns = True)
            s.upload_images(15, with_anns = False)

            s = RegressionTest(372, scope.upper())
            s.upload_images(1400, with_anns = True)
            s.upload_images(50, with_anns = False)            