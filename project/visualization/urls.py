from django.urls import path

from . import views


urlpatterns = [
    path('images/',
         views.browse_images, name="browse_images"),
    path('metadata/',
         views.edit_metadata, name="edit_metadata"),
    path('patches/',
         views.browse_patches, name="browse_patches"),

    path('delete_ajax/',
         views.browse_delete_ajax, name="browse_delete_ajax"),
    path('edit_metadata_ajax/',
         views.edit_metadata_ajax, name="edit_metadata_ajax"),

    path('statistics/',
         views.generate_statistics, name="statistics"),
]
