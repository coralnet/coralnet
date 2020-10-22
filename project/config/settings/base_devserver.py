# Base settings for a development server.
# This isn't a standalone settings file. You also need to import
# one of the 'storage' settings files to have a complete set of settings.

from .base import *

DEBUG = True

# Instead of routing emails through a mail server,
# just print emails to the console.
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# [Custom setting]
# The site domain, for the Django sites framework. This is used in places
# such as links in password reset emails, and 'view on site' links in the
# admin site's blog post edit view.
# If this is different for your dev server setup (like localhost instead of
# 127.0.0.1), then redefine SITE_DOMAIN in your dev_<name>.py settings file.
SITE_DOMAIN = '127.0.0.1:8000'

# Hosts/domain names that are valid for this site.
# "*" matches anything, ".example.com" matches example.com and all subdomains
#
# When DEBUG is True and ALLOWED_HOSTS is empty,
# the host is validated against ['localhost', '127.0.0.1', '[::1]'].
# https://docs.djangoproject.com/en/dev/ref/settings/#allowed-hosts
ALLOWED_HOSTS = []

# No HTTPS.
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_PROXY_SSL_HEADER = None

# [Custom setting]
# Which backend queue to use.
SPACER_QUEUE_CHOICE = 'vision_backend.queues.LocalQueue'

# Configure the SQS queue name to use
SQS_JOBS = 'spacer_test_jobs'  # Deprecated.
SQS_RES = 'spacer_test_results'
BATCH_QUEUE = 'shakeout'

# [Custom setting]
# Front page carousel images.
# Count = number of images in the carousel each time you load the front page.
# Pool = list of image IDs to randomly choose from, e.g. [26, 79, 104].
# The pool size must be at least as large as count.
#
# Two reasons why we hardcode a pool here, instead of randomly picking
# public images from the whole site:
# 1. It's easier to guarantee in-advance thumbnail generation for a small
# pool of images. We don't want new visitors coming to the front page and waiting for those thumbnails to generate.
# 2. Ensuring a good variety and at least decent quality among carousel
# images.
#
# If you don't have any images to use in the carousel (e.g. you're just
# setting up a new dev environment, or you're in some test environment), set
# count to 0 and set pool to [].
CAROUSEL_IMAGE_COUNT = 0
CAROUSEL_IMAGE_POOL = []


# Change to using only 1 worker here for more predictable results.
CELERYD_CONCURRENCY = 1
