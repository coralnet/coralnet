# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2016-09-08 01:15
from __future__ import unicode_literals

from django.db import migrations


def create_locallabels_for_existing_labelsets(apps, schema_editor):
    LabelSet = apps.get_model('labels', 'LabelSet')
    LocalLabel = apps.get_model('labels', 'LocalLabel')

    for labelset in LabelSet.objects.all():
        for global_label in labelset.labels.all():
            local_label = LocalLabel(
                code=global_label.code,
                global_label=global_label,
                labelset=labelset,
            )
            local_label.save()


def do_nothing(apps, schema_editor):
    # A proper reversal would involve
    # 1. filling LabelSet.labels fields according to the LocalLabels, and
    # 2. filling Label.code fields according to the LocalLabels.
    print("\nNo action taken in this migration rollback."
          " Implement the rollback if it's needed;"
          " we just haven't bothered until we know it's needed.")


class Migration(migrations.Migration):

    dependencies = [
        ('labels', '0004_locallabel'),
    ]

    operations = [
        migrations.RunPython(
            create_locallabels_for_existing_labelsets, do_nothing),
    ]
