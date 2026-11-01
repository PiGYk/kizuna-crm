from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.clinic.managers import RelatedOrgManager


class LabResult(models.Model):
    """Бланк лабораторного аналізу з даними рядками (ANVAR 01.11.2026). На відміну від
    PatientAnalysis (файл-скан), тут значення можна читати, порівнювати й друкувати.

    rows — [{"code", "name", "unit", "value", "low", "high"}]: значення й межі — рядки, бо
    в бланку буває «<5», «негатив», кома замість крапки. Типові показники й норми —
    apps/clients/lab_panels.py."""

    class Panel(models.TextChoices):
        BIOCHEMISTRY = 'biochemistry', 'Біохімія крові'
        HEMATOLOGY = 'hematology', 'Загальний аналіз крові'
        CYTOLOGY = 'cytology', 'Цитологія'
        HISTOLOGY = 'histology', 'Гістологія'
        OTHER = 'other', 'Інший аналіз'

    patient = models.ForeignKey(
        'clients.Patient', on_delete=models.CASCADE,
        related_name='lab_results', verbose_name='Пацієнт',
    )
    panel = models.CharField('Бланк', max_length=20, choices=Panel.choices)
    title = models.CharField('Назва', max_length=120, blank=True,
                             help_text='Порожньо — назва бланку')
    date = models.DateField('Дата', default=timezone.localdate)
    material = models.CharField('Матеріал', max_length=200, blank=True)
    rows = models.JSONField('Показники', default=list, blank=True)
    description = models.TextField('Опис', blank=True)
    conclusion = models.TextField('Висновок', blank=True)
    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='lab_results', verbose_name='Лікар',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+', verbose_name='Створив',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = RelatedOrgManager('patient__client__organization')

    class Meta:
        verbose_name = 'Бланк аналізу'
        verbose_name_plural = 'Бланки аналізів'
        ordering = ('-date', '-pk')

    def __str__(self):
        return f'{self.display_title} — {self.patient.name} ({self.date:%d.%m.%Y})'

    @property
    def display_title(self):
        return self.title or self.get_panel_display()

    @property
    def short(self):
        from .lab_panels import SHORT
        return SHORT.get(self.panel, 'АН')

    def rows_with_flags(self):
        from .lab_panels import flag, uk_number
        return [{**r, 'flag': flag(r), 'value_uk': uk_number(r.get('value')), 'low_uk': uk_number(r.get('low')),
                 'high_uk': uk_number(r.get('high'))} for r in self.rows or []]

    @property
    def out_of_range(self):
        from .lab_panels import flag
        return sum(1 for r in self.rows or [] if flag(r))
