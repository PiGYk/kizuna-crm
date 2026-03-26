from django.db import models
from django.conf import settings
from decimal import Decimal


class ExpenseCategory(models.Model):
    name = models.CharField('Назва', max_length=100, unique=True)
    icon = models.CharField('Іконка', max_length=10, blank=True,
                            help_text='Емоджі для відображення')

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
    created_at = models.DateTimeField(auto_now_add=True)

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
    created_at = models.DateTimeField(auto_now_add=True)

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
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Касова операція'
        verbose_name_plural = 'Касові операції'
        ordering = ('-date', '-created_at')

    def __str__(self):
        return f'{self.get_type_display()} — {self.amount} ₴ ({self.date})'
