# -*- coding: utf-8 -*-
# Generated by Django 1.11.25 on 2019-11-06 02:16
from __future__ import unicode_literals

import accounts.models
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import easy_thumbnails.fields


def add_special_users(apps, schema_editor):
    # We can't get the User model directly as it may be a newer
    # version than this migration expects. We use the historical version.
    #
    # Similarly, we can't use settings.AUTH_USER_MODEL as it may be
    # different from what this migration expects. So we specify auth.User.
    User = apps.get_model('auth', 'User')
    user = User(username=settings.IMPORTED_USERNAME)
    user.save()
    user = User(username=settings.ROBOT_USERNAME)
    user.save()
    user = User(username=settings.ALLEVIATE_USERNAME)
    user.save()


class Migration(migrations.Migration):

    replaces = [('accounts', '0001_initial'), ('accounts', '0002_add_special_users'), ('accounts', '0003_alter_language_choices'), ('accounts', '0004_remove_language_and_other_alterations'), ('accounts', '0005_about_me_max_length_increase'), ('accounts', '0006_add_affiliation_and_other_fields'), ('accounts', '0007_avatar_additions'), ('accounts', '0008_mugshot_rename_to_avatar_file'), ('accounts', '0009_update_avatar_filepaths'), ('accounts', '0010_make_distinct_gravatar_hashes'), ('accounts', '0011_wrap_sha1_passwords'), ('accounts', '0012_field_string_attributes_to_unicode')]

    initial = True

    dependencies = [
        ('auth', '0008_alter_user_username_max_length'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Profile',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('avatar_file', easy_thumbnails.fields.ThumbnailerImageField(blank=True, help_text='Upload an image to display in your profile.', upload_to=accounts.models.get_avatar_upload_path, verbose_name='Avatar file')),
                ('privacy', models.CharField(choices=[('open', 'Public'), ('registered', 'Registered users only'), ('closed', 'Private')], default='registered', help_text='Designates who can view your profile.', max_length=15, verbose_name='Privacy')),
                ('about_me', models.CharField(blank=True, max_length=1000, verbose_name='About me')),
                ('website', models.URLField(blank=True, verbose_name='Website')),
                ('location', models.CharField(blank=True, max_length=45, verbose_name='Location')),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL, verbose_name='User')),
                ('affiliation', models.CharField(blank=True, help_text='Your university, research institution, etc.', max_length=100, verbose_name='Affiliation')),
                ('how_did_you_hear_about_us', models.CharField(blank=True, max_length=500, verbose_name='How did you hear about us?')),
                ('project_description', models.CharField(blank=True, max_length=500, verbose_name='Project description')),
                ('reason_for_registering', models.CharField(blank=True, max_length=500, verbose_name='Reason for registering')),
                ('random_gravatar_hash', models.CharField(default=accounts.models.get_random_gravatar_hash, editable=False, help_text="If an avatar isn't specified in another way, the fallback is a Gravatar based on this hash.", max_length=32, verbose_name='Random Gravatar hash')),
                ('use_email_gravatar', models.BooleanField(default=False, help_text="If you're not sure what Gravatar is, just leave this unchecked.", verbose_name='Use a Gravatar based on my email address')),
            ],
            options={},
        ),
        migrations.RunPython(
            code=add_special_users,
        ),
    ]
