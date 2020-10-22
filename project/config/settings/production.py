# Settings for the public site.

from .base import *
from .storage_s3 import *


DEBUG = False

# [Custom setting]
# The site domain, for the Django sites framework. This is used in places
# such as links in password reset emails, and 'view on site' links in the
# admin site's blog post edit view.
SITE_DOMAIN = 'coralnet.ucsd.edu'

# Hosts/domain names that are valid for this site.
# "*" matches anything, ".example.com" matches example.com and all subdomains
#
# Although it doesn't seem to apply to us currently, here's some info about
# configuring this setting if unit tests have some special domain name logic:
# https://docs.djangoproject.com/en/dev/topics/testing/advanced/#topics-testing-advanced-multiple-hosts
ALLOWED_HOSTS = [SITE_DOMAIN]

# Use HTTPS.
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
# This setting is needed since our nginx config connects to Django with a
# non-HTTPS proxy_pass.
# https://docs.djangoproject.com/en/dev/ref/settings/#secure-proxy-ssl-header
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

WSGI_APPLICATION = 'config.wsgi.application'

# [Custom setting]
# Which vision backend to use.
SPACER_QUEUE_CHOICE = 'vision_backend.queues.SQSQueue'

# Configure the SQS queue name to use
SQS_JOBS = 'coralnet_prod_jobs'  # Deprecated
SQS_RES = 'coralnet_prod_results'
BATCH_QUEUE = 'production'

# [Custom setting]
# Front page carousel images.
CAROUSEL_IMAGE_COUNT = 5
CAROUSEL_IMAGE_POOL = [
    115688,  # AIMS LTMP
    25563,  # Catlin Seaview Survey
    469367,  # Colby Bermuda
    7069,  # CVCE Bocas del Toro
    848173,  # Israel
    686881,  # Okinawa
    168582,  # MarineGEO Belize
    675333,  # NOAA ESD CAU
    68923,  # USS Guardian wreck
    686128,  # Vavau
]
