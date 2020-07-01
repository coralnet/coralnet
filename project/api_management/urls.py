from __future__ import unicode_literals

from django.conf.urls import url

from . import views


urlpatterns = [
    url(r'^jobs/$',
        views.job_list, name='job_list'),
    url(r'^jobs/(?P<job_id>\d+)/$',
        views.job_detail, name='job_detail'),
]
