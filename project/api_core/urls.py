from __future__ import unicode_literals

from django.conf.urls import include, url

from . import views


urlpatterns = [
    url(r'^token-auth/$',
        views.ObtainAuthToken.as_view(), name='token_auth'),
    url(r'', include('vision_backend_api.urls')),
]
