from django.urls import path
from . import views
from .tests.js import views as js_test_views


app_name = 'async_media'

urlpatterns = [
    path('start_media_generation_ajax/', views.start_media_generation_ajax,
         name="start_media_generation_ajax"),
    path('media_poll_ajax/', views.media_poll_ajax,
         name="media_poll_ajax"),

    path('js_test_async_media/',
         js_test_views.AsyncMediaQUnitView.as_view(),
         name="js_test_async_media"),
]
