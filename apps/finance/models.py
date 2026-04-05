from django.db import models
from django.conf import settings
from decimal import Decimal
from apps.clinic.managers import OrgManager


class FinanceSettings(models.Model):
    """Singleton — початкові залишки готівки та карти."""
    initial_cash = models.DecimalField(
        'Початковий залишок готівки', max_digits=12, decimal_places=2, default=0
    )
    initial_card = models.DecimalField(
        'Початковий залишок картки', max_digits=12, decimal_places=2, default=0
    )

    class Meta:
        verbose_name = 'Налаштування балансу'

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1, defaults={'initial_cash': 0, 'initial_card': 0})
        return obj


def calculate_balances():
    """Розраховує поточні залишки готівки та карти по всіх операціях."""
    from apps.billing.models import Invoice

    fs = FinanceSettings.get()

    def _sum(qs, field='amount'):
        return qs.aggregate(t=models.Sum(field))['t'] or Decimal('0')

    invoices_paid = Invoice.objects.filter(status='paid')
    income_cash = _sum(invoices_paid.filter(payment_method='cash'), 'total')
    income_card = _sum(invoices_paid.filter(payment_method='card'), 'total')

    expense_cash = _sum(Expense.objects.filter(payment_method='cash'))
    expense_card = _sum(Expense.objects.filter(payment_method='card'))

    card_to_cash = _sum(CashOperation.objects.filter(type='card_to_cash'))
    cash_to_card = _sum(CashOperation.objects.filter(type='cash_to_card'))
    deposits     = _sum(CashOperation.objects.filter(type='deposit'))
    withdrawals  = _sum(CashOperation.objects.filter(type='withdrawal'))

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
        'Фото чеку / накладної', upload_to='expenses/', blank=True
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
