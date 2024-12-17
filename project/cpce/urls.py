from django.urls import include, path

from . import views


app_name = 'cpce'

general_urlpatterns = [
    path('cpc_batch_editor/',
         views.cpc_batch_editor, name="cpc_batch_editor"),
    path('cpc_batch_editor_process_ajax/',
         views.cpc_batch_editor_process_ajax,
         name="cpc_batch_editor_process_ajax"),
    path('cpc_batch_editor_file_serve/',
         views.CpcBatchEditorServeView.as_view(),
         name="cpc_batch_editor_file_serve"),
]

source_urlpatterns = [
    path('upload/',
         views.upload_page, name="upload_page"),
    path('upload_preview_ajax/',
         views.upload_preview_ajax,
         name="upload_preview_ajax"),
    path('upload_confirm_ajax/',
         views.CpcAnnotationsUploadConfirmView.as_view(),
         name="upload_confirm_ajax"),

    path('export_prep/',
         views.ExportPrepView.as_view(),
         name="export_prep"),
]

urlpatterns = [
    path('cpce/', include(general_urlpatterns)),
    path('source/<int:source_id>/cpce/', include(source_urlpatterns)),
]
