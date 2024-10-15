from django.urls import include, path
from . import views


general_urlpatterns = [
    path('backend_overview/', views.backend_overview, name='backend_overview'),
    path('cm_test/', views.cm_test, name='cm_test'),
]

source_urlpatterns = [
    path('', views.backend_main, name="backend_main"),
    path('check', views.request_source_check, name="request_source_check"),
]

urlpatterns = [
    path('', include(general_urlpatterns)),
    path('source/<int:source_id>/backend/', include(source_urlpatterns)),
]
