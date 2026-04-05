from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('clinic', '0005_organization_trial'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='plan',
            field=models.CharField(
                blank=True,
                choices=[
                    ('start', 'Старт — ₴990/міс'),
                    ('clinic', 'Клініка — ₴1 990/міс'),
                    ('network', 'Мережа — ₴3 990/міс'),
                ],
                default='',
                max_length=20,
                verbose_name='Тариф',
            ),
        ),
    ]
