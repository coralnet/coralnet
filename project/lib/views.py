from django.conf import settings
from django.contrib.auth.decorators import permission_required
from django.http import HttpResponseRedirect, HttpResponseServerError
from django.shortcuts import render, get_object_or_404
from django.template import loader, TemplateDoesNotExist
from django.urls import reverse

from annotations.utils import cacheable_annotation_count
from images.models import Image, Source
from images.utils import get_carousel_images
from map.utils import cacheable_map_sources


def index(request):
    """
    This view renders the front page.
    """
    if request.user.is_authenticated:
        return HttpResponseRedirect(reverse('source_list'))

    map_sources = cacheable_map_sources.get()
    carousel_images = get_carousel_images()

    # Gather some stats
    total_sources = Source.objects.all().count()
    total_images = Image.objects.all().count()
    total_annotations = cacheable_annotation_count.get()

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
    return render(request, 'lib/admin_tools.html', {
        'debug': settings.DEBUG,
    })


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
def error_500_test(request):
    """
    View to test 500 internal server errors. It's superuser-only to prevent
    abuse (i.e. clogging up admins' inboxes).
    """
    raise Exception("You entered the 500-error test view.")


@permission_required('is_superuser')
def nav_test(request, source_id):
    """
    Test page for a new navigation header layout.
    """
    source = get_object_or_404(Source, id=source_id)
    return render(request, 'lib/nav_test.html', {
        'source': source,
    })
