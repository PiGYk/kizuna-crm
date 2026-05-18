from django.db import models
from django.conf import settings
from decimal import Decimal
from apps.clinic.managers import OrgManager


class Invoice(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Чернетка'
        PAID = 'paid', 'Оплачено'
        CANCELLED = 'cancelled', 'Скасовано'

    class DiscountType(models.TextChoices):
        PERCENT = 'percent', '%'
        AMOUNT = 'amount', '₴'

    class PaymentMethod(models.TextChoices):
        CASH = 'cash', 'Готівка'
        CARD = 'card', 'Картка'

    class FiscalStatus(models.TextChoices):
        NONE = 'none', '—'
        PENDING = 'pending', 'Очікує оплати'
        SENT = 'sent', 'Оплачено'
        ERROR = 'error', 'Помилка'

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
    payment_method = models.CharField(
        max_length=10, choices=PaymentMethod.choices, null=True, blank=True,
        verbose_name='Спосіб оплати'
    )
    notes = models.TextField(blank=True, verbose_name='Нотатки')
    fiscal_receipt_id = models.CharField(max_length=100, null=True, blank=True, verbose_name='ID чеку Checkbox')
    fiscal_page_url = models.URLField(max_length=500, null=True, blank=True, verbose_name='Посилання на оплату')
    fiscal_status = models.CharField(
        max_length=10, choices=FiscalStatus.choices, default=FiscalStatus.NONE,
        verbose_name='Статус фіскалізації'
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name='created_invoices'
    )
    organization = models.ForeignKey(
        'clinic.Organization',
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='invoices',
        verbose_name='Організація',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = OrgManager()

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Рахунок'
        verbose_name_plural = 'Рахунки'
        indexes = [
            models.Index(fields=['organization', 'status', 'created_at'], name='invoice_org_status_date_idx'),
            models.Index(fields=['organization', 'payment_method'], name='invoice_org_payment_idx'),
        ]

    def __str__(self):
        return f'Рахунок #{self.pk} — {self.client}'

    def calc_total(self):
        from django.db.models import Sum
        subtotal = self.lines.aggregate(t=Sum('total'))['t'] or Decimal('0')
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
    parent_line = models.ForeignKey(
        'self', on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='children',
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

    def __str__(self):
        return f'{self.name} ({self.quantity})'

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
