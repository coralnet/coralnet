from django.conf.urls import url
from . import views


urlpatterns = [
    url(r'^(?P<news_item_id>\d+)/$', views.one_event, name="newsfeed_details"),
    url(r'^$', views.global_feed, name="newsfeed_global"),
]

