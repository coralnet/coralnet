# -*- coding: utf-8 -*-
# Generated by Django 1.11.29 on 2021-03-28 19:35
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('images', '0030_reverse_populate_image_features'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='image',
            name='features',
        ),
    ]
