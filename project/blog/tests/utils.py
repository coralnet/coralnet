import uuid

from bs4 import BeautifulSoup
from django.shortcuts import resolve_url

from ..models import BlogPost


class BlogTestMixin(object):

    # These lines just exist to prevent an 'Unresolved attribute reference' or
    # similar IDE warning. The base test classes should end up setting
    # these in setup methods.
    client = None
    superuser = None

    @classmethod
    def create_post(cls, **kwargs):
        # Defaults
        data = dict(
            title="A title",
            slug="a-title-" + uuid.uuid4().hex,
            author="Post Author",
            content="Some content",
            preview_content="",
            is_published=True,
        )

        # Override defaults with any kwargs that are present
        data.update(**kwargs)
        # Save post
        post = BlogPost(**data)
        post.save()

        return post

    def view_post_list(self, user=None):
        if user:
            self.client.force_login(user)
        else:
            self.client.logout()

        url = resolve_url('blog:post_list')
        response = self.client.get(url)

        return response

    def view_post(self, post, user=None):
        if user:
            self.client.force_login(user)
        else:
            self.client.logout()

        url = resolve_url('blog:post_detail', post.slug)
        response = self.client.get(url)

        return response

    @staticmethod
    def get_post_content_html(post_detail_response):
        response_soup = BeautifulSoup(
            post_detail_response.content, 'html.parser')
        content_div = response_soup.find(
            'div', class_='blog-post-content')
        return ''.join(
            [str(child) for child in content_div.children])
