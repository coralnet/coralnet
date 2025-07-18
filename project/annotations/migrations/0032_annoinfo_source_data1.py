# Generated by Django 4.2.16 on 2025-07-13 02:54

from django.db import migrations


def populate_annoinfo_source(apps, schema_editor):
    """
    Populate the info model's source field using the
    image.source value.
    """
    ImageAnnotationInfo = apps.get_model('annotations', 'ImageAnnotationInfo')
    Source = apps.get_model('sources', 'Source')

    # Can't use joined fields with F(), like F('image__source'). So we
    # can't update all infos with a single update(). Instead we update
    # one source at a time.
    for source in Source.objects.all():
        ImageAnnotationInfo.objects.filter(image__source=source).update(
            source=source)


class Migration(migrations.Migration):

    dependencies = [
        ('annotations', '0031_annoinfo_source_schema1'),
    ]

    operations = [
        migrations.RunPython(
            populate_annoinfo_source,
            migrations.RunPython.noop,
            elidable=True,
        ),
    ]
