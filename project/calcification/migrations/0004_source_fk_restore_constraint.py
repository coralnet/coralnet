# Generated by Django 4.1.10 on 2024-04-18 09:27

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('calcification', '0003_source_fk_app_change'),
        ('images', '0038_rename_source_table'),
    ]

    operations = [
        # Re-enable sources.source FK constraints.
        migrations.AlterField(
            model_name='calcifyratetable',
            name='source',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to='sources.source', db_constraint=True),
        ),
    ]