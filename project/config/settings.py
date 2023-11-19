from collections.abc import MutableMapping
from email.utils import parseaddr
from enum import Enum
import os
from pathlib import Path
import sys

# In many cases it's dangerous to import from Django directly into a settings
# module, but ImproperlyConfigured is fine.
from django.core.exceptions import ImproperlyConfigured

import environ

# Configure Pillow to be tolerant of image files that are truncated (missing
# data from the last block).
# https://stackoverflow.com/a/23575424/
from PIL import ImageFile
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


#
# More directories
#

# Base directory of the Django project.
PROJECT_DIR = REPO_DIR / 'project'

# Directory for any site related files, not just the repository.
SITE_DIR = env.path('SITE_DIR', default=REPO_DIR.parent)

# Directory containing log files.
LOG_DIR = SITE_DIR / 'log'


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
    and 'test' not in sys.argv
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

if SETTINGS_BASE == Bases.STAGING:
    # Instead of routing emails through a mail server,
    # just write emails to the filesystem.
    EMAIL_BACKEND = 'django.core.mail.backends.filebased.EmailBackend'
    EMAIL_FILE_PATH = SITE_DIR / 'tmp' / 'emails'
elif SETTINGS_BASE in [Bases.DEV_LOCAL, Bases.DEV_S3]:
    # Instead of routing emails through a mail server,
    # just print emails to the console.
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
# Else (production), use the default email backend (smtp).


#
# Database related
#

# Database connection info.
DATABASES = {
    'default': {
        # 'postgresql', 'mysql', 'sqlite3' or 'oracle'.
        # sqlite3 may speed up test runs, but proceed with caution since
        # behavior may differ from postgresql.
        'ENGINE': env(
            'DATABASE_ENGINE', default='django.db.backends.postgresql'),
        # If True, wraps each request (view function) in a transaction by
        # default. Individual view functions can override this behavior with
        # the non_atomic_requests decorator.
        'ATOMIC_REQUESTS': True,
        # Database name, or path to database file if using sqlite3.
        'NAME': env('DATABASE_NAME'),
        # Not used with sqlite3.
        'USER': env('DATABASE_USER'),
        # Not used with sqlite3.
        'PASSWORD': env('DATABASE_PASSWORD'),
        # Set to empty string for localhost. Not used with sqlite3.
        'HOST': env('DATABASE_HOST', default=''),
        # Set to empty string for default (e.g. 5432 for postgresql).
        # Not used with sqlite3.
        'PORT': env('DATABASE_PORT', default=''),
    }
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
DATA_UPLOAD_MAX_NUMBER_FIELDS = 1000000

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
VALSET_SELECTION_METHOD = 'id'

# This indicates the max number of scores we store per point.
NBR_SCORES_PER_ANNOTATION = 5

# This is the number of epochs we request the SGD solver to take over the data.
NBR_TRAINING_EPOCHS = 10

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

    'MIN_TRAINIMAGES': TRAINING_MIN_IMAGES,
}

# If True, feature extraction just returns dummy results to speed up testing.
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

# If AWS Batch is being used, use this job queue and job definition name.
if SETTINGS_BASE == Bases.PRODUCTION:
    BATCH_QUEUE = 'production'
    BATCH_JOB_DEFINITION = 'spacer-job'
else:
    BATCH_QUEUE = 'shakeout'
    BATCH_JOB_DEFINITION = 'spacer-job-staging'

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
    DEFAULT_FILE_STORAGE = 'lib.storage_backends.MediaStorageLocal'

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

    # Default file storage mechanism that holds media.
    DEFAULT_FILE_STORAGE = 'lib.storage_backends.MediaStorageS3'

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

# [easy_thumbnails setting]
# Default file storage for saving generated thumbnails.
#
# The only downside of not using the app's provided storage class is that
# the THUMBNAIL_MEDIA_ROOT and THUMBNAIL_MEDIA_URL settings won't work
# (we'd have to apply them manually). We aren't using these settings, though.
THUMBNAIL_DEFAULT_STORAGE = DEFAULT_FILE_STORAGE


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
# ManifestStaticFilesStorage appends a content-based hash to the filename
# to facilitate browser caching.
# This hash appending happens as a post-processing step in collectstatic, so
# it only applies to DEBUG False.
# https://docs.djangoproject.com/en/dev/ref/contrib/staticfiles/#manifeststaticfilesstorage
STATICFILES_STORAGE = \
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
        'burst': '50/min',
        'sustained': '500/hour',
    },
    'EXCEPTION_HANDLER': 'api_core.exceptions.exception_handler',
}

# [huey setting]
# https://huey.readthedocs.io/en/latest/django.html#setting-things-up
HUEY = {
    # Don't store return values of tasks.
    'results': False,
    # Whether to run tasks immediately or to schedule them as normal.
    'immediate': env.bool('HUEY_IMMEDIATE', default=DEBUG),
    # Whether to run huey-registered periodic tasks or not.
    'consumer': {
        'periodic': env.bool('HUEY_CONSUMER_PERIODIC', default=True),
    }
}

# [CoralNet settings]
# Whether to periodically run CoralNet-managed (not huey-registered)
# periodic jobs. Can be useful to disable for certain tests.
ENABLE_PERIODIC_JOBS = True
# Additional API-throttling policy for async jobs.
MAX_CONCURRENT_API_JOBS_PER_USER = 5
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
    'upload',
    'visualization',
    'vision_backend',
    'vision_backend_api',

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

    'easy_thumbnails',
    'guardian',
    'huey.contrib.djhuey',
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
    'django.contrib.messages.middleware.MessageMiddleware',

    # django-reversion
    'reversion.middleware.RevisionMiddleware',
]

CACHES = {
    'default': {
        # The default local-memory cache backend is saved per-process, which
        # doesn't cut it if we have more than one server process, e.g.
        # multiple gunicorn worker processes.
        #
        # For example, async media loading uses the cache as a kind of
        # persistent storage between requests. In general, the subsequent
        # requests may be handled by different worker processes, so per-process
        # caches won't work; the cache must be shared between processes.
        'BACKEND': 'django.core.cache.backends.filebased.FileBasedCache',
        'LOCATION': SITE_DIR / 'tmp' / 'django_cache',
        'OPTIONS': {
            # This should at least support:
            # - Label popularities: assume we're always caching 1 entry per
            #   label, for the label list
            # - Async thumbnail requests: however many might be generated in
            #   the expiration duration
            'MAX_ENTRIES': 10000,
        }
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
                # Adds CoralNet help links to the context.
                'lib.context_processors.help_links',
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

# https://docs.djangoproject.com/en/dev/topics/logging/#configuring-logging
LOGGING = {
    'version': 1,
    # Existing (default) logging includes error emails to admins,
    # so we want to keep it.
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '[%(name)s.%(funcName)s, %(asctime)s]: %(message)s'
        },
    },
    'handlers': {
        'backend': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': LOG_DIR / 'vision_backend.log',
            'formatter': 'standard'
        },
        'backend_debug': {
            'level': 'DEBUG',
            'class': 'logging.FileHandler',
            'filename': LOG_DIR / 'vision_backend_debug.log',
            'formatter': 'standard'
        },
    },
    'loggers': {
        'vision_backend': {
            'handlers': ['backend', 'backend_debug'],
            'level': 'DEBUG',
            # Don't print this info/debug output to console; it clogs output
            # during unit tests, for example.
            'propagate': False,
        }
    },
}
# This can help with debugging DB queries.
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

# Media filepath patterns
IMAGE_FILE_PATTERN = 'images/{name}{extension}'
LABEL_THUMBNAIL_FILE_PATTERN = 'labels/{name}{extension}'
POINT_PATCH_FILE_PATTERN = \
    '{full_image_path}.pointpk{point_pk}.thumbnail.jpg'
PROFILE_AVATAR_FILE_PATTERN = 'avatars/{name}{extension}'

MAINTENANCE_STATUS_FILE_PATH = SITE_DIR / 'tmp' / 'maintenance.json'

# Special users
IMPORTED_USERNAME = 'Imported'
ROBOT_USERNAME = 'robot'
ALLEVIATE_USERNAME = 'Alleviate'

BROWSE_DEFAULT_THUMBNAILS_PER_PAGE = 20

# Image counts required for sources to: display on the map,
# display as medium size, and display as large size.
MAP_IMAGE_COUNT_TIERS = env.list(
    'MAP_IMAGE_COUNT_TIERS', cast=int, default=[100, 500, 1500])

GOOGLE_ANALYTICS_CODE = env('GOOGLE_ANALYTICS_CODE', default='')

# Whether to disable tqdm output and processing or not. tqdm might be used
# during management commands, data migrations, etc.
# How to use: `for obj in tqdm(objs, disable=TQDM_DISABLE):`
#
# Here we disable tqdm when running the test command. Note that this is better
# than setting False here and setting True in `test_settings`, because that
# method would not disable tqdm during pre-test migration runs.
TQDM_DISABLE = 'test' in sys.argv

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
    'page_load': 20,
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
