# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2016-11-01 20:02
from __future__ import unicode_literals

from django.db import migrations


def update_filepaths_in_db(apps, schema_editor, old_dir, new_dir):
    # Note: This migration will NOT move the image files themselves,
    # because using storage classes (which abstract away local vs. S3
    # storage), there is not a simple way to just move a file. There's
    # only copying, which can be a lot slower, and we may have a LOT
    # of images.
    # If you're not setting up a new development machine, make sure
    # that you've moved your image files from the old directory
    # to the new directory.
    # (If you haven't moved them yet, do it later.)

    Profile = apps.get_model('accounts', 'Profile')
    profiles = Profile.objects.all()
    profile_count = profiles.count()

    for num, profile in enumerate(profiles, 1):
        # This needs to take into account the fact that empty strings
        # are permitted in this field.
        # Those should be maintained.
        old_filepath = profile.avatar_file.name
        new_filepath = old_filepath.replace(old_dir, new_dir)

        # Update the filepath in the DB.
        # Since we have to craft a different filepath for each image,
        # there seems to be no way to do a bulk save/update.
        # http://stackoverflow.com/a/12661327
        profile.avatar_file.name = new_filepath
        profile.save()

        # Give progress updates every so often.
        if num % 100 == 0:
            print("Updated {num} of {count} DB entries...".format(
                num=num, count=profile_count))


def update_avatar_filepaths_in_db(apps, schema_editor):
    update_filepaths_in_db(apps, schema_editor, 'mugshots/', 'avatars/')


def rollback_avatar_filepaths_in_db(apps, schema_editor):
    update_filepaths_in_db(apps, schema_editor, 'avatars/', 'mugshots/')


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0008_mugshot_rename_to_avatar_file'),
    ]

    operations = [
        migrations.RunPython(
            update_avatar_filepaths_in_db, rollback_avatar_filepaths_in_db,
            elidable=True),
    ]
