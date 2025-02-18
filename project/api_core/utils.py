from django.conf import settings
from rest_framework.settings import api_settings
from rest_framework.throttling import (
    UserRateThrottle as DefaultUserRateThrottle)

from .models import UserApiLimits


class UserRateThrottle(DefaultUserRateThrottle):
    """
    Subclass of the original UserRateThrottle which applies settings
    at init time, rather than class definition time. This allows settings
    overrides to work during tests.
    """
    def __init__(self):
        self.THROTTLE_RATES = api_settings.DEFAULT_THROTTLE_RATES
        super().__init__()


# The following classes allow us to define multiple throttle rates.


class BurstRateThrottle(UserRateThrottle):
    scope = 'burst'


class SustainedRateThrottle(UserRateThrottle):
    scope = 'sustained'


def get_max_active_jobs(user):
    try:
        # See if there's a user-specific limit.
        return UserApiLimits.objects.get(user=user).max_active_jobs
    except UserApiLimits.DoesNotExist:
        # Else, use the default.
        return settings.USER_DEFAULT_MAX_ACTIVE_API_JOBS
