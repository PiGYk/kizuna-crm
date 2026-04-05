from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tg', '0002_client_onetone_to_fk'),
    ]

    operations = [
        migrations.AddField(
            model_name='telegrammessage',
            name='media_type',
            field=models.CharField(max_length=20, blank=True, default=''),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='telegrammessage',
            name='media_file',
            field=models.FileField(upload_to='tg_media/', blank=True),
        ),
        migrations.AlterField(
            model_name='telegrammessage',
            name='text',
            field=models.TextField(blank=True),
        ),
    ]
