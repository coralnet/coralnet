# Settings to be used for Travis CI.
# Here we don't use secrets.json since these settings are just for testing

from .base_devserver import *


DATABASES['default'].update({
    # Database name, or path to database file if using sqlite3.
    'NAME': 'travis_ci_test',
    # Not used with sqlite3.
    'USER': "",
    # Not used with sqlite3.
    'PASSWORD': "",
    # Set to empty string for localhost. Not used with sqlite3.
    'HOST': "",
    # Set to empty string for default. Not used with sqlite3.
    'PORT': "",
})

# Default file storage mechanism that holds media.
DEFAULT_FILE_STORAGE = 'lib.storage_backends.MediaStorageLocal'

# easy_thumbnails 3rd party app:
# Default file storage for saving generated thumbnails.
#
# The only downside of not using the app's provided storage class is that
# the THUMBNAIL_MEDIA_ROOT and THUMBNAIL_MEDIA_URL settings won't work
# (we'd have to apply them manually). We aren't using these settings, though.
THUMBNAIL_DEFAULT_STORAGE = DEFAULT_FILE_STORAGE

# Absolute filesystem path to the directory that will hold user-uploaded files.
# Example: "/home/media/media.lawrence.com/media/"
# This setting only applies when such files are saved to a filesystem path,
# not when they are uploaded to a cloud service like AWS.
MEDIA_ROOT = SITE_DIR.child('media')

# Base URL where user-uploaded media are served.
#
# Here we assume DEBUG is True, in which case this should be a relative URL.
# Django will serve the contents of MEDIA_ROOT there.
# The code that does the serving is in the root urlconf.
MEDIA_URL = '/media/'
