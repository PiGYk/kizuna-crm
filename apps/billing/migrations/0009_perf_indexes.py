from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0008_add_parent_line'),
    ]

    operations = [
        # InvoiceLine — top_services/top_products groupings
        migrations.AddIndex(
            model_name='invoiceline',
            index=models.Index(
                fields=['invoice', 'line_type'],
                name='line_inv_type_idx',
            ),
        ),
    ]
