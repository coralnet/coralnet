# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.contrib import admin

from .models import NewsItem, NewsSubItem

admin.site.register(NewsItem)
admin.site.register(NewsSubItem)
