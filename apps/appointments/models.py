from django.db import models
from django.conf import settings
from apps.clinic.managers import OrgManager


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
    organization = models.ForeignKey(
        'clinic.Organization',
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='appointments',
        verbose_name='Організація',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    reminder_24h_sent = models.BooleanField(default=False)
    reminder_2h_sent = models.BooleanField(default=False)

    objects = OrgManager()

    class Meta:
        ordering = ['starts_at']
        verbose_name = 'Запис'
        verbose_name_plural = 'Записи'
        indexes = [
            models.Index(fields=['organization', 'starts_at'], name='appt_org_starts_idx'),
            models.Index(fields=['organization', 'status'], name='appt_org_status_idx'),
        ]

    def __str__(self):
        return f"{self.client} / {self.patient} — {self.starts_at:%d.%m %H:%M}"

    @property
    def ends_at(self):
        from datetime import timedelta
        return self.starts_at + timedelta(minutes=self.duration)


class LeadRequest(models.Model):
    """Заявка з публічної форми на сайті."""

    class Status(models.TextChoices):
        NEW = 'new', 'Нова'
        PROCESSED = 'processed', 'Оброблена'
        CANCELLED = 'cancelled', 'Скасована'

    name = models.CharField('Ім\'я', max_length=120)
    phone = models.CharField('Телефон', max_length=30)
    pet_name = models.CharField('Кличка', max_length=100, blank=True)
    pet_type = models.CharField('Вид тварини', max_length=50, blank=True)
    service_note = models.CharField('Причина звернення', max_length=255, blank=True)
    preferred_date = models.DateField('Бажана дата', null=True, blank=True)
    preferred_time = models.TimeField('Бажаний час', null=True, blank=True)
    notes = models.TextField('Примітки', blank=True)
    status = models.CharField(
        'Статус', max_length=20, choices=Status.choices, default=Status.NEW
    )
    organization = models.ForeignKey(
        'clinic.Organization', on_delete=models.CASCADE,
        null=True, blank=True, related_name='leads', verbose_name='Організація',
    )
    source = models.CharField('Джерело', max_length=100, default='website')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Заявка з сайту'
        verbose_name_plural = 'Заявки з сайту'

    def __str__(self):
        return f"{self.name} / {self.phone} — {self.created_at:%d.%m %H:%M}"
