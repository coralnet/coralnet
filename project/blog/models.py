from django.db import models
from django.urls import reverse
from django.utils import timezone

from .managers import BlogPostManager


class BlogPost(models.Model):
    """
    Various elements are borrowed from django-andablog.
    """

    title = models.CharField(max_length=255)

    slug = models.SlugField(
        max_length=80, unique=True,
        help_text="Dashed URL for the post. Example: officially-out-of-beta",
    )

    author = models.CharField(max_length=255)

    content = models.TextField(
        help_text="Post content will be interpreted as Markdown.")

    preview_content = models.TextField(
        blank=True,
        help_text=(
            "Preview content shown on the list of blog posts. If left blank,"
            " a preview is generated automatically using the first part"
            " of the post's main content. Interpreted as Markdown."),
    )

    is_published = models.BooleanField(default=False)

    published_timestamp = models.DateTimeField(
        blank=True, null=True, editable=False,
    )

    def __str__(self):
        return self.title

    class Meta:
        # Controls earliest() and latest().
        #
        # TODO: In Django 2.0, this can be a list. Might want to change this
        # to ['-is_published', 'published_timestamp'] so that
        # drafts are considered latest, followed by the latest-published post.
        get_latest_by = 'published_timestamp'

    objects = BlogPostManager()

    def get_absolute_url(self):
        return reverse('blog:post_detail', args=[self.slug])

    def save(self, *args, **kwargs):
        # Time to publish?
        if not self.published_timestamp and self.is_published:
            self.published_timestamp = timezone.now()
        elif not self.is_published:
            self.published_timestamp = None

        super().save(*args, **kwargs)

    def next_newest_post(self):
        # Even for admins, it doesn't really make sense to have drafts
        # included in previous/next links on the main site.
        # So we narrow it down to only published posts.
        published_posts = BlogPost.objects.get_published()

        if not self.is_published:
            # This is a draft, so this is considered newer than any
            # published post.
            return None

        newer_posts = published_posts.filter(
            published_timestamp__gt=self.published_timestamp)
        if newer_posts.count() == 0:
            # No published posts are newer.
            return None

        # There is a newer published post. Get the oldest of those.
        return newer_posts.earliest()

    def next_oldest_post(self):
        published_posts = BlogPost.objects.get_published()

        if not self.is_published:
            # This is a draft, so this is considered newer than any
            # published post. Thus the next oldest is the latest published.
            return published_posts.latest()

        older_posts = published_posts.filter(
            published_timestamp__lt=self.published_timestamp)
        if older_posts.count() == 0:
            # No published posts are older.
            return None

        # There is an older published post. Get the newest of those.
        return older_posts.latest()
