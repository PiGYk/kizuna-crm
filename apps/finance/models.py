from django.db import models
from django.conf import settings
from decimal import Decimal
from apps.clinic.managers import OrgManager
from apps.clinic.uploads import expense_receipt_path


class FinanceSettings(models.Model):
    """Початкові залишки готівки та карти — per-organization."""
    organization = models.OneToOneField(
        'clinic.Organization',
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='finance_settings',
        verbose_name='Організація',
    )
    initial_cash = models.DecimalField(
        'Початковий залишок готівки', max_digits=12, decimal_places=2, default=0
    )
    initial_card = models.DecimalField(
        'Початковий залишок картки', max_digits=12, decimal_places=2, default=0
    )

    class Meta:
        verbose_name = 'Налаштування балансу'

    def __str__(self):
        return f'Фінанси — {self.organization}'

    @classmethod
    def get_for_org(cls, org):
        if org is None:
            return cls(initial_cash=Decimal('0'), initial_card=Decimal('0'))
        obj, _ = cls.objects.get_or_create(
            organization=org,
            defaults={'initial_cash': 0, 'initial_card': 0}
        )
        return obj

    @classmethod
    def get(cls):
        """Backward-compat: використовує thread-local org."""
        from apps.clinic.tenant import get_current_org
        return cls.get_for_org(get_current_org())


def calculate_balances(org=None):
    """Розраховує поточні залишки готівки та карти по всіх операціях.

    Один SUM-aggregate з Q-filter на queryset замість 8 окремих aggregate.
    """
    from django.db.models import Sum, Q
    from apps.billing.models import Invoice
    from apps.clinic.tenant import get_current_org

    if org is None:
        org = get_current_org()

    fs = FinanceSettings.get_for_org(org)
    zero = Decimal('0')

    inv_agg = Invoice.objects.filter(status='paid').aggregate(
        cash=Sum('total', filter=Q(payment_method='cash')),
        card=Sum('total', filter=Q(payment_method='card')),
    )
    income_cash = inv_agg['cash'] or zero
    income_card = inv_agg['card'] or zero

    exp_agg = Expense.objects.aggregate(
        cash=Sum('amount', filter=Q(payment_method='cash')),
        card=Sum('amount', filter=Q(payment_method='card')),
    )
    expense_cash = exp_agg['cash'] or zero
    expense_card = exp_agg['card'] or zero

    cash_agg = CashOperation.objects.aggregate(
        card_to_cash=Sum('amount', filter=Q(type='card_to_cash')),
        cash_to_card=Sum('amount', filter=Q(type='cash_to_card')),
        deposits=Sum('amount', filter=Q(type='deposit')),
        withdrawals=Sum('amount', filter=Q(type='withdrawal')),
    )
    card_to_cash = cash_agg['card_to_cash'] or zero
    cash_to_card = cash_agg['cash_to_card'] or zero
    deposits = cash_agg['deposits'] or zero
    withdrawals = cash_agg['withdrawals'] or zero

    cash = fs.initial_cash + income_cash - expense_cash + card_to_cash - cash_to_card + deposits - withdrawals
    card = fs.initial_card + income_card - expense_card - card_to_cash + cash_to_card

    return {'cash': cash, 'card': card}


class ExpenseCategory(models.Model):
    name = models.CharField('Назва', max_length=100)
    icon = models.CharField('Іконка', max_length=10, blank=True,
                            help_text='Емоджі для відображення')
    organization = models.ForeignKey(
        'clinic.Organization',
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='expense_categories',
        verbose_name='Організація',
    )

    objects = OrgManager()

    class Meta:
        verbose_name = 'Категорія витрат'
        verbose_name_plural = 'Категорії витрат'
        ordering = ('name',)

    def __str__(self):
        prefix = f'{self.icon} ' if self.icon else ''
        return f'{prefix}{self.name}'


class Supplier(models.Model):
    name = models.CharField('Назва', max_length=200)
    contact_person = models.CharField('Контактна особа', max_length=100, blank=True)
    phone = models.CharField('Телефон', max_length=20, blank=True)
    email = models.EmailField('Email', blank=True)
    notes = models.TextField('Нотатки', blank=True)
    organization = models.ForeignKey(
        'clinic.Organization',
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='suppliers',
        verbose_name='Організація',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = OrgManager()

    class Meta:
        verbose_name = 'Постачальник'
        verbose_name_plural = 'Постачальники'
        ordering = ('name',)

    def __str__(self):
        return self.name


class Expense(models.Model):
    class PaymentMethod(models.TextChoices):
        CASH = 'cash', 'Готівка'
        CARD = 'card', 'Картка'
        TRANSFER = 'transfer', 'Переказ'

    category = models.ForeignKey(
        ExpenseCategory, on_delete=models.PROTECT,
        related_name='expenses', verbose_name='Категорія'
    )
    supplier = models.ForeignKey(
        Supplier, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='expenses', verbose_name='Постачальник'
    )
    amount = models.DecimalField('Сума', max_digits=12, decimal_places=2)
    date = models.DateField('Дата')
    payment_method = models.CharField(
        'Спосіб оплати', max_length=10,
        choices=PaymentMethod.choices, default=PaymentMethod.CASH
    )
    description = models.CharField('Опис', max_length=500)
    receipt_photo = models.ImageField(
        'Фото чеку / накладної', upload_to=expense_receipt_path, blank=True
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, verbose_name='Хто вніс'
    )
    organization = models.ForeignKey(
        'clinic.Organization',
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='expenses',
        verbose_name='Організація',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = OrgManager()

    class Meta:
        verbose_name = 'Витрата'
        verbose_name_plural = 'Витрати'
        ordering = ('-date', '-created_at')

    def __str__(self):
        return f'{self.category} — {self.amount} ₴ ({self.date})'


class CashOperation(models.Model):
    class OperationType(models.TextChoices):
        DEPOSIT = 'deposit', 'Внесення в касу'
        WITHDRAWAL = 'withdrawal', 'Вилучення з каси'
        CARD_TO_CASH = 'card_to_cash', 'Картка → Готівка'
        CASH_TO_CARD = 'cash_to_card', 'Готівка → Картка'

    type = models.CharField('Тип', max_length=15, choices=OperationType.choices)
    amount = models.DecimalField('Сума', max_digits=12, decimal_places=2)
    date = models.DateField('Дата')
    description = models.CharField('Опис', max_length=500, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, verbose_name='Хто вніс'
    )
    organization = models.ForeignKey(
        'clinic.Organization',
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='cash_operations',
        verbose_name='Організація',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = OrgManager()

    class Meta:
        verbose_name = 'Касова операція'
        verbose_name_plural = 'Касові операції'
        ordering = ('-date', '-created_at')

    def __str__(self):
        return f'{self.get_type_display()} — {self.amount} ₴ ({self.date})'
