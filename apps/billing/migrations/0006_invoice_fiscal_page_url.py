from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0005_invoice_fiscal_pending'),
    ]

    operations = [
        migrations.AddField(
            model_name='invoice',
            name='fiscal_page_url',
            field=models.URLField(blank=True, max_length=500, null=True, verbose_name='Посилання на оплату'),
        ),
    ]
