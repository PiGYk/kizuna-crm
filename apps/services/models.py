from django.db import models


class Service(models.Model):
    name = models.CharField('Назва', max_length=200)
    description = models.TextField('Опис', blank=True)
    price = models.DecimalField('Ціна', max_digits=10, decimal_places=2, default=0)
    is_active = models.BooleanField('Активна', default=True)
    created_at = models.DateTimeField(auto_now_add=True)

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
