# Generated by Django 4.2.16 on 2024-10-14 00:04

from django.db import migrations


def hide_old_source_checks(apps, schema_editor):
    Job = apps.get_model('jobs', 'Job')

    for job in Job.objects.filter(job_name='check_source'):
        # Use update() so we can set the modify date to the existing value
        # rather than having it auto-set to the current date.
        Job.objects.filter(pk=job.pk).update(
            hidden=True, modify_date=job.modify_date)


class Migration(migrations.Migration):
    """
    Source checks have just been changed so that they're no longer
    automatically hidden; they're only hidden if they have the newly-added
    hidden flag.
    Those pre-existing, not-marked-as-hidden source checks will stick around
    for up to 30 days, and in general it seems desirable to hide them instead
    of letting them clutter the job lists' default views for that long. So we
    hide them in this migration.
    """

    dependencies = [
        ('jobs', '0018_job_hidden'),
    ]

    operations = [
        migrations.RunPython(
            hide_old_source_checks, migrations.RunPython.noop),
    ]
