from django.db import models
from apps.clinic.managers import OrgManager


class ServiceCategory(models.Model):
    name = models.CharField('Назва', max_length=100)
    sort_order = models.IntegerField('Порядок', default=0, help_text='Менше = вище у списку')
    organization = models.ForeignKey(
        'clinic.Organization',
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='service_categories',
        verbose_name='Організація',
    )

    objects = OrgManager()

    class Meta:
        verbose_name = 'Категорія послуг'
        verbose_name_plural = 'Категорії послуг'
        ordering = ('sort_order', 'name')

    def __str__(self):
        return self.name


class Service(models.Model):
    name = models.CharField('Назва', max_length=200)
    description = models.TextField('Опис', blank=True)
    price = models.DecimalField('Ціна', max_digits=10, decimal_places=2, default=0)
    is_active = models.BooleanField('Активна', default=True)
    show_on_website = models.BooleanField(
        'Показувати на сайті',
        default=False,
        help_text='Якщо увімкнено — послуга з\'явиться на kizuna.com.ua/pricelist/',
    )
    category = models.ForeignKey(
        ServiceCategory,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='services',
        verbose_name='Категорія',
    )
    organization = models.ForeignKey(
        'clinic.Organization',
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='services',
        verbose_name='Організація',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = OrgManager()

    class Meta:
        verbose_name = 'Послуга'
        verbose_name_plural = 'Послуги'
        ordering = ('name',)

    def __str__(self):
        return self.name


class ServiceComponent(models.Model):
    service = models.ForeignKey(Service, on_delete=models.CASCADE,
                                related_name='components', verbose_name='Послуга')
    product = models.ForeignKey('inventory.Product', on_delete=models.PROTECT,
                                verbose_name='Товар зі складу')
    quantity = models.DecimalField('Кількість', max_digits=10, decimal_places=3)

    class Meta:
        verbose_name = 'Компонент послуги'
        verbose_name_plural = 'Компоненти послуги'

    def __str__(self):
        return f"{self.product.name} × {self.quantity}"
