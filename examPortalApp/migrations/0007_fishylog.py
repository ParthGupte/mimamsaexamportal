# Generated by Django 2.1.1 on 2021-06-21 13:02

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('examPortalApp', '0006_team_finished'),
    ]

    operations = [
        migrations.CreateModel(
            name='Fishylog',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('username', models.TextField()),
                ('popup_opentime', models.DateTimeField()),
                ('actionCommited', models.TextField()),
                ('popup_closetime', models.DateTimeField(default=None, null=True)),
            ],
        ),
    ]
