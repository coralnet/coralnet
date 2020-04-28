from __future__ import unicode_literals
import sys

from .base_devserver import *

# Pick one.
from .storage_local import *
# from .storage_s3 import *
# from .storage_s3_regtests import *

MAP_IMAGE_COUNT_TIERS = [5, 20, 50]

MIN_NBR_ANNOTATED_IMAGES = 5

# For now, only the first specified browser gets used for Selenium tests.
SELENIUM_BROWSERS = [
    # Headless Chrome
    {
        'name': 'Chrome',
        'webdriver': r'C:\Programs_non_installed\Webdrivers\chromedriver.exe',
        'options': ['--headless'],
    },
    # Headless Firefox
    {
        'name': 'Firefox',
        'webdriver': r'C:\Programs_non_installed\Webdrivers\geckodriver.exe',
        'browser_binary': r'C:\Programs_non_installed\FirefoxPortable\S\App\firefox64\firefox.exe',
        'options': ['-headless'],
    },
    # Regular Chrome
    {
        'name': 'Chrome',
        'webdriver': r'C:\Programs_non_installed\Webdrivers\chromedriver.exe',
    },
    # Regular Firefox
    {
        'name': 'Firefox',
        'webdriver': r'C:\Programs_non_installed\Webdrivers\geckodriver.exe',
        'browser_binary': r'C:\Programs_non_installed\FirefoxPortable\S\App\firefox64\firefox.exe',
    },
]

# I'll uncomment this for running our Selenium tests, since those tests
# require an in-memory database like SQLite.
# TODO: SQLite won't work as long as JSONField is PostgreSQL-only.
#if 'test' in sys.argv:
#    DATABASES['default']['ENGINE'] = 'django.db.backends.sqlite3'

# If I ever test with DEBUG = False, I'll want to:
# - Set an ALLOWED_HOSTS, otherwise runserver gets a CommandError
# - Set a STATIC_URL which I can serve static files to,
#   say using `python -m http.server 8080` (this syntax is Python 3),
#   and remember to use the collectstatic command
# - Set a MEDIA_URL which I can serve media files to,
#   say using `python -m http.server 8070`
#
# But I'll leave these all commented out if DEBUG = True, because it's easier
# to not bother with starting up those extra servers, and ALLOWED_HOSTS gets
# intelligently filled in if DEBUG = True:
# https://docs.djangoproject.com/en/dev/ref/settings/#allowed-hosts
#DEBUG = False
#ALLOWED_HOSTS = ['*']
#MEDIA_URL = 'http://127.0.0.1:8070/'
#STATIC_URL = 'http://127.0.0.1:8080/'

CAROUSEL_IMAGE_COUNT = 2
CAROUSEL_IMAGE_POOL = [
    516, 515, 514
]
