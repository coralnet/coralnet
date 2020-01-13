from __future__ import unicode_literals

from django.conf.urls import url

from . import views


urlpatterns = [
    url(r'^classifiers/(?P<classifier_id>\d+)/deploy/$',
        views.Deploy.as_view(), name='deploy'),
    url(r'^deploy_statuses/(?P<job_id>\d+)/$',
        views.DeployStatus.as_view(), name='deploy_status'),
    url(r'^deploy_results/(?P<job_id>\d+)/$',
        views.DeployResult.as_view(), name='deploy_result'),
]
