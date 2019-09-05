from django.conf.urls import url
from . import views

urlpatterns = [
    url(r'^$', views.newsfeed_global, name="newsfeed_global"),
]
