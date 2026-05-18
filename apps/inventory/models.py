from django.db import models
from django.db.models import F
from django.conf import settings
from django.core.validators import MinValueValidator
from decimal import Decimal
from apps.clinic.managers import OrgManager


class Category(models.Model):
    name = models.CharField('Назва', max_length=100)
    organization = models.ForeignKey(
        'clinic.Organization',
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='inventory_categories',
        verbose_name='Організація',
    )

    objects = OrgManager()

    class Meta:
        verbose_name = 'Категорія'
        verbose_name_plural = 'Категорії'
        ordering = ('name',)

    def __str__(self):
        return self.name


class Unit(models.Model):
    name = models.CharField('Назва', max_length=20)
    short = models.CharField('Скорочення', max_length=10)
    organization = models.ForeignKey(
        'clinic.Organization', on_delete=models.CASCADE,
        null=True, blank=True, related_name='units',
        verbose_name='Організація',
        help_text='Порожнє = глобальна (доступна всім)',
    )

    class Meta:
        verbose_name = 'Одиниця виміру'
        verbose_name_plural = 'Одиниці виміру'
        ordering = ('name',)
        constraints = [
            models.UniqueConstraint(fields=['name', 'organization'], name='unique_unit_per_org'),
        ]

    def __str__(self):
        return self.short


class Product(models.Model):
    name = models.CharField('Назва', max_length=200)
    sku = models.CharField('Артикул (SKU)', max_length=100, blank=True, db_index=True)
    category = models.ForeignKey(
        Category, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='products', verbose_name='Категорія'
    )
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, verbose_name='Одиниця')
    organization = models.ForeignKey(
        'clinic.Organization',
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='products',
        verbose_name='Організація',
    )

    objects = OrgManager()
    buy_price = models.DecimalField('Вхідна ціна', max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    sell_price = models.DecimalField('Вихідна ціна', max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    quantity = models.DecimalField('Залишок', max_digits=10, decimal_places=3, default=0)
    min_quantity = models.DecimalField('Мін. залишок', max_digits=10, decimal_places=3, default=0,
                                       help_text='При меншому залишку — попередження')
    notes = models.TextField('Нотатки', blank=True)
    is_active = models.BooleanField('Активний', default=True)
    expiry_date = models.DateField('Термін придатності', null=True, blank=True)
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

    def is_expired(self):
        from datetime import date
        return bool(self.expiry_date and self.expiry_date < date.today())

    def is_expiring_soon(self, days=30):
        from datetime import date, timedelta
        if not self.expiry_date:
            return False
        return date.today() <= self.expiry_date <= date.today() + timedelta(days=days)


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
    supplier = models.ForeignKey(
        'finance.Supplier',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='stock_movements',
        verbose_name='Постачальник',
    )
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
                Product.objects.filter(pk=self.product_id).update(quantity=F('quantity') + self.quantity)
            elif self.type == self.Type.OUT:
                Product.objects.filter(pk=self.product_id).update(quantity=F('quantity') - self.quantity)
            elif self.type == self.Type.ADJUST:
                Product.objects.filter(pk=self.product_id).update(quantity=self.quantity)
        super().save(*args, **kwargs)
