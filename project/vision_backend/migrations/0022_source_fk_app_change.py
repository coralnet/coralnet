# Generated by Django 4.1.10 on 2024-04-17 03:07

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('sources', '0002_create_source'),
        ('vision_backend', '0021_features_populate_has_rowcols'),
    ]

    operations = [
        # Change images.source FKs to sources.source, and disable DB
        # constraints while we still have to sync up some related things.
        migrations.AlterField(
            model_name='classifier',
            name='source',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='sources.source', db_constraint=False),
        ),
        migrations.AlterField(
            model_name='score',
            name='source',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='sources.source', db_constraint=False),
        ),
    ]
