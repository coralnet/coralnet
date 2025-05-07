from django.urls import path

from .tests.js import views as views


urlpatterns = [
    path('js_test_upload_images/',
         views.UploadImagesQUnitView.as_view(),
         name="js_test_upload_images"),
]
