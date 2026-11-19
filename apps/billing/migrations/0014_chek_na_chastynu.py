"""Чек на частину (Олег 19.11.2026): сума QR, що висить на терміналі, і чек Checkbox на кожен платіж."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0013_perekaz_na_fop'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoice',
            name='qr_amount',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True, verbose_name='Сума на QR'),
        ),
        migrations.AddField(
            model_name='invoicepayment',
            name='fiscal_receipt_id',
            field=models.CharField(blank=True, max_length=100, null=True, verbose_name='ID чеку Checkbox'),
        ),
        # Досі чек пробивався лише на весь рахунок — позначаємо його й на платежах таких рахунків
        migrations.RunSQL(
            "UPDATE billing_invoicepayment p SET fiscal_receipt_id = i.fiscal_receipt_id FROM billing_invoice i "
            "WHERE p.invoice_id = i.id AND i.fiscal_status = 'sent' AND i.fiscal_receipt_id IS NOT NULL "
            "AND i.fiscal_receipt_id <> '' AND p.fiscal_receipt_id IS NULL",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
