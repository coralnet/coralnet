# Generated by Django 1.11.23 on 2019-08-19 01:00
from django.conf import settings
from django.db import migrations


def set_site_domain_based_on_setting(apps, schema_editor):
    Site = apps.get_model('sites', 'Site')

    # The site domain is used to build URLs in some places, such as in password
    # reset emails, and 'view on site' links in the admin site's blog post edit
    # view. Thus, the domain should correspond to the domain actually being
    # used by the current environment: production, staging, or development.
    #
    # Previously (migration 0001) we hardcoded the domain to
    # 'coralnet.ucsd.edu'. Now we set the domain to the environment-dependent
    # settings.SITE_DOMAIN.
    #
    # Note that Django doesn't seem to use this site domain in testing
    # environments. Tests will always use a domain of 'testserver' or something
    # like that, and the tests should 'just work' that way.
    site = Site.objects.get(pk=settings.SITE_ID)
    site.domain = settings.SITE_DOMAIN
    site.save()


class Migration(migrations.Migration):

    dependencies = [
        ('lib', '0001_set_site_name'),
    ]

    # Reverse operation is a no-op. The forward operation doesn't care if the
    # domain is already set correctly.
    operations = [
        migrations.RunPython(
            set_site_domain_based_on_setting, migrations.RunPython.noop),
    ]
