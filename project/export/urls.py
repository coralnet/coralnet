from django.urls import path
from . import views

urlpatterns = [
    path('metadata/',
         views.export_metadata, name="export_metadata"),
    path('image_covers_prep/',
         views.ImageCoversExportPrepView.as_view(), name="export_image_covers_prep"),
    path('labelset/',
         views.export_labelset, name="export_labelset"),
    path('serve/',
         views.SourceExportServeView.as_view(), name="source_export_serve")
]
