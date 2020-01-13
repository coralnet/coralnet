from __future__ import unicode_literals

from rest_framework.settings import api_settings
from rest_framework.throttling import (
    UserRateThrottle as DefaultUserRateThrottle)


class UserRateThrottle(DefaultUserRateThrottle):
    """
    Subclass of the original UserRateThrottle which applies settings
    at init time, rather than class definition time. This allows settings
    overrides to work during tests.
    """
    def __init__(self):
        self.THROTTLE_RATES = api_settings.DEFAULT_THROTTLE_RATES
        super(UserRateThrottle, self).__init__()


# The following classes allow us to define multiple throttle rates.


class BurstRateThrottle(UserRateThrottle):
    scope = 'burst'


class SustainedRateThrottle(UserRateThrottle):
    scope = 'sustained'
