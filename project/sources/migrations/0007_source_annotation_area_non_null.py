# Generated by Django 4.1.10 on 2024-05-05 02:39

from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Change source.image_annotation_area from allowing null to
    not allowing null.

    As of 2024/05, production has this non-null for all sources. The source
    form (rather than the model) has probably enforced non-null for most of
    CoralNet's lifetime. In any case, might as well make the field non-null
    on the model level for clarity.
    """

    dependencies = [
        ('sources', '0006_remove_long_help_texts'),
    ]

    operations = [
        migrations.AlterField(
            model_name='source',
            name='image_annotation_area',
            field=models.CharField(max_length=50, verbose_name='Default image annotation area'),
        ),
    ]
