# Generated by Django 4.2.16 on 2025-07-04 09:34

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('sources', '0010_populate_deployed_classifier'),
        ('images', '0047_metadata_source_data1'),
    ]

    operations = [
        # Make this field non-null, now that it's been populated.
        migrations.AlterField(
            model_name='metadata',
            name='source',
            field=models.ForeignKey(db_index=False, on_delete=django.db.models.deletion.CASCADE, to='sources.source'),
        ),
    ]
