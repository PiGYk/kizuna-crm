from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tg', '0003_telegrammessage_media'),
    ]

    operations = [
        migrations.AddField(
            model_name='telegrammessage',
            name='media_filename',
            field=models.CharField(max_length=255, blank=True, default=''),
            preserve_default=False,
        ),
    ]
