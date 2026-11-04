from django.db import models
from django.conf import settings
from django.utils import timezone
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
        # з грошей, що клієнт лишив наперед (ANVAR 04.11.2026) — у касу нових грошей не додає (apps/billing/deposits.py)
        DEPOSIT = 'deposit', 'З депозиту'

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
    # Сума платежів (InvoicePayment) — зберігається, щоб борг рахувався запитом. Оплачений
    # рахунок із amount_paid < total = закритий з боргом (ANVAR 01.11.2026).
    amount_paid = models.DecimalField('Сплачено', max_digits=10, decimal_places=2, default=0)
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

    def _norm_discount(self):
        """Знижка не може бути відʼємною, а відсоткова — понад 100%.
        Без цього 380% давало відʼємний total і псувало суму чека."""
        if self.discount is None:
            self.discount = Decimal('0')
        elif self.discount < 0:
            self.discount = Decimal('0')
        elif self.discount_type == self.DiscountType.PERCENT and self.discount > 100:
            self.discount = Decimal('100')

    def calc_total(self):
        from django.db.models import Sum
        subtotal = self.lines.aggregate(t=Sum('total'))['t'] or Decimal('0')
        self._norm_discount()
        if self.discount_type == self.DiscountType.PERCENT:
            discount_amt = subtotal * self.discount / Decimal('100')
        else:
            discount_amt = min(self.discount, subtotal)
        return max(subtotal - discount_amt, Decimal('0'))

    def save(self, *args, **kwargs):
        self._norm_discount()
        super().save(*args, **kwargs)

    def save_total(self):
        self.total = self.calc_total()
        self.save(update_fields=['total'])

    @property
    def balance_due(self):
        """Скільки ще не сплачено (для чернетки — до закриття, для оплаченого — борг)."""
        return max((self.total or Decimal('0')) - (self.amount_paid or Decimal('0')), Decimal('0'))

    @property
    def has_debt(self):
        return self.status == self.Status.PAID and self.balance_due > 0

    def refresh_paid(self):
        """Перерахувати amount_paid із платежів; оплаченому — основний спосіб (де сплачено найбільше),
        щоб підписи й старі звіти лишались осмисленими й при змішаній оплаті."""
        from django.db.models import Sum
        # _base_manager: OrgManager без клініки в контексті (фонові задачі) віддає порожньо — і «сплачено» стало б 0
        mine = InvoicePayment._base_manager.filter(invoice=self)
        self.amount_paid = mine.aggregate(s=Sum('amount'))['s'] or Decimal('0')
        fields = ['amount_paid']
        if self.status == self.Status.PAID:
            top = mine.values('method').annotate(s=Sum('amount')).order_by('-s').first()
            if top:
                self.payment_method = top['method']
                fields.append('payment_method')
        self.save(update_fields=fields)

    @property
    def is_mixed_payment(self):
        return InvoicePayment._base_manager.filter(invoice=self).values('method').distinct().count() > 1


class InvoicePayment(models.Model):
    """Платіж за рахунком: частинами, змішано готівкою й карткою, погашення боргу (ANVAR 01.11.2026).
    До того рахунок знав один спосіб і вважався сплаченим цілком. Каса (finance.calculate_balances)
    рахує саме платежі — гроші, що реально надійшли."""
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='payments', verbose_name='Рахунок')
    organization = models.ForeignKey(
        'clinic.Organization', on_delete=models.CASCADE, related_name='invoice_payments', verbose_name='Організація',
    )
    amount = models.DecimalField('Сума', max_digits=10, decimal_places=2)
    method = models.CharField('Спосіб', max_length=10, choices=Invoice.PaymentMethod.choices)
    paid_at = models.DateTimeField('Коли', default=timezone.now)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = OrgManager()

    class Meta:
        ordering = ('paid_at', 'pk')
        verbose_name = 'Платіж'
        verbose_name_plural = 'Платежі'
        indexes = [models.Index(fields=['organization', 'method'], name='invpay_org_method_idx')]

    def __str__(self):
        return f'{self.amount} ₴ {self.get_method_display()} — рахунок #{self.invoice_id}'


class ClientDeposit(models.Model):
    """Депозит клієнта (ANVAR 04.11.2026): гроші, які клієнт лишив наперед, щоб з них платити свої рахунки.
    Тут — лише рух через касу: «внесено» (готівкою чи карткою) і «повернуто клієнту». Оплата рахунку з
    депозиту — InvoicePayment зі способом «З депозиту». Залишок рахує apps/billing/deposits.py."""
    class Kind(models.TextChoices):
        TOPUP = 'topup', 'Внесено на депозит'
        REFUND = 'refund', 'Повернуто клієнту'

    class Method(models.TextChoices):
        CASH = 'cash', 'Готівка'
        CARD = 'card', 'Картка'

    organization = models.ForeignKey(
        'clinic.Organization', on_delete=models.CASCADE, related_name='client_deposits', verbose_name='Організація',
    )
    client = models.ForeignKey(
        'clients.Client', on_delete=models.CASCADE, related_name='deposit_ops', verbose_name='Клієнт',
    )
    kind = models.CharField('Що', max_length=10, choices=Kind.choices)
    amount = models.DecimalField('Сума', max_digits=10, decimal_places=2)
    method = models.CharField('Спосіб', max_length=10, choices=Method.choices)
    note = models.CharField('Примітка', max_length=200, blank=True)
    created_at = models.DateTimeField('Коли', default=timezone.now)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )

    objects = OrgManager()

    class Meta:
        ordering = ('-created_at', '-pk')
        verbose_name = 'Рух депозиту'
        verbose_name_plural = 'Депозити клієнтів'
        indexes = [models.Index(fields=['organization', 'client'], name='clientdep_org_client_idx')]

    def __str__(self):
        return f'{self.get_kind_display()} {self.amount} ₴ — {self.client}'


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

    def _norm_discount(self):
        """Та сама стеля, що й для рахунку: 0..100% для відсотка, не мінус для суми."""
        if self.discount is None:
            self.discount = Decimal('0')
        elif self.discount < 0:
            self.discount = Decimal('0')
        elif self.discount_type == Invoice.DiscountType.PERCENT and self.discount > 100:
            self.discount = Decimal('100')

    def calc_total(self):
        base = self.quantity * self.unit_price
        self._norm_discount()
        if self.discount_type == Invoice.DiscountType.PERCENT:
            return base * (1 - self.discount / Decimal('100'))
        return max(base - self.discount, Decimal('0'))

    def save(self, *args, **kwargs):
        self.total = self.calc_total()
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = 'Рядок рахунку'
