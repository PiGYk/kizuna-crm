from django.db import models
from django.conf import settings


class Appointment(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = 'scheduled', 'Заплановано'
        CONFIRMED = 'confirmed', 'Підтверджено'
        COMPLETED = 'completed', 'Виконано'
        CANCELLED = 'cancelled', 'Скасовано'
        NO_SHOW   = 'no_show',   'Не прийшов'

    class Duration(models.IntegerChoices):
        MIN_15  = 15,  '15 хв'
        MIN_30  = 30,  '30 хв'
        MIN_45  = 45,  '45 хв'
        MIN_60  = 60,  '1 год'
        MIN_90  = 90,  '1.5 год'
        MIN_120 = 120, '2 год'

    client = models.ForeignKey(
        'clients.Client', on_delete=models.CASCADE,
        related_name='appointments', verbose_name='Клієнт'
    )
    patient = models.ForeignKey(
        'clients.Patient', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='appointments', verbose_name='Пацієнт'
    )
    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='appointments', verbose_name='Лікар'
    )
    starts_at = models.DateTimeField('Початок')
    duration = models.IntegerField(
        'Тривалість (хв)', choices=Duration.choices, default=Duration.MIN_30
    )
    status = models.CharField(
        'Статус', max_length=20, choices=Status.choices, default=Status.SCHEDULED
    )
    services = models.ManyToManyField(
        'services.Service', blank=True, related_name='appointments',
        verbose_name='Заплановані послуги'
    )
    notes = models.TextField('Нотатки', blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, related_name='created_appointments'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['starts_at']
        verbose_name = 'Запис'
        verbose_name_plural = 'Записи'

    def __str__(self):
        return f"{self.client} / {self.patient} — {self.starts_at:%d.%m %H:%M}"

    @property
    def ends_at(self):
        from datetime import timedelta
        return self.starts_at + timedelta(minutes=self.duration)
