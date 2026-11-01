"""Кожному оплаченому рахунку — один платіж на всю суму його способом і датою. Після цього каса
рахує платежі, і її сума не змінюється ні на копійку (звіряється до і після викладки)."""
from django.db import migrations


def forwards(apps, schema_editor):
    Invoice = apps.get_model('billing', 'Invoice')
    InvoicePayment = apps.get_model('billing', 'InvoicePayment')
    batch = []
    paid = (Invoice.objects.filter(status='paid', total__gt=0)
            .values_list('pk', 'organization_id', 'total', 'payment_method', 'date', 'created_by_id'))
    for pk, org_id, total, method, date, author in paid.iterator(chunk_size=2000):
        batch.append(InvoicePayment(invoice_id=pk, organization_id=org_id, amount=total,
                                    method=method or 'cash', paid_at=date, created_by_id=author))
        if len(batch) >= 2000:
            InvoicePayment.objects.bulk_create(batch)
            batch = []
    if batch:
        InvoicePayment.objects.bulk_create(batch)
    Invoice.objects.filter(status='paid').update(amount_paid=models_F('total'))


def models_F(name):
    from django.db.models import F
    return F(name)


def backwards(apps, schema_editor):
    apps.get_model('billing', 'InvoicePayment').objects.all().delete()
    apps.get_model('billing', 'Invoice').objects.update(amount_paid=0)


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0010_invoicepayment'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
