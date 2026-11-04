"""Депозит клієнта (ANVAR 04.11.2026): рух депозиту через касу + спосіб оплати рахунку «З депозиту».
Нова таблиця й нові варіанти вибору — наявні дані не змінюються."""
import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

PAY_CHOICES = [('cash', 'Готівка'), ('card', 'Картка'), ('deposit', 'З депозиту')]


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0011_backfill_invoice_payments'),
        ('clinic', '0027_page_background_lab_templates'),
        ('clients', '0027_ultrasound_kidneys_other'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name='invoice',
            name='payment_method',
            field=models.CharField(blank=True, choices=PAY_CHOICES, max_length=10, null=True, verbose_name='Спосіб оплати'),
        ),
        migrations.AlterField(
            model_name='invoicepayment',
            name='method',
            field=models.CharField(choices=PAY_CHOICES, max_length=10, verbose_name='Спосіб'),
        ),
        migrations.CreateModel(
            name='ClientDeposit',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(choices=[('topup', 'Внесено на депозит'), ('refund', 'Повернуто клієнту')], max_length=10, verbose_name='Що')),
                ('amount', models.DecimalField(decimal_places=2, max_digits=10, verbose_name='Сума')),
                ('method', models.CharField(choices=[('cash', 'Готівка'), ('card', 'Картка')], max_length=10, verbose_name='Спосіб')),
                ('note', models.CharField(blank=True, max_length=200, verbose_name='Примітка')),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now, verbose_name='Коли')),
                ('client', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='deposit_ops', to='clients.client', verbose_name='Клієнт')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='client_deposits', to='clinic.organization', verbose_name='Організація')),
            ],
            options={
                'verbose_name': 'Рух депозиту',
                'verbose_name_plural': 'Депозити клієнтів',
                'ordering': ('-created_at', '-pk'),
                'indexes': [models.Index(fields=['organization', 'client'], name='clientdep_org_client_idx')],
            },
        ),
    ]
