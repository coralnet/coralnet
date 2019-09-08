from django.conf.urls import url
from . import views

urlpatterns = [
    url(r'^$', views.backend_main, name="backend_main"),
]
