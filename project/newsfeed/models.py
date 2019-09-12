# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from images.models import Source
from django.contrib.auth.models import User

# Create your models here.


def log_item(source, user, category, message):
    """ Convenience method for creating a new NewsItem. """
    ns = NewsItem(source_name=source.name,
                  source_id=source.id,
                  user_id=user.id,
                  user_username=user.username,
                  message=message,
                  category=category)
    ns.save()
    return ns


def log_sub_item(news_item, message):
    """ Convenience method for creating a new NewsSubItem. """
    ni = NewsSubItem(news_item=news_item, message=message)
    ni.save()


class NewsItem(models.Model):
    """ These are main news-items to be displayed in the source main pages
    as well on an aggregate listings. """

    # Not using foreign keys since we don't want to delete a news-item if a
    # source or user is deleted.
    source_id = models.IntegerField(null=False, blank=False)
    source_name = models.CharField(null=False, blank=False, max_length=200)

    # Don't require the user to be set.
    user_id = models.IntegerField(null=False, blank=False)
    user_username = models.CharField(null=False, blank=False, max_length=50)

    message = models.TextField(null=False, blank=False, max_length=500)
    category = models.CharField(null=False, blank=False, max_length=50,
                                choices=[(a, b) for a, b in
                                         zip(settings.NEWS_ITEM_CATEGORIES,
                                             settings.NEWS_ITEM_CATEGORIES)])
    datetime = models.DateTimeField(auto_now_add=True, editable=False)

    def render_view(self):
        """ Renders the record into a dictionary used in the views. """

        curated = {
            'source_name': self.source_name,
            'source_id': self.source_id,
            'user_username': self.user_username,
            'user_id': self.user_id,
            'category': self.category,
            'message': self.message.format(subcount=NewsSubItem.objects.
                                           filter(news_item=self).count()),
            'datetime': self.datetime.strftime("%c"),
            'id': self.id,
        }
        sources = Source.objects.filter(id=self.source_id)
        curated['source_exists'] = sources.count() > 0

        users = User.objects.filter(id=self.user_id)
        curated['user_exists'] = users.count() > 0
        return curated

    def save(self, *args, **kwargs):
        self.clean()
        super(NewsItem, self).save(*args, **kwargs)

    def clean(self):
        if self.category not in settings.NEWS_ITEM_CATEGORIES:
            raise ValidationError(
                "Doesn't recognize {} as an installed app.".format(
                    self.category))


class NewsSubItem(models.Model):
    """ These are sub-items on main news items. For examples, individual
    images annotated as part of a annotation session. """

    news_item = models.ForeignKey(NewsItem)
    message = models.TextField(null=False, blank=False, max_length=500)
    datetime = models.DateTimeField(auto_now_add=True, editable=False)

    def render_view(self):
        """ Renders the record into a dictionary used in the views. """

        return {
            'message': self.message,
            'datetime': self.datetime.strftime("%c"),
            'id': self.id,
        }
