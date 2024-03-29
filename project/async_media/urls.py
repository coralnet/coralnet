from django.urls import path
from . import views


app_name = 'async_media'

urlpatterns = [
    path('start_media_generation_ajax/', views.start_media_generation_ajax,
         name="start_media_generation_ajax"),
    path('media_poll_ajax/', views.media_poll_ajax,
         name="media_poll_ajax"),
]
