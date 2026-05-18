from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('finance', '0005_alter_expense_receipt_photo'),
    ]

    operations = [
        # Expense — profit_data / balances range scans
        migrations.AddIndex(
            model_name='expense',
            index=models.Index(
                fields=['organization', 'date'],
                name='exp_org_date_idx',
            ),
        ),
        migrations.AddIndex(
            model_name='expense',
            index=models.Index(
                fields=['organization', 'payment_method'],
                name='exp_org_paymeth_idx',
            ),
        ),
        # CashOperation — calculate_balances aggregates
        migrations.AddIndex(
            model_name='cashoperation',
            index=models.Index(
                fields=['organization', 'type'],
                name='cashop_org_type_idx',
            ),
        ),
    ]
