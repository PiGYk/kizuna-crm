from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0004_org_fk'),
    ]

    operations = [
        migrations.AlterField(
            model_name='invoice',
            name='fiscal_status',
            field=models.CharField(
                choices=[
                    ('none', '—'),
                    ('pending', 'Очікує оплати'),
                    ('sent', 'Оплачено'),
                    ('error', 'Помилка'),
                ],
                default='none',
                max_length=10,
                verbose_name='Статус фіскалізації',
            ),
        ),
    ]
