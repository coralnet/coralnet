from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView

import lib.views as lib_views
import lib.tests.js.views as lib_js_test_views


IMAGE_ID = 'image/<int:image_id>/'
SOURCE_ID = 'source/<int:source_id>/'

urlpatterns = [
    # Many apps are included with no prefix ('') because they have some URLs
    # which are prefixed by a source/image/label ID, and some URLs which are
    # not. We have to trust them to not have URL patterns which clash with each
    # other.
    path('accounts/', include('accounts.urls')),
    path('', include('annotations.urls')),
    path('api/', include('api_core.urls', namespace='api')),
    path('api_management/', include('api_management.urls')),
    path('async_media/', include('async_media.urls')),
    path('blog/', include('blog.urls')),
    path('', include('calcification.urls')),
    path('', include('cpce.urls')),
    path(SOURCE_ID + 'export/', include('export.urls')),
    # Flatpages, such as the help page
    path('pages/', include('flatpages_custom.urls', namespace='pages')),
    path(IMAGE_ID, include('images.urls')),
    path('', include('jobs.urls')),
    path('', include('labels.urls')),
    path('newsfeed/', include('newsfeed.urls')),
    path('', include('sources.urls')),
    path(SOURCE_ID + 'upload/', include('upload.urls')),
    path('', include('upload.urls_js')),
    path('', include('vision_backend.urls')),
    path(SOURCE_ID + 'browse/', include('visualization.urls')),
    path('', include('visualization.urls_js')),

    # lib.views
    path('', lib_views.index, name='index'),
    path('about/',
         TemplateView.as_view(template_name='lib/about.html'),
         name='about'),
    path('privacy_policy/',
         TemplateView.as_view(template_name='lib/privacy_policy.html'),
         name='privacy_policy'),
    path('release/',
         TemplateView.as_view(template_name='lib/release_notes.html'),
         name='release'),
    path('admin_tools/', lib_views.admin_tools, name='admin_tools'),
    path('error_500_test/', lib_views.error_500_test, name='error_500_test'),
    path('js_test_poller/',
         lib_js_test_views.PollerQUnitView.as_view(),
         name='js_test_poller'),
    path('js_test_util/',
         lib_js_test_views.UtilQUnitView.as_view(),
         name='js_test_util'),
    path(SOURCE_ID + 'nav_test/', lib_views.nav_test, name='nav_test'),

    # Django's built-in admin
    path('admin/doc/', include('django.contrib.admindocs.urls')),
    path('admin/', admin.site.urls),

    # Internationalization
    path('i18n/', include('django.conf.urls.i18n')),

    # markdownx editor AJAX functionality (content preview and image upload).
    path('markdownx/', include('markdownx.urls')),
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
