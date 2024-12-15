from django.urls import path
from . import views

urlpatterns = [
    path('metadata/',
         views.export_metadata, name="export_metadata"),
    path('image_covers/',
         views.ImageCoversExportView.as_view(), name="export_image_covers"),
    path('labelset/',
         views.export_labelset, name="export_labelset"),
]
