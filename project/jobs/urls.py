from django.urls import path

from . import views


app_name = 'jobs'

urlpatterns = [
    path(r'jobs/overall_dashboard/',
         views.overall_dashboard, name='overall_dashboard'),
    path(r'source/<int:source_id>/jobs/',
         views.source_dashboard, name='source_dashboard'),
]
