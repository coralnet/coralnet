# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from images.models import Source

# Create your models here.


def log_item(source, app, message):
    ns = NewsItem(source_name=source.name,
                  source_id=source.id,
                  message=message,
                  app=app)
    ns.save()
    return ns


def log_sub_item(news_item, message):
    ni = NewsSubItem(news_item=news_item, message=message)
    ni.save()


class NewsItem(models.Model):
    """ These are main news-items to be displayed in the source main pages
    as well on an aggregate listings. """

    # Not using foreign keys since we don't want to delete a news-item if a
    # source is deleted.
    source_id = models.IntegerField(null=False, blank=False)
    source_name = models.CharField(null=False, blank=False, max_length=200)
    message = models.CharField(null=False, blank=False, max_length=500)
    app = models.CharField(null=False, blank=False, max_length=50,
                           choices=[(a, b) for a, b in
                                    zip(settings.INSTALLED_APPS,
                                        settings.INSTALLED_APPS)
                                    if not a.startswith('django')])
    datetime = models.DateTimeField(auto_now_add=True, editable=False)

    def render_view(self):

        curated = {
            'source_name': self.source_name,
            'source_id': self.source_id,
            'app': self.app,
            'message': self.message.format(subcount=NewsSubItem.objects.
                                           filter(news_item=self).count()),
            'datetime': self.datetime.strftime("%c"),
            'id': self.id,
        }
        sources = Source.objects.filter(id=self.source_id)
        if len(sources) == 0:
            curated['source_exists'] = False
        else:
            curated['source_exists'] = True
        return curated

    def clean(self):
        if self.app not in settings.INSTALLED_APPS:
            raise ValidationError(
                "Doesn't recognize {} as an installed app.".format(self.app))


class NewsSubItem(models.Model):
    """ These are sub-items on main news items. For examples, individual
    images annotated as part of a annotation session. """

    news_item = models.ForeignKey(NewsItem)
    message = models.CharField(null=False, blank=False, max_length=500)
    datetime = models.DateTimeField(auto_now_add=True, editable=False)

    def render_view(self):

        return {
            'message': self.message,
            'datetime': self.datetime.strftime("%c"),
            'id': self.id,
        }
