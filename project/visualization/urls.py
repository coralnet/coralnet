from django.urls import include, path
from . import views
from .tests.js import views as js_test_views


general_urlpatterns = [
    path('js_test_browse_images_actions/',
         js_test_views.BrowseImagesActionsQUnitView.as_view(),
         name="js_test_browse_images_actions"),
]

source_urlpatterns = [
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

urlpatterns = [
    path('', include(general_urlpatterns)),
    path('source/<int:source_id>/browse/', include(source_urlpatterns)),
]
