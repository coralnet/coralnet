# Generated by Django 2.2.20 on 2022-11-28 01:25

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api_core', '0005_remove_fields_covered_by_internal_job'),
    ]

    operations = [
        migrations.AddField(
            model_name='apijobunit',
            name='order_in_parent',
            field=models.PositiveIntegerField(null=True),
        ),
    ]
