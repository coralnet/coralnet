from django.urls import include, path
from . import views
from .tests.js import views as js_test_views


source_general_urlpatterns = [
    path('', views.source_list, name="source_list"),
    path('about/', views.source_about, name="source_about"),
    path('new/', views.source_new, name="source_new"),
    path('invites/', views.invites_manage, name="invites_manage"),

    path('js_test_async_media/',
         js_test_views.SourceEditQUnitView.as_view(),
         name="js_test_source_edit"),
]

source_specific_urlpatterns = [
    path('', views.source_main, name="source_main"),
    path('edit/', views.source_edit, name="source_edit"),
    path('edit/cancel/', views.source_edit_cancel, name='source_edit_cancel'),
    path('admin/', views.source_admin, name="source_admin"),
    path('detail_box/', views.source_detail_box, name="source_detail_box"),
]

urlpatterns = [
    path('source/', include(source_general_urlpatterns)),
    path('source/<int:source_id>/', include(source_specific_urlpatterns)),
]
