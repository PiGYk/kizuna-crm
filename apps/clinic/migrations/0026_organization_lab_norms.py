from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clinic', '0025_menu_config_effective'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='lab_norms',
            field=models.JSONField(blank=True, default=dict, verbose_name='Свої норми аналізів'),
        ),
    ]
