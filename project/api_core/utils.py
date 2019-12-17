from __future__ import unicode_literals

from rest_framework.settings import api_settings
from rest_framework.throttling import (
    ScopedRateThrottle as DefaultScopedRateThrottle)


class ScopedRateThrottle(DefaultScopedRateThrottle):
    """
    Subclass of the original ScopedRateThrottle which applies settings
    at init time, rather than class definition time. This allows settings
    overrides to work during tests.
    """
    def __init__(self):
        self.THROTTLE_RATES = api_settings.DEFAULT_THROTTLE_RATES
        super(ScopedRateThrottle, self).__init__()
