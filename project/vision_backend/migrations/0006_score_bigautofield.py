# Generated by Django 2.2.20 on 2022-05-14 05:38

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vision_backend', '0005_classifier_status_new_choice'),
    ]

    operations = [
        migrations.AlterField(
            model_name='score',
            name='id',
            field=models.BigAutoField(primary_key=True, serialize=False),
        ),
    ]
