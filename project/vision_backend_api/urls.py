from __future__ import unicode_literals

from django.conf.urls import url

from . import views


urlpatterns = [
    url(r'^sources/(?P<source_id>\d+)/deploy/$',
        views.Deploy.as_view(), name='deploy'),
]
