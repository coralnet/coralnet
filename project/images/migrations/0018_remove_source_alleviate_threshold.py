# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2016-11-01 12:26
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('images', '0017_source_confidence_threshold'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='source',
            name='alleviate_threshold',
        ),
    ]
