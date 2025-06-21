from django.views.generic import ListView, DetailView

from lib.utils import CustomPaginator
from .models import BlogPost


class PostsList(ListView):

    model = BlogPost
    template_name = 'blog/post_list.html'
    context_object_name = 'posts'

    # Posts per page.
    paginate_by = 10
    # A non-zero value here would allow the last page to merge with the
    # second-last page, if the last page's post count is small enough.
    # We'll disallow that behavior since "Showing 1-10 of 23" along with
    # "Page 1 of 2" seems pretty confusing.
    paginate_orphans = 0

    def get_queryset(self):
        """Restrict to posts that the user is allowed to view."""
        return BlogPost.objects.get_visible_to_user(self.request.user)

    def get_paginator(self, *args, **kwargs):
        """
        This allows us to use pagination_links.html, which has stuff specific
        to our CustomPaginator class.
        """
        return CustomPaginator(dict(), *args, **kwargs)


class PostDetail(DetailView):

    model = BlogPost
    template_name = 'blog/post_detail.html'
    context_object_name = 'post'
    slug_field = 'slug'

    def get_queryset(self):
        """The queryset used to look up the post. We restrict to posts
        that the user is allowed to view. If the post isn't there, we 404."""
        return BlogPost.objects.get_visible_to_user(self.request.user)
