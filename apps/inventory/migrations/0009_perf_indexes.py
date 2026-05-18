from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0008_unit_org_fk'),
    ]

    operations = [
        # StockMovement — COGS analytics, history listing
        migrations.AddIndex(
            model_name='stockmovement',
            index=models.Index(
                fields=['product', 'type', '-created_at'],
                name='stock_prod_type_dt_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='stockmovement',
            index=models.Index(
                fields=['type', '-created_at'],
                name='stock_type_dt_idx',
            ),
        ),
        # Product — active product listings + expiry alerts
        migrations.AddIndex(
            model_name='product',
            index=models.Index(
                fields=['organization', 'is_active', 'name'],
                name='prod_org_active_name_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='product',
            index=models.Index(
                fields=['organization', 'expiry_date'],
                name='prod_org_expiry_idx',
            ),
        ),
    ]
