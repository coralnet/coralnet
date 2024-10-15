from django.urls import path

from . import views


app_name = 'jobs'

urlpatterns = [
    path(r'jobs/summary/',
         views.JobSummaryView.as_view(), name='summary'),
    path(r'jobs/list/',
         views.AllJobsListView.as_view(), name='all_jobs_list'),
    path(r'jobs/non_source_list/',
         views.NonSourceJobListView.as_view(), name='non_source_job_list'),
    path(r'jobs/status/',
         views.background_job_status, name='status'),
    path(r'source/<int:source_id>/jobs/',
         views.SourceJobListView.as_view(), name='source_job_list'),
]
