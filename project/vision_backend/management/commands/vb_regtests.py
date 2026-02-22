from argparse import RawTextHelpFormatter
import time

from django.core.management.base import BaseCommand

from jobs.models import Job
from jobs.tasks import run_scheduled_jobs
from jobs.tests.utils import do_job
from lib.regtest_utils import VisionBackendRegressionTest
from ...models import Classifier

reg_test_config = {
    372: {'small': (25, 5),
          'medium': (250, 30),
          'large': (1400, 50)},
    504: {'small': (25, 5),
          'medium': (100, 15),
          'large': (100, 15)}
}


class Command(BaseCommand):
    help = '''
        Run vision backend regression tests. Depending on your config
        you can run this reg-test in several modes:
        ## Local immediate
        This is the simplest setting. Local backend, sync tasks, local queue.
        ```
        HUEY_IMMEDIATE=True
        SPACER_QUEUE_CHOICE=vision_backend.queues.LocalQueue
        SETTINGS_BASE=dev-local
        ```
        
        ## Local async
        Here everything is still local, but jobs are executed asynchronously 
        using huey. Make sure the huey consumer is running before starting 
        the test: `python manage.py run_huey`.
        ```
        HUEY_IMMEDIATE=False
        SPACER_QUEUE_CHOICE=vision_backend.queues.LocalQueue
        SETTINGS_BASE=dev-local
        ```
        
        ## S3 async
        Still using the LocalQueue and async tasks, but storage is now on S3. 
        ```
        HUEY_IMMEDIATE=False
        SPACER_QUEUE_CHOICE=vision_backend.queues.LocalQueue
        SETTINGS_BASE=dev-s3
        ```
        ## AWS ECS cluster. 
        This uses the AWS Batch to process the jobs. 
        ```
        HUEY_IMMEDIATE=False
        SPACER_QUEUE_CHOICE=vision_backend.queues.BatchQueue
        SETTINGS_BASE=dev-s3
        ```
        
        Etc. etc. Most combinations work. The only requirement is that if you 
        use the `BatchQueue` you need to use the `dev-s3` setting. 
        
        NOTE: 
        If you use `dev-local` you still need to have AWS configuration in
        your .env to allow access to fixtures and spacer models from s3.
        '''

    latest_job_id: int

    def create_parser(self, *args, **kwargs):
        """ This makes the help text more nicely formatted. """
        parser = super().create_parser(*args, **kwargs)
        parser.formatter_class = RawTextHelpFormatter
        return parser

    def add_arguments(self, parser):
        parser.add_argument(
            '--size',
            type=str,
            choices=['small', 'medium', 'large'],
            default='small',
            help='Choose size: '
                 'Small ~ 50 images; medium ~ 400 images; large ~ 1600 images')
        parser.add_argument(
            '--fixture_source',
            type=int,
            choices=[372, 504],
            default=372,
            help='Choose one of two sources to run your regression test on.')
        parser.add_argument(
            '--vgg16',
            action='store_true',
            help='Use VGG16 feature extractor instead of EfficientNet.')

    def handle(self, *args, **options):

        size = options['size']
        fixture_source_id = options['fixture_source']

        (n_with, n_without) = reg_test_config[fixture_source_id][size]

        self.latest_job_id = Job.objects.latest('pk').pk

        s = VisionBackendRegressionTest(
            fixture_source_id, size.upper(), options['vgg16'])

        print("\n-> Uploading images which have manual annotations...")
        annotated_image_filepaths = s.upload_images(n_with)
        print("\n-> Adding manual annotations...")
        for image_filepath in annotated_image_filepaths:
            s.upload_anns(image_filepath)

        print("\n-> Uploading images which don't have manual annotations...")
        _ = s.upload_images(n_without)

        print("-> Waiting until feature extraction is done...")
        n_imgs = s.source.image_set.count()
        all_have_features = False
        while not all_have_features:
            time.sleep(5)
            run_scheduled_jobs()
            do_job('collect_spacer_jobs')
            n_with_feats = s.source.image_set.with_features().count()
            print(f"-> {n_with_feats} out of {n_imgs} images have features.")
            all_have_features = n_with_feats == n_imgs
            self.check_for_failed_jobs()

        print("-> All images have features!")

        print("-> Waiting until classifier training is done...")
        has_classifier = False
        while not has_classifier:
            time.sleep(5)
            run_scheduled_jobs()
            do_job('collect_spacer_jobs')
            print("-> No classifier trained yet.")
            has_classifier = Classifier.objects.filter(
                source=s.source, status=Classifier.ACCEPTED).count() > 0
            self.check_for_failed_jobs()

        print("-> Classifier trained!")

        print("-> Waiting for non-manually-annotated images to be classified.")
        all_imgs_classified = False
        while not all_imgs_classified:
            time.sleep(5)
            run_scheduled_jobs()
            n_classified = s.source.image_set.unconfirmed().count()
            n_imgs = s.source.image_set.incomplete().count()

            print(
                f"-> {n_classified} out of {n_imgs} non-manually-annotated"
                f" images are classified.")
            all_imgs_classified = n_classified == n_imgs
            self.check_for_failed_jobs()

        print("-> All Done!")

    def check_for_failed_jobs(self):
        failed_jobs = Job.objects.filter(
            status=Job.Status.FAILURE, pk__gt=self.latest_job_id)
        if failed_jobs.exists():
            print("Jobs have failed:")
            for job in failed_jobs:
                print(f"- {job}: {job.result_message}")
            # Next time, only report any new failures
            self.latest_job_id = failed_jobs.latest('pk').pk
