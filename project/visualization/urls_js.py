from django.urls import path

from .tests.js import views as views


urlpatterns = [
    path('js_test_browse_images_actions/',
         views.BrowseImagesActionsQUnitView.as_view(),
         name="js_test_browse_images_actions"),
    path('js_test_browse_search_form/',
         views.BrowseSearchFormQUnitView.as_view(),
         name="js_test_browse_search_form"),
]
