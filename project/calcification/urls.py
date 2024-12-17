from django.urls import include, path

from . import views


app_name = 'calcification'

general_urlpatterns = [
    path('table_download/<int:table_id>/',
         views.rate_table_download,
         name='rate_table_download'),
    path('table_delete/<int:table_id>/',
         views.rate_table_delete_ajax,
         name='rate_table_delete_ajax'),
]

source_urlpatterns = [
    path('stats_export_prep/',
         views.CalcifyStatsExportPrepView.as_view(),
         name='stats_export_prep'),
    path('table_upload/',
         views.rate_table_upload_ajax,
         name='rate_table_upload_ajax'),
]

urlpatterns = [
    path('calcification/', include(general_urlpatterns)),
    path('source/<int:source_id>/calcification/', include(source_urlpatterns)),
]
