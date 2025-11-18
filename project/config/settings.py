from collections.abc import MutableMapping
import datetime
from email.utils import parseaddr
from enum import Enum
import os
from pathlib import Path
import sys

import boto3.s3.transfer
# In many cases it's dangerous to import from Django directly into a settings
# module, but ImproperlyConfigured is fine.
from django.core.exceptions import ImproperlyConfigured
import environ
from PIL import ImageFile

# Careful with imports from the project itself, too. But this is a simple
# module that doesn't import from any of our other modules.
from .constants import SpacerJobSpec


# Configure Pillow to be tolerant of image files that are truncated (missing
# data from the last block).
# https://stackoverflow.com/a/23575424/
ImageFile.LOAD_TRUNCATED_IMAGES = True


class CoralNetEnvMapping(MutableMapping):
    """
    Customization for django-environ.

    Make SETTING_NAME in the .env file correspond to CORALNET_SETTING_NAME in
    environment variables.

    __init__, __getitem__, and __setitem__ are the non-trivial part of the
    implementation. The rest is just required to be implemented as a subclass
    of MutableMapping.
    """
    def __init__(self):
        self.env = os.environ

    def __getitem__(self, key):
        return self.env['CORALNET_' + key]

    def __iter__(self):
        for key in self.env:
            yield key

    def __len__(self):
        return len(self.env)

    def __setitem__(self, key, value):
        self.env['CORALNET_' + key] = value

    def __delitem__(self, key):
        del self.env[key]


class CoralNetEnv(environ.Env):
    ENVIRON = CoralNetEnvMapping()

    def path(
        self, var, default: Path | environ.NoValue = environ.Env.NOTSET,
        **kwargs
    ):
        # Use pathlib.Path instead of environ.Path
        return Path(self.get_value(var, default=default))


# The repository's directory.
REPO_DIR = Path(__file__).resolve().parent.parent.parent

env = CoralNetEnv()
# Read environment variables from the system or a .env file.
CoralNetEnv.read_env(REPO_DIR / '.env')


#
# Settings base
#

class Bases(Enum):
    # For the production server
    PRODUCTION = 'production'
    # For the staging server
    STAGING = 'staging'
    # For a developer's environment using local media storage
    DEV_LOCAL = 'dev-local'
    # For a developer's environment using S3 media storage
    DEV_S3 = 'dev-s3'


try:
    SETTINGS_BASE = Bases(env('SETTINGS_BASE'))
except ValueError:
    raise ImproperlyConfigured(
        f"Unsupported SETTINGS_BASE value: {env('SETTINGS_BASE')}"
        f" (supported values are: {', '.join([b.value for b in Bases])})")

_TESTING = 'test' in sys.argv or 'selenium_test' in sys.argv
_SELENIUM = 'selenium_test' in sys.argv


#
# More directories
#

# Base directory of the Django project.
PROJECT_DIR = REPO_DIR / 'project'

# Directory for any site related files, not just the repository.
SITE_DIR = env.path('SITE_DIR', default=REPO_DIR.parent)

# Directory containing log files.
LOG_DIR = SITE_DIR / 'log'

# Directory containing other temporary files. The idea is that any file here
# that's old enough (say, a couple months) should be safe to clean up.
if _TESTING:
    # A TemporaryDirectory might be a cleaner solution here, but
    # would need more instrumentation to ensure that directory gets
    # deleted at the end of the test suite run.
    # Until we figure that out, we'll ensure it's just this one hardcoded
    # dir that gets left behind, rather than one dir per test suite run.
    TMP_DIR = SITE_DIR / 'tmp' / 'test'
    TMP_DIR.mkdir(exist_ok=True)
else:
    TMP_DIR = SITE_DIR / 'tmp'

# Directory containing output files from management commands or scripts.
COMMAND_OUTPUT_DIR = TMP_DIR / 'command_output'
COMMAND_OUTPUT_DIR.mkdir(exist_ok=True)


#
# Debug
#

if SETTINGS_BASE in [Bases.PRODUCTION, Bases.STAGING]:
    DEBUG = False
else:
    # Development environments would typically use DEBUG True, but setting to
    # False is useful sometimes, such as for testing 404 and 500 views.
    DEBUG = env.bool('DEBUG', default=True)


# [CoralNet setting]
# Whether the app is being served through nginx, Apache, etc.
# Situations where it's not:
# - DEBUG True and running any manage.py command
# - runserver
# - unit tests
REAL_SERVER = (
    not DEBUG
    and 'runserver' not in sys.argv
    and not _TESTING
)


#
# Internationalization, localization, time
#

# If you set this to True, Django will use timezone-aware datetimes.
USE_TZ = True

# Local time zone for this installation. All choices can be found here:
# http://en.wikipedia.org/wiki/List_of_tz_zones_by_name (although not all
# systems may support all possibilities). When USE_TZ is True, this is
# interpreted as the default user time zone.
TIME_ZONE = env('TIME_ZONE', default='America/Los_Angeles')

# Language code for this installation. All choices can be found here:
# http://www.i18nguy.com/unicode/language-identifiers.html
LANGUAGE_CODE = 'en-us'

# Supported languages for text translation.
# 'en' includes sublanguages like 'en-us'.
LANGUAGES = [
    ('en', 'English'),
]

# If you set this to False, Django will make some optimizations so as not
# to load the internationalization machinery.
USE_I18N = False


#
# Email
#

# People who get code error notifications.
# In the format: Name 1 <email@example.com>,Name 2 <email@example2.com>

if REAL_SERVER:
    ADMINS = [
        parseaddr(addr.strip())
        for addr in env('ADMINS').split(',')
    ]
else:
    # Some unit tests need at least one admin specified.
    # The address shouldn't matter since a non-real-server setup shouldn't
    # be sending actual emails.
    ADMINS = [('CoralNet Admin', 'admin@coralnet.ucsd.edu')]

# Not-necessarily-technical managers of the site. They get broken link
# notifications and other various emails.
MANAGERS = ADMINS

# E-mail address that error messages come from.
SERVER_EMAIL = env('SERVER_EMAIL', default='noreply@coralnet.ucsd.edu')

# Default email address to use for various automated correspondence
# from the site manager(s).
DEFAULT_FROM_EMAIL = SERVER_EMAIL

# [CoralNet setting]
# Email of the labelset-committee group.
LABELSET_COMMITTEE_EMAIL = env(
    'LABELSET_COMMITTEE_EMAIL', default='coralnet-labelset@googlegroups.com')

# Subject-line prefix for email messages sent with
# django.core.mail.mail_admins or django.core.mail.mail_managers.
# You'll probably want to include the trailing space.
EMAIL_SUBJECT_PREFIX = '[CoralNet] '

if SETTINGS_BASE == Bases.PRODUCTION:
    # Use Amazon SES with auth through boto3, instead of direct SMTP.
    EMAIL_BACKEND = 'django_ses.SESBackend'
elif SETTINGS_BASE == Bases.STAGING:
    # Instead of routing emails through a mail server,
    # just write emails to the filesystem.
    EMAIL_BACKEND = 'django.core.mail.backends.filebased.EmailBackend'
    EMAIL_FILE_PATH = TMP_DIR / 'emails'
else:
    # Development environment:
    # Instead of routing emails through a mail server,
    # just print emails to the console.
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# [django-ses settings]
AWS_SES_REGION_NAME = env('AWS_SES_REGION_NAME', default='us-west-2')
# We don't have backward-compat obligations with v1, so we use v2.
# https://aws.amazon.com/blogs/messaging-and-targeting/upgrade-your-email-tech-stack-with-amazon-sesv2-api/
USE_SES_V2 = True

# Any outgoing email with an element that could get very large (in bytes)
# should truncate/limit that element according to this setting.
# The resulting total size of the email (incorporating other elements, e.g.
# both subject and body) may go above this limit, hence it's a 'soft' limit.
#
# We go for about 100 KB here. We consider the 'hard' limit to be around 10 MB,
# which is where email software may start encountering issues. For example,
# the default max outgoing message size in Postfix seems to be about 10 MB.
# However, CoralNet only anticipates sending emails of pure text, and 10 MB
# generally has images and attachment in mind. So, anything greater than 100 KB
# is most likely a stack trace or data structure which isn't useful to print in
# its entirety.
EMAIL_SIZE_SOFT_LIMIT = 100000


#
# Database related
#

if _SELENIUM:
    _DEFAULT_DATABASE_ENGINE = 'django.db.backends.sqlite3'
    _DATABASE_NAME = env(
        'SELENIUM_DATABASE_PATH',
        default=str(TMP_DIR / f"test_{env('DATABASE_NAME')}.sqlite3"),
    )
else:
    _DEFAULT_DATABASE_ENGINE = 'django.db.backends.postgresql'
    _DATABASE_NAME = env('DATABASE_NAME')

_DATABASE_ENGINE = env('DATABASE_ENGINE', default=_DEFAULT_DATABASE_ENGINE)

# Whether to run migrations as part of the test runner's database setup.
#
# True makes it easier to maintain correctness, since the migrations are the
# first source of truth for creation of initial data, such as the Imported
# and Alleviate users.
# False can speed up test database setup, and paper over a DB engine's
# inability to run all the migrations.
# The JSONFields in some of the earlier migrations are Postgres-only, hence
# our definition of the default value.
TEST_DATABASE_MIGRATE = env.bool(
    'TEST_DATABASE_MIGRATE', default='postgresql' in _DATABASE_ENGINE)

# https://docs.djangoproject.com/en/5.1/ref/models/querysets/#distinct
# "On PostgreSQL only, you can pass positional arguments (*fields) in order
# to specify the names of fields to which the DISTINCT should apply.
# This translates to a SELECT DISTINCT ON SQL query."
# If we can't use DISTINCT ON, we won't necessarily take the trouble to aim
# for correctness, but we'll at least return something of the expected type.
USE_DISTINCT_ON = 'postgresql' in _DATABASE_ENGINE

# Django's database connection info setting.
DATABASES = {
    'default': {
        'ENGINE': _DATABASE_ENGINE,
        # If True, wraps each request (view function) in a transaction by
        # default. Individual view functions can override this behavior with
        # the non_atomic_requests decorator.
        'ATOMIC_REQUESTS': True,
        # Database name, or path to database file if using sqlite3.
        'NAME': _DATABASE_NAME,
        # Not used with sqlite3.
        'USER': env('DATABASE_USER'),
        # Not used with sqlite3.
        'PASSWORD': env('DATABASE_PASSWORD'),
        # Set to empty string for localhost. Not used with sqlite3.
        'HOST': env('DATABASE_HOST', default=''),
        # Set to empty string for default (e.g. 5432 for postgresql).
        # Not used with sqlite3.
        'PORT': env('DATABASE_PORT', default=''),
        'TEST': {
            'MIGRATE': TEST_DATABASE_MIGRATE,
        },
    },
}

# Default auto-primary-key field type for the database.
# TODO: From Django 3.2 onward, the default for this setting is BigAutoField,
#  but we set it to AutoField to postpone the work of migrating existing
#  fields. We should do that work sometime, though.
DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'


#
# Upload/data restrictions
#

MAX_POINTS_PER_IMAGE = 1000

# The maximum size (in bytes) that an upload will be before it
# gets streamed to the file system.
#
# The value in this base settings module should match what we want for the
# production server. Each developer's settings module can override this
# as needed.
FILE_UPLOAD_MAX_MEMORY_SIZE = 52428800  # 50 MB

# The maximum size for a request body (not counting file uploads).
# Due to metadata-edit not having an image limit yet, this needs to be quite
# big.
DATA_UPLOAD_MAX_MEMORY_SIZE = 52428800  # 50 MB

# Maximum number of GET/POST parameters that are parsed from a single request.
# Due to metadata-edit not having an image limit yet, this needs to be quite
# large (each image would have about 20 fields).
DATA_UPLOAD_MAX_NUMBER_FIELDS = 2500*20

# Maximum number of files that may be received via POST in a
# multipart/form-data encoded request before a SuspiciousOperation
# (TooManyFiles) is raised.
# Default 100.
# Main concern for coralnet is CPC upload. Ideally that page would be reworked
# so that files are uploaded in batches, rather than all in a single request.
# But until then, we'll have a fairly high limit here.
DATA_UPLOAD_MAX_NUMBER_FILES = 1000

# Although the name of this setting implies it's just for file uploads, it also
# applies to the collectstatic command, which is our primary use case.
# We prefer collectstatic to create group-writable files, so that multiple
# users in the www-data group can update the same files.
# This setting doesn't seem to apply to diskcache's Django cache files though.
FILE_UPLOAD_PERMISSIONS = 0o664

# [CoralNet settings]
IMAGE_UPLOAD_MAX_FILE_SIZE = 30*1024*1024  # 30 MB
IMAGE_UPLOAD_MAX_DIMENSIONS = (8000, 8000)
IMAGE_UPLOAD_ACCEPTED_CONTENT_TYPES = [
    # https://www.sitepoint.com/web-foundations/mime-types-complete-list/
    'image/jpeg',
    'image/pjpeg',  # Progressive JPEG
    'image/png',
    'image/mpo',
]
CSV_UPLOAD_MAX_FILE_SIZE = 30*1024*1024  # 30 MB

# [CoralNet setting]
# Sometimes we specify a really large queryset and anticipate that our code
# will induce Django to load it all into memory. For example, QuerySet.delete()
# seems to do this if there are any SET_NULL foreign keys pointing to the model
# in question. In these cases, we can code it in such a way that the objects
# are loaded in chunks so that we don't run out of memory.
QUERYSET_CHUNK_SIZE = 100000


#
# PySpacer and the vision backend
#

# How many more annotated images are required before we try to train a new
# classifier.
NEW_CLASSIFIER_TRAIN_TH = 1.1

# How much better than previous classifiers must a new one be in order to get
# accepted.
NEW_CLASSIFIER_IMPROVEMENT_TH = 1.01

# This many images must be annotated before a first classifier is trained.
# Can't set this lower than 3, since at least 1 train, 1 ref, and 1 val image
# are needed for training.
if _TESTING:
    # Speed up tests' training setup by requiring as few images as possible.
    TRAINING_MIN_IMAGES = 3
else:
    TRAINING_MIN_IMAGES = env.int('TRAINING_MIN_IMAGES', default=20)

# Naming schemes
FEATURE_VECTOR_FILE_PATTERN = '{full_image_path}.featurevector'
ROBOT_MODEL_FILE_PATTERN = 'classifiers/{pk}.model'
ROBOT_MODEL_TRAINDATA_PATTERN = 'classifiers/{pk}.traindata'
ROBOT_MODEL_VALDATA_PATTERN = 'classifiers/{pk}.valdata'
ROBOT_MODEL_VALRESULT_PATTERN = 'classifiers/{pk}.valresult'

# Naming for vision_backend.models.BatchJob
BATCH_JOB_PATTERN = 'batch_jobs/{pk}_job_msg.json'
BATCH_RES_PATTERN = 'batch_jobs/{pk}_job_res.json'

# Method of selecting images for the validation set vs. the training set.
# See Image.valset() definition for the possible choices and how they're
# implemented.
if _TESTING:
    # Selection should be completely predictable in unit tests.
    VALSET_SELECTION_METHOD = 'name'
else:
    VALSET_SELECTION_METHOD = 'id'

# This indicates the max number of scores we store per point.
NBR_SCORES_PER_ANNOTATION = 5

# This is the number of epochs we request the SGD solver to take over the data.
NBR_TRAINING_EPOCHS = 10

# Batch size for pyspacer's batching of training-annotations.
TRAINING_BATCH_LABEL_COUNT = 5000

# Feature caching can greatly speed up pyspacer training, but might make
# training fail if the amount to cache approaches the available storage space.
#
# Since we no longer accept legacy-format (pre-2021) features for training,
# we can expect feature vectors to be about 5.5 KB per point. (Legacy ones
# were about 8x bigger.)
# As of 2024/04, CoralNet's AWS Batch instances use 30 GB storage volumes.
# That should leave at least 15 GB for feature caching.
# 15 GB divided by 5.5 KB = a little over 2.5 million points. So we'll use
# that as the default limit for allowing feature caching in training.
FEATURE_CACHING_ANNOTATION_LIMIT = env(
    'FEATURE_CACHING_ANNOTATION_LIMIT', default=2500000)

# Don't let a source check schedule more than this much classification 'work'
# in one go.
# See check_source() for how work is calculated as a function of images and
# points.
# Since classify-features jobs happen on the web server instead of in
# Batch, there's a risk of monopolizing the web server resources (namely, the
# processes allocated for background jobs) if there is no limit here.
SOURCE_CLASSIFICATIONS_MAX_WORK = 100000

# Spacer job hash to identify this server instance's jobs in the AWS Batch
# dashboard.
SPACER_JOB_HASH = env('SPACER_JOB_HASH', default='default_hash')

# [PySpacer setting]
SPACER = {
    # Filesystem directory for caching feature extractor files.
    # Expects str, not Path.
    'EXTRACTORS_CACHE_DIR': str(SITE_DIR / 'spacer_models'),

    'MAX_IMAGE_PIXELS': (
        IMAGE_UPLOAD_MAX_DIMENSIONS[0] * IMAGE_UPLOAD_MAX_DIMENSIONS[1]),
    'MAX_POINTS_PER_IMAGE': MAX_POINTS_PER_IMAGE,

    'TRAINING_BATCH_LABEL_COUNT': TRAINING_BATCH_LABEL_COUNT,
}

# If True, feature extraction just returns dummy results. This helps by
# speeding up testing.
if _TESTING:
    FORCE_DUMMY_EXTRACTOR = True
else:
    FORCE_DUMMY_EXTRACTOR = env.bool('FORCE_DUMMY_EXTRACTOR', default=DEBUG)

if not FORCE_DUMMY_EXTRACTOR:
    # [CoralNet setting]
    # Non-dummy feature extractors need to live at the root of this
    # S3 bucket, using the filenames expected by get_extractor().
    EXTRACTORS_BUCKET = env('EXTRACTORS_BUCKET')

# Type of queue to keep track of vision backend jobs.
if SETTINGS_BASE in [Bases.PRODUCTION, Bases.STAGING]:
    SPACER_QUEUE_CHOICE = 'vision_backend.queues.BatchQueue'
else:
    SPACER_QUEUE_CHOICE = env(
        'SPACER_QUEUE_CHOICE', default='vision_backend.queues.LocalQueue')


# If AWS Batch is being used, these job queue and job definition names are
# used depending on the specs of the requested job.
if SETTINGS_BASE == Bases.PRODUCTION:
    BATCH_QUEUES = {
        SpacerJobSpec.MEDIUM: 'production',
        SpacerJobSpec.HIGH: 'production-highspec',
    }
    BATCH_JOB_DEFINITIONS = {
        SpacerJobSpec.MEDIUM: 'spacer-job',
        SpacerJobSpec.HIGH: 'spacer-highspec',
    }
else:
    BATCH_QUEUES = {
        SpacerJobSpec.MEDIUM: 'staging',
        SpacerJobSpec.HIGH: 'staging-highspec',
    }
    BATCH_JOB_DEFINITIONS = {
        SpacerJobSpec.MEDIUM: 'spacer-job-staging',
        SpacerJobSpec.HIGH: 'spacer-highspec-staging',
    }

# How the spec level's decided for individual job types.
# These thresholds should be specified from high to low.
FEATURE_EXTRACT_SPEC_PIXELS = [
    (SpacerJobSpec.HIGH, 6000*6000),
    (SpacerJobSpec.MEDIUM, 0),
]
TRAIN_SPEC_ANNOTATIONS = [
    (SpacerJobSpec.HIGH, 10000*20),
    (SpacerJobSpec.MEDIUM, 0),
]

AWS_BATCH_REGION = env('AWS_BATCH_REGION', default='us-west-2')


#
# General AWS and S3 config
#
# It's hard to programmatically define when these settings are needed or not.
# So, if you need them, remember to specify them in .env; there won't be an
# ImproperlyConfigured check here.
#

# [django-storages settings]
# http://django-storages.readthedocs.io/en/latest/backends/amazon-S3.html
AWS_ACCESS_KEY_ID = env('AWS_ACCESS_KEY_ID', default=None)
AWS_SECRET_ACCESS_KEY = env('AWS_SECRET_ACCESS_KEY', default=None)
AWS_S3_TRANSFER_CONFIG = boto3.s3.transfer.TransferConfig(
    # Disables using threads for S3 requests, preventing errors such as
    # `RuntimeError: cannot schedule new futures after interpreter shutdown`
    # More info on how this relates to the error:
    # https://github.com/jschneier/django-storages/pull/1112
    # https://github.com/etianen/django-s3-storage/pull/136
    #
    # Formerly set by the django-storages setting AWS_S3_USE_THREADS
    # (deprecated starting from django-storages 1.14).
    use_threads=False,
)

# [PySpacer settings]
SPACER['AWS_ACCESS_KEY_ID'] = AWS_ACCESS_KEY_ID
SPACER['AWS_SECRET_ACCESS_KEY'] = AWS_SECRET_ACCESS_KEY

# [CoralNet setting]
# Name of the CoralNet regtests S3 bucket.
REGTEST_BUCKET = 'coralnet-regtest-fixtures'


#
# Media file storage
#

if SETTINGS_BASE == Bases.DEV_LOCAL:

    # Default file storage mechanism that holds media.
    _STORAGES_DEFAULT = dict(
        BACKEND='lib.storage_backends.MediaStorageLocal',
    )

    # Absolute filesystem path to the directory that will hold user-uploaded
    # files.
    # Example: "/home/media/media.lawrence.com/media/"
    # This setting only applies when such files are saved to a filesystem path,
    # not when they are uploaded to a cloud service like AWS.
    MEDIA_ROOT = SITE_DIR / 'media'

    # Base URL where user-uploaded media are served.
    if DEBUG:
        # Django will serve the contents of MEDIA_ROOT here.
        # The code that does the serving is in the root urlconf.
        MEDIA_URL = '/media/'
    else:
        # Need to serve media to a localhost URL or something.
        # See .env.dist for an explanation.
        MEDIA_URL = env('MEDIA_URL')

else:

    # [django-storages setting]
    # http://django-storages.readthedocs.io/en/latest/backends/amazon-S3.html
    AWS_STORAGE_BUCKET_NAME = env('AWS_STORAGE_BUCKET_NAME')

    # [django-storages setting]
    # Default ACL permissions when saving S3 files.
    # 'private' means the bucket-owning AWS account has full permissions, and
    # no one else has permissions. Further permissions can be specified in the
    # bucket policy or in the IAM console.
    AWS_DEFAULT_ACL = 'private'

    # [django-storages setting]
    # Tell the S3 storage class's get_available_name() method to add a suffix if
    # the file already exists. This is what Django's default storage class does,
    # but the django-storages default behavior is to never add a suffix.
    AWS_S3_FILE_OVERWRITE = False

    # [CoralNet settings]
    # S3 details on storing media.
    AWS_S3_REGION = env('AWS_S3_REGION', default='us-west-2')
    SPACER['AWS_REGION'] = AWS_S3_REGION
    AWS_S3_DOMAIN = \
        f's3-{AWS_S3_REGION}.amazonaws.com/{AWS_STORAGE_BUCKET_NAME}'
    AWS_S3_MEDIA_SUBDIR = 'media'

    # Base URL where user-uploaded media are served.
    # Example: "http://media.lawrence.com/media/"
    MEDIA_URL = f'https://{AWS_S3_DOMAIN}/{AWS_S3_MEDIA_SUBDIR}/'

    # [django-storages setting]
    # S3 bucket subdirectory in which to store media.
    AWS_LOCATION = AWS_S3_MEDIA_SUBDIR

    # Default file storage mechanism that holds media.
    _STORAGES_DEFAULT = dict(
        BACKEND='lib.storage_backends.MediaStorageS3',
    )


#
# Static file storage
#

# A list of locations of additional static files
# (besides apps' "static/" subdirectories, which are automatically included)
STATICFILES_DIRS = [
    # Project-wide static files
    PROJECT_DIR / 'static',
]

# The default file storage backend used during the build process.
#
# ManifestStaticFilesStorage appends a content-based hash to the filename
# to facilitate browser caching.
# This hash appending happens as a post-processing step in collectstatic, so
# it only applies to DEBUG False.
# It also isn't for use during unit tests, so in that case we use the default
# static files storage backend.
# https://docs.djangoproject.com/en/dev/ref/contrib/staticfiles/#manifeststaticfilesstorage
if _TESTING:
    _STORAGES_BACKEND_STATICFILES = \
        'django.contrib.staticfiles.storage.StaticFilesStorage'
else:
    _STORAGES_BACKEND_STATICFILES = \
        'django.contrib.staticfiles.storage.ManifestStaticFilesStorage'

# Absolute path to the directory which static files should be collected to.
# Example: "/home/media/media.lawrence.com/static/"
#
# To collect static files in STATIC_ROOT, first ensure that your static files
# are in apps' "static/" subdirectories and in STATICFILES_DIRS. Then use the
# collectstatic management command.
# Don't put anything in STATIC_ROOT manually.
#
# Then, use your web server's settings (e.g. nginx, Apache) to serve
# STATIC_ROOT at the STATIC_URL.
# This is done outside of Django, but the docs have some implementation
# suggestions. Basically, you either serve directly from the STATIC_ROOT
# with nginx, or you push the STATIC_ROOT to a separate static-file server
# and serve from there.
# https://docs.djangoproject.com/en/dev/howto/static-files/deployment/
#
# This only is used when DEBUG = False. When DEBUG = True, static files
# are served automagically with django.contrib.staticfiles.views.serve().
#
# Regardless of DEBUG, as long as we're using ManifestStaticFilesStorage,
# this setting is required. Otherwise, Django gets an
# ImproperlyConfiguredError. So, even devs need this value set to something.
STATIC_ROOT = SITE_DIR / 'static_serve'

# URL that handles the static files served from STATIC_ROOT.
# Example: "http://media.lawrence.com/static/"
# If DEBUG is False, remember to use the collectstatic command.
if not DEBUG and not REAL_SERVER:
    # If running with runserver + DEBUG False, you'll probably want to
    # use something like `python -m http.server 8080` in your STATIC_ROOT,
    # and provide the local-host URL here.
    STATIC_URL = env('STATIC_URL')
else:
    # If DEBUG is True, static files are served automagically with the
    # static-serve view.
    # Otherwise, make sure your server software (e.g. nginx) serves static
    # files at this URL relative to your domain.
    STATIC_URL = '/static/'


# Overall storages setting.

STORAGES = {
    'default': _STORAGES_DEFAULT,
    'staticfiles': {
        'BACKEND': _STORAGES_BACKEND_STATICFILES,
    },
    # easy_thumbnails does provide its own storage class, but we don't
    # need that class's functionality because we don't use the
    # THUMBNAIL_MEDIA_ROOT or THUMBNAIL_MEDIA_URL settings.
    'easy_thumbnails': _STORAGES_DEFAULT,
}

if (
    SPACER_QUEUE_CHOICE == 'vision_backend.queues.BatchQueue'
    and
    STORAGES['default']['BACKEND'] == 'lib.storage_backends.MediaStorageLocal'
    and
    not _TESTING
):
    # We only raise this in non-test environments, because some tests
    # are able to use mocks to test BatchQueue while sticking with
    # local storage.
    raise ImproperlyConfigured(
        "Can not use Remote queue with local storage."
        " Please use S3 storage."
    )


#
# Authentication, security, web server
#

AUTHENTICATION_BACKENDS = [
    # Our subclass of Django's default backend.
    # Allows sign-in by username or email.
    'accounts.auth_backends.UsernameOrEmailModelBackend',
    # django-guardian's backend for per-object permissions.
    # Should be fine to put either before or after the main backend.
    # https://django-guardian.readthedocs.io/en/stable/configuration.html
    'guardian.backends.ObjectPermissionBackend',
]

# Don't expire the sign-in session when the user closes their browser
# (Unless set_expiry(0) is explicitly called on the session).
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
# The age of session cookies, in seconds.
SESSION_COOKIE_AGE = 60 * 60 * 24 * 30

# A secret key for this particular Django installation. Used in secret-key
# hashing algorithms.
# Make this unique.
SECRET_KEY = env('SECRET_KEY')

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'source_list'

# The list of validators that are used to check the strength of user passwords.
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {
            'min_length': 10,
        }
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher',
    # This hasher assists in strengthening security for users who haven't
    # logged in since PBKDF2 became the default.
    'accounts.hashers.PBKDF2WrappedSHA1PasswordHasher',
    'django.contrib.auth.hashers.Argon2PasswordHasher',
    'django.contrib.auth.hashers.BCryptSHA256PasswordHasher',
]

# [django-registration setting]
# The number of days users will have to activate their accounts after
# registering. If a user does not activate within that period,
# the account will remain permanently inactive
# unless a site administrator manually activates it.
ACCOUNT_ACTIVATION_DAYS = 7

# [CoralNet setting]
# The number of hours users will have to confirm an email change after
# requesting one.
EMAIL_CHANGE_CONFIRMATION_HOURS = 24

if REAL_SERVER:

    # [CoralNet setting]
    # The site domain, for the Django sites framework. This is used in places
    # such as links in password reset emails, and 'view on site' links in the
    # admin site's blog post edit view.
    SITE_DOMAIN = env('SITE_DOMAIN')

    # Hosts/domain names that are valid for this site.
    ALLOWED_HOSTS = [SITE_DOMAIN]

    # Use HTTPS.
    # For staging, this can mean using a self-signed certificate.
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

    # This setting is needed since our nginx config connects to Django with a
    # non-HTTPS proxy_pass.
    # https://docs.djangoproject.com/en/dev/ref/settings/#secure-proxy-ssl-header
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

    WSGI_APPLICATION = 'config.wsgi.application'

else:

    SITE_DOMAIN = env('SITE_DOMAIN', default='127.0.0.1:8000')

    # "*" matches anything, ".example.com" matches example.com and all
    # subdomains
    #
    # When DEBUG is True and ALLOWED_HOSTS is empty,
    # the host is validated against ['.localhost', '127.0.0.1', '[::1]'].
    # (That's: localhost or subdomains thereof, IPv4 loopback, and IPv6
    # loopback)
    # https://docs.djangoproject.com/en/dev/ref/settings/#allowed-hosts
    #
    # Here we add 'testserver' on top of that, which is needed for a dev server
    # to run the submit_deploy management command and the regtests.
    ALLOWED_HOSTS = ['.localhost', '127.0.0.1', '[::1]', 'testserver']

    # No HTTPS.
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False
    SECURE_PROXY_SSL_HEADER = None


#
# Async jobs
#

# [django-rest-framework setting]
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        # Log in, get cookies, and browse. Like any non-API website. This is
        # intended for use by the CoralNet website frontend.
        'rest_framework.authentication.SessionAuthentication',
        # Token authentication without OAuth. This is intended for use by
        # non-website applications, such as command line.
        'rest_framework.authentication.TokenAuthentication',
    ],
    'DEFAULT_PARSER_CLASSES': [
        'api_core.parsers.JSONAPIParser',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        # Must be authenticated to use the API.
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_RENDERER_CLASSES': [
        'api_core.renderers.JSONAPIRenderer',
        'rest_framework.renderers.BrowsableAPIRenderer',
    ],
    'DEFAULT_THROTTLE_CLASSES': [
        # These classes allow us to define multiple throttle rates. If either
        # rate is met, subsequent requests are throttled.
        'api_core.utils.BurstRateThrottle',
        'api_core.utils.SustainedRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        # Each of these rates are tracked per user. That means per registered
        # user, or per IP address if not logged in.
        'burst': '60/min',
        'sustained': '1000/hour',
    },
    'EXCEPTION_HANDLER': 'api_core.exceptions.exception_handler',
}
# [CoralNet setting]
# Additional API-throttling policy for async jobs.
USER_DEFAULT_MAX_ACTIVE_API_JOBS = env.int(
    'USER_DEFAULT_MAX_ACTIVE_API_JOBS', default=5)

HUEY_IMMEDIATE = env.bool('HUEY_IMMEDIATE', default=DEBUG)

# [django-huey setting]
# https://github.com/gaiacoop/django-huey#configuration
DJANGO_HUEY = {
    # Dict key of default queue. We make background the default since we expect
    # most task definitions to use that queue.
    'default': 'background',
    'queues': {
        # The following dicts are each what the HUEY setting would accept if
        # using huey standalone.
        # https://huey.readthedocs.io/en/latest/django.html#setting-things-up
        #
        # The request/response cycle is top priority for low latency.
        # The 'realtime' task queue is second priority.
        # The 'background' task queue is third priority.
        'realtime': {
            'name': 'realtime_tasks',
            # Don't store return values of tasks.
            'results': False,
            # Whether to run tasks immediately in the webserver's thread,
            # or to schedule them to be run by a worker as normal.
            'immediate': HUEY_IMMEDIATE,
            'consumer': {
                # No periodic tasks in this queue.
                'periodic': False,
            }
        },
        'background': {
            'name': 'background_tasks',
            'results': False,
            'immediate': HUEY_IMMEDIATE,
            'consumer': {
                # Whether to run huey-registered periodic tasks or not.
                'periodic': env.bool('HUEY_CONSUMER_PERIODIC', default=True),
            }
        }
    }
}

# [CoralNet settings]
# Whether to periodically run CoralNet-managed (not huey-registered)
# periodic jobs. Can be useful to disable for certain tests.
ENABLE_PERIODIC_JOBS = True
# Days until we purge old async jobs.
JOB_MAX_DAYS = 30
# Page size when listing async jobs.
JOBS_PER_PAGE = 100
# Potentially long-running jobs should try to finish up once this
# amount of time passes. By defining a duration cap, we have better
# chances to gracefully shut down the server (without force-stopping
# jobs).
# For example, the supervisor `stopwaitsecs` parameter for the huey
# process can be twice this duration.
JOB_MAX_MINUTES = 10


#
# Other Django stuff
#

# [Helper variable]
CORALNET_APPS = [
    'accounts',
    'annotations',
    'api_core',
    'api_management',
    'async_media',
    'blog',
    'calcification',
    # Uploading from and exporting to Coral Point Count file formats
    'cpce',
    # Saves internal server error messages for viewing in the admin site
    'errorlogs.apps.ErrorlogsConfig',
    # Logs of site events/actions
    'events',
    'export',
    # Flatpages-related customizations
    'flatpages_custom',
    'images',
    # Asynchronous job/task management
    'jobs',
    'labels',
    # Miscellaneous / not specific to any other app
    'lib',
    # World map of sources
    'map',
    # Logs of site events/actions (likely being replaced by 'events')
    'newsfeed',
    'sources',
    'upload',
    'visualization',
    'vision_backend',
    'vision_backend_api',
]

# A list of strings designating all applications that are enabled in this
# Django installation.
#
# When several applications provide different versions of the same resource
# (template, static file, management command, translation), the application
# listed first in INSTALLED_APPS has precedence.
# We do have cases where we want to override default templates with our own
# (e.g. auth and registration pages), so we'll put our apps first.
#
# If an app has an application configuration class, specify the dotted path
# to that class here, rather than just specifying the app package.
INSTALLED_APPS = [
    *CORALNET_APPS,

    # Admin site (<domain>/admin)
    'django.contrib.admin',
    # Admin documentation
    'django.contrib.admindocs',
    # User authentication framework
    # https://docs.djangoproject.com/en/dev/topics/auth/
    'django.contrib.auth',
    # Allows permissions to be associated with models you create
    'django.contrib.contenttypes',
    # Store "flat" content pages like Help and FAQ in the database, and edit
    # them via the admin interface
    'django.contrib.flatpages',
    # Has Django template filters to 'humanize' data, like adding thousands
    # separators to numbers
    'django.contrib.humanize',
    'django.contrib.messages',
    'django.contrib.sessions',
    # Sites framework:
    # https://docs.djangoproject.com/en/dev/ref/contrib/sites/
    # "Strongly encouraged" to use by the
    # Django docs, even if we only have one site:
    # https://docs.djangoproject.com/en/dev/ref/contrib/sites/#how-django-uses-the-sites-framework
    'django.contrib.sites',
    'django.contrib.staticfiles',
    # Required for overriding built-in widget templates
    # https://docs.djangoproject.com/en/dev/ref/forms/renderers/#templatessetting
    'django.forms',

    # Extension of huey's contrib.djhuey package; for async tasks
    'django_huey',
    'easy_thumbnails',
    'guardian',
    'markdownx',
    # REST API
    'rest_framework',
    # rest_framework's TokenAuthentication
    'rest_framework.authtoken',
    'reversion',
    'storages',
]

# The order of middleware classes is important!
# https://docs.djangoproject.com/en/dev/topics/http/middleware/
MIDDLEWARE = [
    'django.middleware.common.CommonMiddleware',
    # Save error logs to the database
    'errorlogs.middleware.SaveLogsToDatabaseMiddleware',
    # Manages sessions across requests; required for auth
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    # Clickjacking protection
    # https://docs.djangoproject.com/en/dev/ref/clickjacking/
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # Associates users with requests across sessions; required for auth
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    # Log when each view starts and ends.
    # Should be after AuthenticationMiddleware so we can log the user ID of
    # each request to understand usage patterns. (ID, not username, to keep
    # things relatively anonymous)
    'lib.middleware.ViewLoggingMiddleware',
    # Provide a cache which persists for the duration of the view.
    'lib.middleware.ViewScopedCacheMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',

    # django-reversion
    'reversion.middleware.RevisionMiddleware',
]

if _TESTING:
    # For most tests, use a local memory cache instead of a filesystem cache,
    # because there's no reason to persist the cache after a particular test is
    # over. And having to clean up those files after each test is slower +
    # more issue-prone than just using memory.
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'test',
        }
    }
else:
    # File-based cache:
    # https://grantjenks.com/docs/diskcache/tutorial.html#djangocache
    #
    # We don't use Django's stock FileBasedCache because it culls entries
    # randomly. We want some control over culling priority, like with
    # expiration dates (see cull_limit comments below).
    #
    # We don't use Django's stock local-memory cache because it saves
    # entries per-process, with no possibility of passing between
    # multiple gunicorn worker processes.
    #
    # Other than that, file-based seems a bit easier to manage/debug than
    # memory-based, and seems good enough speed-wise for our use case.
    CACHES = {
        'default': {
            'BACKEND': 'diskcache.DjangoCache',
            'LOCATION': TMP_DIR / 'django_cache',
            # DiskCache: Horizontal partitioning of cache entries. 8 is the
            # default, but we're setting it explicitly to emphasize that
            # culling and the cull_limit (see below) only applies within a
            # particular shard.
            'SHARDS': 8,
            # DiskCache: How many seconds to allow to access the DiskCache
            # SQLite database which lives in LOCATION. Default 0.010.
            'DATABASE_TIMEOUT': 0.5,
            'OPTIONS': {
                # DiskCache: Maximum number of expired keys to cull when adding
                # a new item. 10 is the default, but we're setting it
                # explicitly to emphasize that this behavior of actively
                # culling expired keys is important to us.
                # We'll make one-time-use async media keys expire quickly,
                # and make performance keys (e.g. label_details) expire
                # very rarely.
                'cull_limit': 10,
            },
        }
    }

ROOT_URLCONF = 'config.urls'

# A list containing the settings for all template engines to be used
# with Django. Each item of the list is a dictionary containing the
# options for an individual engine.
# https://docs.djangoproject.com/en/dev/ref/settings/#templates
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [
            PROJECT_DIR / 'templates',
        ],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                # Adds current user and permissions to the template context.
                'django.contrib.auth.context_processors.auth',
                'django.template.context_processors.debug',
                'django.template.context_processors.i18n',
                'django.template.context_processors.media',
                # Adds 'request' (current HttpRequest) to the context.
                'django.template.context_processors.request',
                'django.template.context_processors.static',
                'django.template.context_processors.tz',
                'django.contrib.messages.context_processors.messages',
                # Adds relevant CoralNet settings to the context.
                'lib.context_processors.coralnet_settings',
            ],
        },
    },
]

# Use this class by default for rendering forms, i.e. when using
# {{ my_form }} in a template.
# Individual Form classes can specify a default_renderer attribute to
# override this.
FORM_RENDERER = 'lib.forms.GridFormRenderer'

# For the Django sites framework
SITE_ID = 1

# [Helper variable]
# CORALNET_APPS elements are either just the app dir's name, or are dotted
# Python paths to the app's custom AppConfig class.
# This code grabs just the app dir's name in both cases.
CORALNET_APP_DIRS = [app_config.split('.')[0] for app_config in CORALNET_APPS]

# https://docs.djangoproject.com/en/dev/topics/logging/#configuring-logging
LOGGING = {
    'version': 1,
    # Existing (default) logging includes error emails to admins,
    # so we want to keep it.
    'disable_existing_loggers': False,
    'formatters': {
        # https://docs.python.org/3/library/logging.html#logrecord-attributes
        'standard': {
            'format': (
                '%(asctime)s - %(levelname)s:%(name)s'
                ' - p%(process)d/t%(thread)d\n%(message)s')
        },
        'views': {
            # This is meant to be converted to a SSV easily. `message` has
            # multiple semicolon-separated values within it as well.
            # We go for semicolons instead of commas because it's a bit of a
            # hassle to make asctime use something besides a comma before
            # the milliseconds.
            'format': ';'.join([
                '%(asctime)s',
                'p%(process)d',
                't%(thread)d',
                '%(message)s',
            ]),
        },
    },
    'handlers': {
        'coralnet': {
            'level': 'INFO',
            # Filesize-based rotation for info level. When there's
            # less server activity, having logs of this level from
            # farther in the past can be nice to have, and has little
            # impact on disk space.
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': LOG_DIR / 'coralnet.log',
            'formatter': 'standard',
            # 3 files having 5 MB of logs each
            'maxBytes': 5000000,
            'backupCount': 3,
        },
        'coralnet_debug': {
            'level': 'DEBUG',
            # Time-based rotation for debug level. The rate this can
            # grow is less predictable than info level, and we want
            # to ensure at least a few days' worth of these logs.
            'class': 'logging.handlers.TimedRotatingFileHandler',
            'filename': LOG_DIR / 'coralnet_debug.log',
            'formatter': 'standard',
            # 3 files having 3 days of logs each
            'when': 'D',
            'interval': 3,
            'backupCount': 3,
        },
        'coralnet_views_tasks': {
            'level': 'INFO',
            'class': 'logging.handlers.TimedRotatingFileHandler',
            'filename': LOG_DIR / 'coralnet_views_tasks.ssv',
            'formatter': 'views',
            # 3 files having 3 days of logs each
            'when': 'D',
            'interval': 3,
            'backupCount': 3,
        },
        'coralnet_views_tasks_debug': {
            'level': 'DEBUG',
            'class': 'logging.handlers.TimedRotatingFileHandler',
            'filename': LOG_DIR / 'coralnet_views_tasks_debug.ssv',
            'formatter': 'views',
            # 3 files having 1 day of logs each
            'when': 'D',
            'interval': 1,
            'backupCount': 3,
        },
    },
    'loggers': {
        'coralnet_views': {
            'handlers': ['coralnet_views_tasks', 'coralnet_views_tasks_debug'],
            'level': 'DEBUG',
        },
        'coralnet_tasks': {
            'handlers': ['coralnet_views_tasks', 'coralnet_views_tasks_debug'],
            'level': 'DEBUG',
        },
        **{
            CORALNET_APP_DIR: {
                'handlers': ['coralnet', 'coralnet_debug'],
                'level': 'DEBUG',
            }
            for CORALNET_APP_DIR in CORALNET_APP_DIRS + ['spacer']
        }
    },
}
# This can help with debugging DB queries.
# Note: you must set django.db.connection.force_debug_cursor to True
# before the code of interest to actually log any non-schema queries.
# Then set to False when you don't need to log any more.
if env.bool('LOG_DATABASE_QUERIES', default=False):
    LOGGING['handlers']['database'] = {
        'filename': LOG_DIR / 'database.log',
        'class': 'logging.FileHandler',
        'level': 'DEBUG',
        'formatter': 'standard',
    }
    LOGGING['loggers']['django.db.backends'] = {
        'handlers': ['database'],
        'level': 'DEBUG',
        'propagate': True,
    }

if os.name == 'nt' and not HUEY_IMMEDIATE:
    # If Windows + multiple processes, change all rotating loggers to regular
    # file loggers, because the file-renaming step of the rotation would crash.
    # https://bugs.python.org/issue25121
    for handler in LOGGING['handlers'].values():
        handler['class'] = 'logging.FileHandler'
        for kwarg in ['maxBytes', 'backupCount', 'when', 'interval']:
            if kwarg in handler:
                handler.pop(kwarg)

# The name of the class to use for starting the test suite.
TEST_RUNNER = 'lib.tests.utils.CustomTestRunner'


#
# Other settings from third-party packages besides Django
#

# [markdownx setting]
# Max size for images uploaded through a markdownx widget via drag and drop
# (e.g. on the admin site's flatpage editor).
#
# Note that in Markdown, you can use HTML to make an image appear a different
# size from its original size: <img src="image.png" width="900"/>
MARKDOWNX_IMAGE_MAX_SIZE = {
    # Max resolution
    'size': (2000, 2000),
}

# [markdownx setting]
# Media path where drag-and-drop image uploads get stored.
MARKDOWNX_MEDIA_PATH = 'article_images/'

# [markdownx setting]
# Markdown extensions. 'extra' features are listed here:
# https://python-markdown.github.io/extensions/extra/
MARKDOWNX_MARKDOWN_EXTENSIONS = [
    'markdown.extensions.extra'
]

# [easy-thumbnails setting]
THUMBNAIL_DEFAULT_OPTIONS = {
    # We don't rotate images according to EXIF orientation, since that would
    # cause confusion in terms of point positions and annotation area.
    # For consistency, here we apply this policy to thumbnails too, not just
    # original images.
    'exif_orientation': False,
}


#
# Other settings from CoralNet
#

ACCOUNT_QUESTIONS_LINK = \
    'https://groups.google.com/forum/#!topic/coralnet-users/PsU3x-Ubrdc'
FORUM_LINK = 'https://groups.google.com/forum/#!forum/coralnet-users'

# CSS dark color scheme availability.
# This is enabled on an env basis for now; that is, any dev who wants it
# enables it, but it's not in production yet, because:
#
# 1. The dark color scheme isn't complete yet (at this time of writing).
#    The idea is to gradually work on the rest of it.
# 2. We'll probably want to implement browser-storage of the user choice
#    before a public release, so that users who want to use something
#    other than their browser's default dark-scheme setting don't have to
#    specify that on every single page load.
# 3. Need to fix the flash of the light theme which happens before the
#    dark theme kicks in.
DARK_COLORS_AVAILABLE = env.bool('DARK_COLORS_AVAILABLE', default=False)

# Media filepath patterns
IMAGE_FILE_PATTERN = 'images/{name}{extension}'
LABEL_THUMBNAIL_FILE_PATTERN = 'labels/{name}{extension}'
POINT_PATCH_FILE_PATTERN = \
    '{full_image_path}.pointpk{point_pk}.thumbnail.jpg'
PROFILE_AVATAR_FILE_PATTERN = 'avatars/{name}{extension}'

MAINTENANCE_DETAILS_FILE_PATH = TMP_DIR / 'maintenance.json'

# Special users
IMPORTED_USERNAME = 'Imported'
ROBOT_USERNAME = 'robot'
ALLEVIATE_USERNAME = 'Alleviate'

BROWSE_DEFAULT_THUMBNAILS_PER_PAGE = 20
LABEL_EXAMPLE_PATCHES_PER_PAGE = 50
LABEL_EXAMPLE_PATCHES_PER_PAGE_GUEST = 5

# If a source has more than this many unique values for a given
# aux. metadata model field, the corresponding search form field
# becomes a free text field rather than a dropdown options field.
BROWSE_METADATA_DROPDOWN_LIMIT = 100
# And if the dropdown limit's exceeded, then we provide help
# text with a list of possible options up to this amount.
BROWSE_METADATA_HELP_TEXT_OPTION_LIMIT = 500

# Max results to count in Browse Patches, because arbitrarily
# high counts are a potential source of slow page loads.
BROWSE_PATCHES_RESULT_LIMIT = 20000

# Image counts required for sources to: display on the map,
# display as medium size, and display as large size.
MAP_IMAGE_COUNT_TIERS = env.list(
    'MAP_IMAGE_COUNT_TIERS', cast=int, default=[100, 500, 1500])

GOOGLE_ANALYTICS_CODE = env('GOOGLE_ANALYTICS_CODE', default='')

# Whether to disable tqdm output and processing or not. tqdm might be used
# during management commands, data migrations, etc.
# How to use: `for obj in tqdm(objs, disable=TQDM_DISABLE):`
TQDM_DISABLE = _TESTING

# Browsers to run Selenium tests in.
#
# For now, only ONE browser is picked: the first one listed in this setting.
# Running in multiple browsers will hopefully be implemented in the future
# (with test parametrization or something).
SELENIUM_BROWSERS = env.json('SELENIUM_BROWSERS', default='[]')

# Timeouts for Selenium tests, in seconds.
SELENIUM_TIMEOUTS = {
    'short': 0.5,
    'medium': 5,
    # Hard wait time after a DB-changing operation to ensure consistency.
    # Without this wait time, we may get odd effects such as the DB not getting
    # rolled back before starting the next test.
    'db_consistency': 0.5,
    # Timeout when waiting for a page to load. If the page loads beforehand,
    # the timeout's cut short. If the page doesn't load within this time, we
    # get an error.
    # Bump this way up if you're using a debugger.
    'page_load': env.int('SELENIUM_TIMEOUT_PAGE_LOAD', default=20),
}

# We filter on sources that contains these strings for map and some exports.
LIKELY_TEST_SOURCE_NAMES = ['test', 'sandbox', 'dummy', 'tmp', 'temp', 'check']

# NewsItem categories used in NewsItem app.
NEWS_ITEM_CATEGORIES = ['ml', 'source', 'image', 'annotation', 'account']

# Size of label patches (after scaling)
LABELPATCH_NCOLS = 150
LABELPATCH_NROWS = 150
# Patch covers this proportion of the original image's greater dimension
LABELPATCH_SIZE_FRACTION = 0.2

# Front page carousel images.
# Count = number of images in the carousel each time you load the front page.
# Pool = list of image IDs to randomly choose from, e.g. [26, 79, 104].
# The pool size must be at least as large as count.
#
# Two reasons why we hardcode a pool here, instead of randomly picking
# public images from the whole site:
# 1. It's easier to guarantee in-advance thumbnail generation for a small
# pool of images. We don't want new visitors coming to the front page and
# waiting for those thumbnails to generate.
# 2. Ensuring a good variety and at least decent quality among carousel
# images.
#
# If you don't have any images to use in the carousel (e.g. you're just
# setting up a new dev environment, or you're in some test environment), set
# count to 0 and set pool to [].
if SETTINGS_BASE == Bases.PRODUCTION:
    CAROUSEL_IMAGE_COUNT = env.int('CAROUSEL_IMAGE_COUNT', default=5)
    CAROUSEL_IMAGE_POOL = env.list(
        'CAROUSEL_IMAGE_POOL', cast=int)
else:
    CAROUSEL_IMAGE_COUNT = env.int('CAROUSEL_IMAGE_COUNT', default=0)
    CAROUSEL_IMAGE_POOL = env.list(
        'CAROUSEL_IMAGE_POOL', cast=int, default=[])

if SETTINGS_BASE == Bases.PRODUCTION:
    # Provide the exact date of CoralNet 1.15's release here, i.e. a date
    # during the server downtime between 1.14 and 1.15. This is part of the
    # annotation history migration process.
    CORALNET_1_15_DATE = datetime.datetime.fromisoformat(
        env('CORALNET_1_15_DATE'))
else:
    # For non-production, a default date is provided. To ensure accurate
    # annotation histories in your env, provide the actual date that you
    # updated to CoralNet 1.15.
    CORALNET_1_15_DATE = datetime.datetime.fromisoformat(
        env('CORALNET_1_15_DATE', default='2024-10-20T08:00:00+00:00'))
