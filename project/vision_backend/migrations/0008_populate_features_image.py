# -*- coding: utf-8 -*-
# Generated by Django 1.11.29 on 2021-03-24 08:24
from __future__ import unicode_literals

from django.conf import settings
from django.db import migrations
from tqdm import tqdm


def populate_features_image(apps, schema_editor):
    """
    Populate the Features model's image_new field using the Image.features
    value.
    """
    Image = apps.get_model('images', 'Image')
    Source = apps.get_model('images', 'Source')
    Features = apps.get_model('vision_backend', 'Features')

    # Iterate over sources, then images. We don't just flatly iterate over
    # images, because too many loop iterations (like millions) can cause
    # Python to hang indefinitely until the process is OS-killed.
    for source in tqdm(Source.objects.all(), disable=settings.TQDM_DISABLE):
        for image in Image.objects.filter(source=source):
            if image.features:
                features = Features.objects.get(pk=image.features.pk)
                features.image_new = image
                features.save()


class Migration(migrations.Migration):

    dependencies = [
        # Features field should be up to date
        ('images', '0013_add_features_foreignkey'),
        ('vision_backend', '0007_features_add_image_field'),
    ]

    operations = [
        migrations.RunPython(
            populate_features_image, migrations.RunPython.noop, elidable=True),
    ]
