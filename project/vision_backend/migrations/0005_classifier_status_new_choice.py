# Generated by Django 2.2.20 on 2021-11-04 10:27

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vision_backend', '0004_remove_classifier_valid'),
    ]

    operations = [
        migrations.AlterField(
            model_name='classifier',
            name='status',
            field=models.CharField(choices=[('PN', 'Training pending'), ('UQ', 'Declined because the training labelset only had one unique label'), ('ER', 'Training got an error'), ('RJ', "Rejected because accuracy didn't improve enough"), ('AC', 'Accepted as new classifier')], default='PN', max_length=2),
        ),
    ]
