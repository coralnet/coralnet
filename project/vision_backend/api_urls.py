from __future__ import unicode_literals

from django.conf.urls import url

from . import api_views


urlpatterns = [
    url(r'^sources/(?P<source_id>\d+)/deploy/$',
        api_views.Deploy.as_view(), name='deploy'),
]
