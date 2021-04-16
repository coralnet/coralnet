import time

from bs4 import BeautifulSoup
from django.shortcuts import resolve_url

from lib.tests.utils import BasePermissionTest, ClientTest
from .utils import BlogTestMixin


class PermissionTest(BasePermissionTest):

    def test_post_list_permission(self):
        """Everyone can access the post list."""
        url = resolve_url('blog:post_list')
        template = 'blog/post_list.html'

        self.assertPermissionLevel(
            url, self.SIGNED_OUT, template=template)


class FooterLinkTest(ClientTest):
    """This isn't exactly a test of the blog, but of the site footer that's on
    every page. This still seemed like an OK place to put the test though."""

    def test_footer_link_to_post_list(self):
        index_response = self.client.get(resolve_url('index'))
        response_soup = BeautifulSoup(index_response.content, 'html.parser')
        footer_div = response_soup.find('div', id='footer')

        post_list_link = footer_div.find(
            'a', href=resolve_url('blog:post_list'))
        self.assertIsNotNone(
            post_list_link, "Footer has a link to the post list")


class PostPreviewTest(ClientTest, BlogTestMixin):

    def test_auto_preview(self):
        # > 26 words
        self.create_post(content=(
            "01 02 03 04 05 06 07 08 09 10 11 12 13 14 15"
            " 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30"))

        list_response = self.view_post_list()
        response_soup = BeautifulSoup(list_response.content, 'html.parser')
        preview_div = response_soup.find(
            'div', class_='blog-post-content-preview')
        self.assertHTMLEqual(
            preview_div.text,
            '01 02 03 04 05 06 07 08 09 10 11 12 13 14 15'
            ' 16 17 18 19 20 21 22 23 24 25 26 ... (More...)',
            "Post preview consists of first X words, ellipsis, and More link")

    def test_custom_preview(self):
        self.create_post(
            content="01 02 03 04 05", preview_content="10 20 30 40 50")

        list_response = self.view_post_list()
        response_soup = BeautifulSoup(list_response.content, 'html.parser')
        preview_div = response_soup.find(
            'div', class_='blog-post-content-preview')
        preview_paragraph = preview_div.find('p')
        self.assertHTMLEqual(
            str(preview_paragraph),
            '<p>10 20 30 40 50</p>',
            "Post preview consists of the specified preview content instead"
            " of the post content itself")

    def test_links_to_post_detail(self):
        post = self.create_post(title="A title")
        post_url = resolve_url('blog:post_detail', post.slug)

        list_response = self.view_post_list()
        response_soup = BeautifulSoup(list_response.content, 'html.parser')

        row_div = response_soup.find('div', class_='blog-post-row')
        title_link = row_div.find('h3').find('a')
        self.assertHTMLEqual(
            str(title_link),
            '<a href="{url}">A title</a>'.format(url=post_url),
            "Title link is as expected")

        preview_div = response_soup.find(
            'div', class_='blog-post-content-preview')
        more_link = preview_div.find('a')
        self.assertHTMLEqual(
            str(more_link),
            '<a href="{url}">(More...)</a>'.format(url=post_url),
            "More... link is as expected")


class ListedPostsTest(ClientTest, BlogTestMixin):
    """
    Test that the expected posts are listed.
    """
    def test_drafts_only_viewable_by_admins(self):
        regular_user = self.create_user()
        self.create_post(is_published=False)

        list_response = self.view_post_list(user=regular_user)
        response_soup = BeautifulSoup(list_response.content, 'html.parser')
        row_div = response_soup.find('div', class_='blog-post-row')
        self.assertIsNone(row_div, "A regular user can't see the draft")

        list_response = self.view_post_list(user=self.superuser)
        response_soup = BeautifulSoup(list_response.content, 'html.parser')
        row_div = response_soup.find('div', class_='blog-post-row')
        self.assertIsNotNone(row_div, "A superuser can see the draft")

    def test_order_drafts_first_then_published_by_date(self):
        # Ordering is finicky if the test creates posts too quickly, so we
        # have to throttle it with sleep...
        # To ensure draft ordering is correct, we'll create the draft neither
        # first nor last.
        self.create_post(title="Post 1")
        time.sleep(0.01)
        self.create_post(title="Post 2", is_published=False)
        time.sleep(0.01)
        self.create_post(title="Post 3")

        list_response = self.view_post_list(user=self.superuser)
        response_soup = BeautifulSoup(list_response.content, 'html.parser')
        row_divs = response_soup.find_all('div', class_='blog-post-row')
        listed_titles = [
            row_div.find('h3').find('a').contents[0] for row_div in row_divs]
        self.assertListEqual(
            ["Post 2", "Post 3", "Post 1"], listed_titles,
            "Draft first, then newer public post, then older public post")

    def test_pagination(self):
        # Ordering is finicky if the test creates posts too quickly, so we
        # have to throttle it with sleep...
        # There are 10 posts per page. We make 10*x + 1 posts to test that
        # the last page is allowed to have only 1 post. (The Django paginator
        # has a setting to merge the last 2 pages when the last page is small
        # enough.)
        for n in range(1, 21+1):
            self.create_post(title="P{n}".format(n=n))
            time.sleep(0.01)

        list_response = self.client.get(
            resolve_url('blog:post_list'))
        response_soup = BeautifulSoup(list_response.content, 'html.parser')
        row_divs = response_soup.find_all('div', class_='blog-post-row')
        listed_titles = [
            row_div.find('h3').find('a').contents[0] for row_div in row_divs]
        self.assertListEqual(
            ["P21", "P20", "P19", "P18", "P17",
             "P16", "P15", "P14", "P13", "P12"],
            listed_titles,
            "First page lists posts as expected")

        list_response = self.client.get(
            resolve_url('blog:post_list') + '?page=2')
        response_soup = BeautifulSoup(list_response.content, 'html.parser')
        row_divs = response_soup.find_all('div', class_='blog-post-row')
        listed_titles = [
            row_div.find('h3').find('a').contents[0] for row_div in row_divs]
        self.assertListEqual(
            ["P11", "P10", "P9", "P8", "P7", "P6", "P5", "P4", "P3", "P2"],
            listed_titles,
            "Second page lists posts as expected")

        list_response = self.client.get(
            resolve_url('blog:post_list') + '?page=3')
        response_soup = BeautifulSoup(list_response.content, 'html.parser')
        row_divs = response_soup.find_all('div', class_='blog-post-row')
        listed_titles = [
            row_div.find('h3').find('a').contents[0] for row_div in row_divs]
        self.assertListEqual(
            ["P1"],
            listed_titles,
            "Third page lists posts as expected")
