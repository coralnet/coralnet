from functools import wraps
from typing import Union

from django.conf import settings
from django.contrib import messages
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from annotations.utils import image_annotation_area_is_editable
from images.models import Image
from newsfeed.models import NewsItem
from sources.models import Source


class ModelViewDecorator():
    """
    Class for instantiating decorators for views.
    Specifically, views that take the id of a model as a parameter.

    :param model_class: The model that the view takes an id parameter of.
    :param meets_requirements: Function that determines whether we've
       met the requirements to show the view normally.
    :param template: Template to show if the requirements weren't met.
    :param get_extra_context: Function that gets extra info (as a dict)
       about the model object. In the case that we must render the
       requirements-not-met template, this extra info is added to the
       rendering context.
    :param default_message: Default message to display on the
       requirements-not-met template.
    """

    def __init__(self, model_class, meets_requirements,
                 template, get_extra_context=None,
                 default_message=None):
        self.model_class = model_class
        self.meets_requirements = meets_requirements
        self.template = template
        self.get_extra_context = get_extra_context
        self.default_message = default_message

    def __call__(self, object_id_view_arg, message=None, ajax=False, **requirements_kwargs):
        def decorator(view_func):
            def _wrapped_view(request, *args, **kwargs):

                if object_id_view_arg not in kwargs:
                    raise ValueError("Argument %s was not passed "
                                     "into view function" % object_id_view_arg)
                object_id = kwargs[object_id_view_arg]

                object = get_object_or_404(self.model_class, pk=object_id)

                if not self.meets_requirements(object, request, **requirements_kwargs):
                    fail_message = message or self.default_message or ""

                    # Ajax: Return a dict with an error field
                    if ajax:
                        return JsonResponse(dict(error=fail_message))

                    # Not Ajax: Render a template
                    context_dict = dict(message=fail_message)
                    if self.get_extra_context:
                        context_dict.update(self.get_extra_context(object))

                    return render(request, self.template, context_dict)

                return view_func(request, *args, **kwargs)
            return wraps(view_func)(_wrapped_view)
        return decorator


def image_get_extra_context(image):
    return dict(
        image=image,
        source=image.source,
    )


def source_get_extra_context(source):
    return dict(
        source=source,
    )


def source_permission_for_news_item(news_item, request, perm):
    """ Helper method for meets_requirements function of
    news_item_permission_required decorator. """

    sources = Source.objects.filter(id=news_item.source_id)
    if sources.count() == 1:
        return request.user.has_perm(perm, sources[0])
    else:
        return request.user.is_superuser


# @image_annotation_area_must_be_editable('image_id')
image_annotation_area_must_be_editable = ModelViewDecorator(
    model_class=Image,
    meets_requirements=lambda image, request: image_annotation_area_is_editable(image),
    template='annotations/annotation_area_not_editable.html',
    get_extra_context=image_get_extra_context,
    default_message="This image's annotation area is not editable, because re-generating points "
                    "would result in loss of data (such as annotations made in the annotation tool, "
                    "or points imported from outside the site)."
    )

# @image_labelset_required('image_id')
image_labelset_required = ModelViewDecorator(
    model_class=Image,
    meets_requirements=lambda image, request: image.source.labelset is not None,
    template='labels/labelset_required.html',
    get_extra_context=image_get_extra_context,
    default_message="You need to create a labelset before you can use this page."
    )

# @source_labelset_required('source_id')
source_labelset_required = ModelViewDecorator(
    model_class=Source,
    meets_requirements=lambda source, request: source.labelset is not None,
    template='labels/labelset_required.html',
    get_extra_context=source_get_extra_context,
    default_message="You need to create a labelset before you can use this page."
)

# @image_visibility_required('image_id')
image_visibility_required = ModelViewDecorator(
    model_class=Image,
    meets_requirements=lambda image, request: image.source.visible_to_user(request.user),
    template='permission_denied.html',
    default_message="Sorry, you don't have permission to view this page."
)

# @source_visibility_required('source_id')
source_visibility_required = ModelViewDecorator(
    model_class=Source,
    meets_requirements=lambda source, request: source.visible_to_user(request.user),
    template='permission_denied.html',
    default_message="Sorry, you don't have permission to view this page."
)

# TODO: Make this even more DRY: just pass in 'admin' instead of Source.PermTypes.ADMIN.code.
# @image_permission_required('image_id', perm=Source.PermTypes.<YOUR_PERMISSION_TYPE_HERE>.code)
image_permission_required = ModelViewDecorator(
    model_class=Image,
    meets_requirements=lambda image, request, perm: request.user.has_perm(perm, image.source),
    template='permission_denied.html',
    default_message="You don't have permission to access this part of this source."
)

# @source_permission_required('source_id', perm=Source.PermTypes.<YOUR_PERMISSION_TYPE_HERE>.code)
source_permission_required = ModelViewDecorator(
    model_class=Source,
    meets_requirements=lambda source, request, perm: request.user.has_perm(perm, source),
    template='permission_denied.html',
    default_message="You don't have permission to access this part of this source."
)

# @news_item_permission_required('news_item_id', perm=Source.PermTypes.<YOUR_PERMISSION_TYPE_HERE>.code)
news_item_permission_required = ModelViewDecorator(
    model_class=NewsItem,
    meets_requirements=lambda news_item, request, perm:
    source_permission_for_news_item(news_item, request, perm),
    template='permission_denied.html',
    default_message="You don't have permission to view this news item."
)

# Require DEBUG = True to access the view.
# @debug_required
def debug_required(view_func):
    def wrapper_func(request, *args, **kwargs):
        if not settings.DEBUG:
            # Deny access
            return render(request, 'permission_denied.html', dict(
                message="This page is inaccessible because DEBUG mode isn't on."
            ))
        else:
            # Serve the view
            return view_func(request, *args, **kwargs)
    return wrapper_func

# Version of login_required that can be used on Ajax views.
# @login_required_ajax
def login_required_ajax(view_func):
    def wrapper_func(request, *args, **kwargs):
        if not request.user.is_authenticated:
            # If not signed in, return error response
            return JsonResponse(
                dict(error="You must be signed in to access this function."))
        else:
            # Else, same behavior as calling the view directly
            return view_func(request, *args, **kwargs)
    return wrapper_func


def session_key_required(
        key: str, error_redirect: Union[str, list], error_prefix: str):
    """
    Require session data to exist at `key`, and require the timestamp stored
    there to match with the timestamp request arg.
    """
    def decorator(view_func):
        def _wrapped_view(request, *args, **kwargs):
            if isinstance(error_redirect, str):
                error_url_name = error_redirect
                url_args = []
            else:
                # list
                error_url_name, object_id_view_arg = error_redirect
                url_args = [kwargs[object_id_view_arg]]
            error_redirect_url = reverse(error_url_name, args=url_args)

            timestamp = request.GET.get('session_data_timestamp', None)
            # Can be None, or can be '' if it's from a form field that
            # didn't get filled in.
            if not timestamp:
                messages.error(
                    request,
                    f"{error_prefix}: Request data doesn't have a"
                    f" session_data_timestamp. This might be a bug."
                    f" If the problem persists, let us know on the forum."
                )
                return HttpResponseRedirect(error_redirect_url)

            session_value = request.session.pop(key, None)
            if not session_value:
                messages.error(
                    request,
                    f"{error_prefix}: We couldn't find the expected data in"
                    f" your session. Please try again."
                    f" If the problem persists, let us know on the forum."
                )
                return HttpResponseRedirect(error_redirect_url)

            if session_value['timestamp'] != timestamp:
                messages.error(
                    request,
                    f"{error_prefix}: Session data timestamp didn't match."
                    f" Please try again."
                    f" If the problem persists, let us know on the forum."
                )
                return HttpResponseRedirect(error_redirect_url)

            # The view function must expect a session_data arg.
            data = session_value['data']
            return view_func(request, *args, session_data=data, **kwargs)
        return wraps(view_func)(_wrapped_view)
    return decorator
