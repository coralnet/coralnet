# Generated by Django 2.2.20 on 2022-11-28 01:29

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api_core', '0007_populate_unit_order_from_request_json'),
    ]

    operations = [
        migrations.AlterField(
            model_name='apijobunit',
            name='order_in_parent',
            field=models.PositiveIntegerField(),
        ),
        migrations.AddConstraint(
            model_name='apijobunit',
            constraint=models.UniqueConstraint(fields=('parent', 'order_in_parent'), name='unique_order_within_parent'),
        ),
    ]
