# Generated by Django 2.2.20 on 2022-12-14 09:57

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('jobs', '0005_dates_verbose_names'),
    ]

    operations = [
        migrations.RenameField(
            model_name='job',
            old_name='error_message',
            new_name='result_message',
        ),
    ]
