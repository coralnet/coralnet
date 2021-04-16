from django.conf.urls import url

from . import views


urlpatterns = [
    url(r'^$',
        views.PostsList.as_view(
            template_name='blog/post_list.html'),
        name='post_list'),
    url(r'^(?P<slug>[A-Za-z0-9-_]+)/$',
        views.PostDetail.as_view(
            template_name='blog/post_detail.html'),
        name='post_detail'),
]
