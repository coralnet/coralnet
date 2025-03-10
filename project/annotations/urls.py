from django.urls import include, path
from . import views

general_urlpatterns = [
    path('tool_settings_save_ajax/',
         views.annotation_tool_settings_save,
         name="annotation_tool_settings_save"),
]

image_urlpatterns = [
    path('tool/',
         views.annotation_tool, name="annotation_tool"),
    path('save_ajax/',
         views.save_annotations_ajax, name="save_annotations_ajax"),
    path('all_done_ajax/',
         views.is_annotation_all_done_ajax, name="is_annotation_all_done_ajax"),
    path('area_edit/',
         views.annotation_area_edit, name="annotation_area_edit"),
    path('history/',
         views.annotation_history, name="annotation_history"),
]

source_urlpatterns = [
    path('upload/',
         views.upload_page, name="annotations_upload_page"),
    path('upload_preview/',
         views.upload_preview,
         name="annotations_upload_preview"),
    path('upload_confirm/',
         views.AnnotationsUploadConfirmView.as_view(),
         name="annotations_upload_confirm"),

    path('export_prep/',
         views.ExportPrepView.as_view(), name="annotations_export_prep"),

    path('batch_delete_ajax/',
         views.batch_delete_annotations_ajax,
         name="batch_delete_annotations_ajax"),
]

urlpatterns = [
    path('annotation/', include(general_urlpatterns)),
    path('image/<int:image_id>/annotation/', include(image_urlpatterns)),
    path('source/<int:source_id>/annotation/', include(source_urlpatterns)),
]
