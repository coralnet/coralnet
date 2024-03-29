# Generated by Django 1.11.23 on 2019-09-08 07:20
from django.conf import settings
from django.core.management.sql import emit_post_migrate_signal
from django.db import migrations


def add_help_flatpage_if_not_present(apps, schema_editor):
    """Help is a flatpage that is linked from non-flatpages, so we make
    sure that Help exists in all project installations."""
    FlatPage = apps.get_model('flatpages', 'FlatPage')
    Site = apps.get_model('sites', 'Site')

    try:
        site = Site.objects.get(pk=settings.SITE_ID)
    except Site.DoesNotExist:
        # The Site is normally created as a result of the post-migration
        # signal.
        # However, if this is the first round of migrations ever run (e.g. in
        # unit tests), then we have to trigger this signal manually to create
        # the Site right now.

        # This function may or may not be private API, and thus its behavior
        # or signature may change without notice.
        emit_post_migrate_signal(0, False, 'default')

        # Try getting the Site again.
        site = Site.objects.get(pk=settings.SITE_ID)

    try:
        FlatPage.objects.get(url='/help/')
    except FlatPage.DoesNotExist:
        help_page = FlatPage(
            url='/help/', title="Help", content="Help contents go here.")
        help_page.save()
        help_page.sites.add(site)
        help_page.save()


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('flatpages', '0001_initial'),
        ('sites', '0001_initial'),
    ]

    # Reverse operation is a no-op.
    # Forward operation just adds the help page if not present. If it is
    # present, we don't care. So the operation can run again without reversing.
    operations = [
        migrations.RunPython(
            add_help_flatpage_if_not_present, migrations.RunPython.noop),
    ]
