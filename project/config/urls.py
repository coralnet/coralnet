from django.conf import settings
from django.conf.urls import include, url
from django.conf.urls.static import static
from django.contrib import admin
from django.views.generic import TemplateView
from rest_framework.authtoken import views as authtoken_views

import lib.views as lib_views
import vision_backend.views as backend_views

urlpatterns = [
    # These apps don't have uniform prefixes. We'll trust them to provide
    # their own non-clashing URL patterns.
    url(r'', include('annotations.urls')),
    url(r'', include('images.urls')),
    url(r'', include('labels.urls')),

    url(r'^accounts/', include('accounts.urls')),
    url(r'^newsfeed/', include('newsfeed.urls')),
    url(r'^async_media/',
        include('async_media.urls', namespace='async_media')),
    url(r'^blog/', include('blog.urls', namespace='blog')),
    url(r'^source/(?P<source_id>\d+)/browse/', include('visualization.urls')),
    url(r'^source/(?P<source_id>\d+)/export/', include('export.urls')),
    url(r'^source/(?P<source_id>\d+)/upload/', include('upload.urls')),
    url(r'^source/(?P<source_id>\d+)/backend/', include('vision_backend.urls')),

    url(r'^admin/doc/', include('django.contrib.admindocs.urls')),
    url(r'^admin/', include(admin.site.urls)),

    url(r'^$', lib_views.index, name='index'),
    url(r'^about/$',
        TemplateView.as_view(template_name='lib/about.html'),
        name='about',
    ),
    url(r'^release/$',
        TemplateView.as_view(template_name='lib/release_notes.html'),
        name='release',
    ),

    # Flatpages, such as the help page
    url(r'^pages/', include('flatpages_custom.urls', namespace='pages')),

    # markdownx editor AJAX functionality (content preview and image upload).
    url(r'^markdownx/', include('markdownx.urls')),

    # API
    url(r'^api/', include('vision_backend.api_urls', namespace='api')),
    # Token authentication for the API
    url(r'^api/token-auth/',
        authtoken_views.obtain_auth_token, name='api_token_auth'),

    # "Secret" dev views
    url(r'^nav_test/(?P<source_id>\d+)/$', lib_views.nav_test, name="nav_test"),
    url(r'^backend_overview$', backend_views.backend_overview, name="backend_overview"),
    url(r'^cm_test$', backend_views.cm_test, name="cm_test"),
    
    # Internationalization
    url(r'^i18n/', include('django.conf.urls.i18n')),
]

# Serving media files in development.
# https://docs.djangoproject.com/en/dev/ref/views/#serving-files-in-development
#
# When in production, this doesn't do anything; you're expected to serve
# media via your web server software.
# https://docs.djangoproject.com/en/dev/howto/deployment/wsgi/modwsgi/#serving-files
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Custom server-error handlers. Must be assigned in the root URLconf.
handler500 = lib_views.handler500