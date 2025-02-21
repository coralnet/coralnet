# Generated by Django 4.2.16 on 2025-02-18 01:51

from django.db import migrations


def populate(apps, schema_editor):
    ApiJob = apps.get_model('api_core', 'ApiJob')

    for api_job in ApiJob.objects.all():
        units = api_job.apijobunit_set
        unfinished_units = units.filter(
            internal_job__status__in=['pending', 'in_progress'])
        if not unfinished_units.exists():
            api_job.finish_date = units.order_by(
                '-internal_job__modify_date').first().internal_job.modify_date
            api_job.save()


class Migration(migrations.Migration):

    dependencies = [
        ('api_core', '0012_apijob_finish_date'),
    ]

    operations = [
        migrations.RunPython(populate, migrations.RunPython.noop),
    ]
