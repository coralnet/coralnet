from __future__ import unicode_literals

from .utils import BurstRateThrottle, SustainedRateThrottle
from rest_framework.authtoken.views import (
    ObtainAuthToken as DefaultObtainAuthToken)


class ObtainAuthToken(DefaultObtainAuthToken):
    """
    Subclass of rest-framework's token view to add throttling, since the view
    doesn't have throttling by default, as said here:
    https://www.django-rest-framework.org/api-guide/authentication/#by-exposing-an-api-endpoint
    """
    throttle_classes = [BurstRateThrottle, SustainedRateThrottle]
