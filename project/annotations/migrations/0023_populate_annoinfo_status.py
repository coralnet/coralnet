# Generated by Django 4.1.10 on 2023-11-05 07:35

from django.conf import settings
from django.db import migrations
from tqdm import tqdm


def image_annotation_status_copy(image):
    """
    Copy of the contents of the utility function image_annotation_status(),
    except with the `.unconfirmed()` custom-queryset function call replaced
    with a `.filter()` call. That custom-queryset function doesn't seem to be
    available in migrations unless the custom queryset is instantiated
    directly.
    https://stackoverflow.com/questions/28788819/
    """
    annotations = image.annotation_set.all()
    annotation_count = annotations.count()

    if annotation_count == 0:
        return 'unclassified'

    point_count = image.point_set.count()
    if annotation_count < point_count:
        return 'unclassified'

    if annotations.filter(user__username=settings.ROBOT_USERNAME).exists():
        return 'unconfirmed'

    return 'confirmed'


def populate_status_field(apps, schema_editor):
    """
    Populate all ImageAnnotationInfos' status fields.
    This can take a long time.
    """
    Source = apps.get_model('images', 'Source')

    for source in tqdm(Source.objects.all(), disable=settings.TQDM_DISABLE):
        for image in source.image_set.all():
            image.annoinfo.status = image_annotation_status_copy(image)
            image.annoinfo.save()


class Migration(migrations.Migration):

    dependencies = [
        ('annotations', '0022_annoinfo_confirmed_to_status'),
    ]

    operations = [
        migrations.RunPython(populate_status_field, migrations.RunPython.noop),
    ]
