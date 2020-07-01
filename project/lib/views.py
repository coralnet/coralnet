from __future__ import unicode_literals

from django.conf import settings
from django.contrib.auth.decorators import permission_required
from django.http import HttpResponseRedirect, HttpResponseServerError
from django.shortcuts import render, get_object_or_404
from django.template import loader, TemplateDoesNotExist
from django.urls import reverse

from annotations.utils import get_sitewide_annotation_count
from images.models import Image, Source
from images.utils import get_map_sources, get_carousel_images


def index(request):
    """
    This view renders the front page.
    """
    if request.user.is_authenticated:
        return HttpResponseRedirect(reverse('source_list'))

    map_sources = get_map_sources()
    carousel_images = get_carousel_images()

    # Gather some stats
    total_sources = Source.objects.all().count()
    total_images = Image.objects.all().count()
    total_annotations = get_sitewide_annotation_count()

    return render(request, 'lib/index.html', {
        'map_sources': map_sources,
        'total_sources': total_sources,
        'total_images': total_images,
        'total_annotations': total_annotations,
        'carousel_images': carousel_images,
    })


@permission_required('is_superuser')
def admin_tools(request):
    """
    Admin tools portal page.
    """
    return render(request, 'lib/admin_tools.html')


def handler500(request, template_name='500.html'):
    try:
        template = loader.get_template(template_name)
    except TemplateDoesNotExist:
        return HttpResponseServerError(
            '<h1>Server Error (500)</h1>', content_type='text/html')
    return HttpResponseServerError(template.render({
        'request': request,
        'forum_link': settings.FORUM_LINK,
    }))


@permission_required('is_superuser')
def nav_test(request, source_id):
    """
    Test page for a new navigation header layout.
    """
    source = get_object_or_404(Source, id=source_id)
    return render(request, 'lib/nav_test.html', {
        'source': source,
    })
