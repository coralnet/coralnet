# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models

# Create your models here.


class NewsItem(models.Model):

    source_id = models.IntegerField(null=False)
    user_id = models.IntegerField(null=False)
    message = models.CharField(null=False)
    create_date = models.DateTimeField(
        'Date created',
        auto_now_add=True, editable=False)

