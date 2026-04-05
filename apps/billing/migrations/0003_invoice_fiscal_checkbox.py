from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0002_payment_method'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoice',
            name='fiscal_receipt_id',
            field=models.CharField(blank=True, max_length=100, null=True, verbose_name='ID чеку Checkbox'),
        ),
        migrations.AddField(
            model_name='invoice',
            name='fiscal_status',
            field=models.CharField(
                choices=[('none', '—'), ('sent', 'Відправлено'), ('error', 'Помилка')],
                default='none',
                max_length=10,
                verbose_name='Статус фіскалізації',
            ),
        ),
        migrations.AlterField(
            model_name='invoice',
            name='payment_method',
            field=models.CharField(
                blank=True,
                choices=[('cash', 'Готівка'), ('card', 'Картка'), ('grey', 'Готівка (сіра)')],
                max_length=10,
                null=True,
                verbose_name='Спосіб оплати',
            ),
        ),
    ]
