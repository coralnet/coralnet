from django.urls import include, path

from . import views


app_name = 'api_core'

urlpatterns = [
    path('token_auth/',
         views.ObtainAuthToken.as_view(), name='token_auth'),
    path('user/<username>/',
         views.UserShow.as_view(), name='user_show'),
    path('', include('vision_backend_api.urls')),
]
