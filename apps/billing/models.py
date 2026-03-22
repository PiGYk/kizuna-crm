from django.db import models
from django.conf import settings
from decimal import Decimal


class Invoice(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Чернетка'
        PAID = 'paid', 'Оплачено'
        CANCELLED = 'cancelled', 'Скасовано'

    class DiscountType(models.TextChoices):
        PERCENT = 'percent', '%'
        AMOUNT = 'amount', '₴'

    client = models.ForeignKey(
        'clients.Client', on_delete=models.PROTECT, related_name='invoices',
        verbose_name='Клієнт'
    )
    patient = models.ForeignKey(
        'clients.Patient', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='invoices', verbose_name='Пацієнт'
    )
    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='invoices', verbose_name='Лікар'
    )
    date = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    discount = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, verbose_name='Знижка'
    )
    discount_type = models.CharField(
        max_length=10, choices=DiscountType.choices, default=DiscountType.PERCENT
    )
    total = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, verbose_name='Сума'
    )
    notes = models.TextField(blank=True, verbose_name='Нотатки')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name='created_invoices'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Рахунок'
        verbose_name_plural = 'Рахунки'

    def __str__(self):
        return f'Рахунок #{self.pk} — {self.client}'

    def calc_total(self):
        subtotal = sum(line.total for line in self.lines.all())
        if self.discount_type == self.DiscountType.PERCENT:
            discount_amt = subtotal * self.discount / Decimal('100')
        else:
            discount_amt = self.discount
        return max(subtotal - discount_amt, Decimal('0'))

    def save_total(self):
        self.total = self.calc_total()
        self.save(update_fields=['total'])


class InvoiceLine(models.Model):
    class LineType(models.TextChoices):
        SERVICE = 'service', 'Послуга'
        PRODUCT = 'product', 'Товар'

    invoice = models.ForeignKey(
        Invoice, on_delete=models.CASCADE, related_name='lines'
    )
    line_type = models.CharField(max_length=10, choices=LineType.choices)
    service = models.ForeignKey(
        'services.Service', on_delete=models.SET_NULL, null=True, blank=True
    )
    product = models.ForeignKey(
        'inventory.Product', on_delete=models.SET_NULL, null=True, blank=True
    )
    name = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=10, decimal_places=3)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount_type = models.CharField(
        max_length=10,
        choices=Invoice.DiscountType.choices,
        default=Invoice.DiscountType.PERCENT
    )
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    stock_written_off = models.BooleanField(default=False)

    def calc_total(self):
        base = self.quantity * self.unit_price
        if self.discount_type == Invoice.DiscountType.PERCENT:
            return base * (1 - self.discount / Decimal('100'))
        return max(base - self.discount, Decimal('0'))

    def save(self, *args, **kwargs):
        self.total = self.calc_total()
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = 'Рядок рахунку'
