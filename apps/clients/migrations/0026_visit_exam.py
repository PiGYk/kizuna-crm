from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clients', '0025_labresult'),
    ]

    operations = [
        migrations.AddField(
            model_name='visit',
            name='exam',
            field=models.TextField(blank=True, verbose_name='Клінічний огляд'),
        ),
        migrations.AddField(
            model_name='visittemplate',
            name='exam',
            field=models.TextField(blank=True, verbose_name='Клінічний огляд'),
        ),
    ]
