# Generated by Django 4.1.8 on 2023-06-28 19:14

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('jobs', '0010_unique_constraint_update_inprogress_code'),
        ('vision_backend', '0012_rename_model_was_cashed_features_model_was_cached'),
    ]

    operations = [
        migrations.AddField(
            model_name='classifier',
            name='train_job',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='jobs.job'),
        ),
    ]
