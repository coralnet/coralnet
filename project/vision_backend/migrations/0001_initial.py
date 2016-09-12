# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2016-09-12 16:01
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('images', '0011_rename_dupe_image_names'),
        ('annotations', '0007_color_setting_typo_fix'),
    ]

    operations = [
        migrations.CreateModel(
            name='Classifier',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('valid', models.BooleanField(default=False)),
                ('version', models.IntegerField(unique=True)),
                ('path_to_model', models.CharField(max_length=500)),
                ('runtime_train', models.BigIntegerField(default=0)),
                ('nbr_train_images', models.IntegerField(null=True)),
                ('create_date', models.DateTimeField(auto_now_add=True, verbose_name='Date created')),
                ('source', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='images.Source')),
            ],
        ),
        migrations.CreateModel(
            name='Features',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('extracted', models.BooleanField(default=False)),
                ('classified', models.BooleanField(default=False)),
                ('runtime_total', models.IntegerField(null = True)),
                ('runtime_core', models.IntegerField(null = True)),
                ('extracted_date', models.DateTimeField(null = True)),
            ],
        ),
        migrations.CreateModel(
            name='Score',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('score', models.IntegerField(default=0)),
                ('image', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='images.Image')),
                ('label', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='annotations.Label')),
                ('point', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='images.Point')),
                ('source', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='images.Source')),
            ],
        ),
    ]