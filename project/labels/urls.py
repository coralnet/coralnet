from django.conf.urls import url
from . import views

urlpatterns = [
    url(r'^labels/$', views.label_list, name="label_list"),
    url(r'^labels/(?P<label_id>\d+)/$', views.label_main, name="label_main"),
    url(r'^labels/(?P<label_id>\d+)/example_patches_ajax/$',
        views.label_example_patches_ajax, name="label_example_patches_ajax"),
    url(r'^labels/new_ajax/$', views.label_new_ajax, name="label_new_ajax"),
    url(r'^labels/search/$', views.label_search_ajax,
        name="label_search_ajax"),
    url(r'^labelsets/search/$', views.labelset_search_ajax,
        name="labelset_search_ajax"),
    url(r'^labelset/(?P<labelset_id>\d+)/labels/$', views.labelset_labels_ajax,
        name="labelset_labels_ajax"),

    url(r'^source/(?P<source_id>\d+)/labelset/$', views.labelset_main,
        name="labelset_main"),
    url(r'^source/(?P<source_id>\d+)/labelset/add/$', views.labelset_add,
        name="labelset_add"),
    url(r'^source/(?P<source_id>\d+)/labelset/edit/$', views.labelset_edit,
        name="labelset_edit"),

    url(r'^source/(?P<source_id>\d+)/labelset/import/$', views.labelset_import,
        name="labelset_import"),
    url(r'^source/(?P<source_id>\d+)/labelset/import_preview_ajax/$',
        views.labelset_import_preview_ajax,
        name="labelset_import_preview_ajax"),
    url(r'^source/(?P<source_id>\d+)/labelset/import_ajax/$',
        views.labelset_import_ajax,
        name="labelset_import_ajax"),
]
