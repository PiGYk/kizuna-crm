import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0009_perf_indexes'),
        ('clinic', '0026_organization_lab_norms'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='invoice',
            name='amount_paid',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10, verbose_name='Сплачено'),
        ),
        migrations.CreateModel(
            name='InvoicePayment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('amount', models.DecimalField(decimal_places=2, max_digits=10, verbose_name='Сума')),
                ('method', models.CharField(choices=[('cash', 'Готівка'), ('card', 'Картка')], max_length=10, verbose_name='Спосіб')),
                ('paid_at', models.DateTimeField(default=django.utils.timezone.now, verbose_name='Коли')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('invoice', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='payments', to='billing.invoice', verbose_name='Рахунок')),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='invoice_payments', to='clinic.organization', verbose_name='Організація')),
            ],
            options={
                'verbose_name': 'Платіж',
                'verbose_name_plural': 'Платежі',
                'ordering': ('paid_at', 'pk'),
                'indexes': [models.Index(fields=['organization', 'method'], name='invpay_org_method_idx')],
            },
        ),
    ]
