from django.conf.urls import include, url
from . import views

label_general_urlpatterns = [
    url(r'^list/$', views.label_list, name="label_list"),
    url(r'^list_search_ajax/$', views.label_list_search_ajax,
        name="label_list_search_ajax"),
    url(r'^new/$', views.label_new, name="label_new"),
    url(r'^new_ajax/$', views.label_new_ajax, name="label_new_ajax"),
    url(r'^add_search_ajax/$', views.labelset_add_search_ajax,
        name="labelset_add_search_ajax"),
    url(r'^duplicates/$', views.duplicates_overview,
        name="labelset_duplicates"),
]

label_specific_urlpatterns = [
    url(r'^$', views.label_main, name="label_main"),
    url(r'^example_patches_ajax/$',
        views.label_example_patches_ajax, name="label_example_patches_ajax"),
    url(r'^edit/$', views.label_edit, name="label_edit"),
]

labelset_urlpatterns = [
    url(r'^$', views.labelset_main,
        name="labelset_main"),
    url(r'^add/$', views.labelset_add,
        name="labelset_add"),
    url(r'^edit/$', views.labelset_edit,
        name="labelset_edit"),
    url(r'^import/$', views.labelset_import,
        name="labelset_import"),
    url(r'^import_preview_ajax/$',
        views.labelset_import_preview_ajax,
        name="labelset_import_preview_ajax"),
    url(r'^import_ajax/$',
        views.labelset_import_ajax,
        name="labelset_import_ajax"),
]

urlpatterns = [
    url(r'^label/', include(label_general_urlpatterns)),
    url(r'^label/(?P<label_id>\d+)/', include(label_specific_urlpatterns)),
    url(r'^source/(?P<source_id>\d+)/labelset/', include(labelset_urlpatterns)),
]
