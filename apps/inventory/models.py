from django.db import models
from django.conf import settings
from decimal import Decimal


class Unit(models.Model):
    name = models.CharField('Назва', max_length=20, unique=True)
    short = models.CharField('Скорочення', max_length=10)

    class Meta:
        verbose_name = 'Одиниця виміру'
        verbose_name_plural = 'Одиниці виміру'
        ordering = ('name',)

    def __str__(self):
        return self.short


class Product(models.Model):
    name = models.CharField('Назва', max_length=200)
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, verbose_name='Одиниця')
    buy_price = models.DecimalField('Вхідна ціна', max_digits=10, decimal_places=2, default=0)
    sell_price = models.DecimalField('Вихідна ціна', max_digits=10, decimal_places=2, default=0)
    quantity = models.DecimalField('Залишок', max_digits=10, decimal_places=3, default=0)
    min_quantity = models.DecimalField('Мін. залишок', max_digits=10, decimal_places=3, default=0,
                                       help_text='При меншому залишку — попередження')
    notes = models.TextField('Нотатки', blank=True)
    is_active = models.BooleanField('Активний', default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Товар'
        verbose_name_plural = 'Товари'
        ordering = ('name',)

    def __str__(self):
        return f"{self.name} ({self.unit})"

    def is_low_stock(self):
        return self.quantity <= self.min_quantity and self.min_quantity > 0

    def is_out_of_stock(self):
        return self.quantity <= 0


class StockMovement(models.Model):
    class Type(models.TextChoices):
        IN = 'in', 'Прихід'
        OUT = 'out', 'Списання'
        ADJUST = 'adjust', 'Коригування'

    product = models.ForeignKey(Product, on_delete=models.CASCADE,
                                related_name='movements', verbose_name='Товар')
    type = models.CharField('Тип', max_length=10, choices=Type.choices)
    quantity = models.DecimalField('Кількість', max_digits=10, decimal_places=3)
    price = models.DecimalField('Ціна за од.', max_digits=10, decimal_places=2,
                                null=True, blank=True)
    reason = models.CharField('Причина', max_length=300, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, verbose_name='Хто',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Рух складу'
        verbose_name_plural = 'Рухи складу'
        ordering = ('-created_at',)

    def __str__(self):
        return f"{self.get_type_display()} {self.product.name} × {self.quantity}"

    def save(self, *args, **kwargs):
        if not self.pk:  # тільки при створенні
            if self.type == self.Type.IN:
                self.product.quantity += self.quantity
            elif self.type == self.Type.OUT:
                self.product.quantity -= self.quantity
            elif self.type == self.Type.ADJUST:
                self.product.quantity = self.quantity
            self.product.save(update_fields=['quantity'])
        super().save(*args, **kwargs)
