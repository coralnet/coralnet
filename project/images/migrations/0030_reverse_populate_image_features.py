# -*- coding: utf-8 -*-
# Generated by Django 1.11.29 on 2021-03-28 19:30
from __future__ import unicode_literals

from django.conf import settings
from django.db import migrations
from tqdm import tqdm


def populate_image_features(apps, schema_editor):
    """
    Populate the Image model's features field using the Features.image_new
    value (reverse relation is features_new).
    """
    Image = apps.get_model('images', 'Image')
    Source = apps.get_model('images', 'Source')

    # Iterate over sources, then images. We don't just flatly iterate over
    # images, because too many loop iterations (like millions) can cause
    # Python to hang indefinitely until the process is OS-killed.
    for source in tqdm(Source.objects.all(), disable=settings.TQDM_DISABLE):
        for image in Image.objects.filter(source=source):
            if image.features_new:
                image.features = image.features_new
                image.save()


class Migration(migrations.Migration):

    dependencies = [
        ('images', '0029_image_features_nullable'),
        # The Features.image_new field (with related name features_new)
        # should exist and be populated.
        # ('vision_backend', '0008_populate_features_image'),
    ]

    # To remove this field while making the migration process reversible,
    # we'll make the field nullable, then write a backwards migration to
    # populate the field, then remove the field. This is step 2.
    operations = [
        migrations.RunPython(
            migrations.RunPython.noop, populate_image_features, elidable=True),
    ]
