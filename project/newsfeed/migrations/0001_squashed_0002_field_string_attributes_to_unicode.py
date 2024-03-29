# Generated by Django 2.0.13 on 2021-04-19 22:06

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    replaces = [('newsfeed', '0001_initial'), ('newsfeed', '0002_field_string_attributes_to_unicode')]

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='NewsItem',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source_id', models.IntegerField()),
                ('source_name', models.CharField(max_length=200)),
                ('user_id', models.IntegerField()),
                ('user_username', models.CharField(max_length=50)),
                ('message', models.TextField(max_length=500)),
                ('category', models.CharField(choices=[('ml', 'ml'), ('source', 'source'), ('image', 'image'), ('annotation', 'annotation'), ('account', 'account')], max_length=50)),
                ('datetime', models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name='NewsSubItem',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('message', models.TextField(max_length=500)),
                ('datetime', models.DateTimeField(auto_now_add=True)),
                ('news_item', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='newsfeed.NewsItem')),
            ],
        ),
    ]
