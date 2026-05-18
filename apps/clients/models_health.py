from django.db import models


class HealthCheck(models.Model):
    """Автоматичне опитування стану здоров'я тварини."""

    class Status(models.TextChoices):
        PENDING = 'pending', 'Очікує відповіді'
        OK = 'ok', 'Все добре'
        CONCERN = 'concern', 'Є питання'
        NO_RESPONSE = 'no_response', 'Без відповіді'

    class Trigger(models.TextChoices):
        WEEKLY = 'weekly', 'Щотижневе'
        POST_VISIT = 'post_visit', 'Після візиту'
        POST_SURGERY = 'post_surgery', 'Після операції'
        SEASONAL = 'seasonal', 'Сезонне'

    patient = models.ForeignKey(
        'clients.Patient', on_delete=models.CASCADE,
        related_name='health_checks', verbose_name='Пацієнт',
    )
    organization = models.ForeignKey(
        'clinic.Organization', on_delete=models.CASCADE,
        related_name='health_checks',
    )
    trigger = models.CharField('Тип', max_length=20, choices=Trigger.choices)
    status = models.CharField('Статус', max_length=20, choices=Status.choices, default=Status.PENDING)
    question = models.TextField('Питання')
    response_text = models.TextField('Відповідь клієнта', blank=True)
    response_photo = models.ImageField('Фото відповіді', upload_to='health_checks/', null=True, blank=True)
    sent_at = models.DateTimeField('Відправлено', auto_now_add=True)
    responded_at = models.DateTimeField('Відповідь отримана', null=True, blank=True)
    visit = models.ForeignKey(
        'clients.Visit', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='health_checks',
        verbose_name='Пов\'язаний візит',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-sent_at']
        verbose_name = 'Опитування здоров\'я'
        verbose_name_plural = 'Опитування здоров\'я'

    def __str__(self):
        return f'{self.patient.name} — {self.get_trigger_display()} ({self.get_status_display()})'
