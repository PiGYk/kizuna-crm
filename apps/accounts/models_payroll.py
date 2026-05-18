from django.db import models
from django.conf import settings
from decimal import Decimal


class Shift(models.Model):
    """Робоча зміна працівника."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='shifts', verbose_name='Працівник',
    )
    organization = models.ForeignKey(
        'clinic.Organization', on_delete=models.CASCADE,
        related_name='shifts', verbose_name='Організація',
    )
    date = models.DateField('Дата')
    start_time = models.TimeField('Початок', null=True, blank=True)
    end_time = models.TimeField('Кінець', null=True, blank=True)
    hours = models.DecimalField('Годин', max_digits=5, decimal_places=2, default=0)
    notes = models.CharField('Нотатки', max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-start_time']
        verbose_name = 'Зміна'
        verbose_name_plural = 'Зміни'
        unique_together = ['user', 'date']
        indexes = [
            models.Index(fields=['organization', 'date']),
            models.Index(fields=['user', 'date']),
        ]

    def __str__(self):
        return f'{self.user} — {self.date}'

    def save(self, *args, **kwargs):
        # Авторозрахунок годин
        if self.start_time and self.end_time and not self.hours:
            from datetime import datetime, timedelta
            start = datetime.combine(self.date, self.start_time)
            end = datetime.combine(self.date, self.end_time)
            if end < start:
                end += timedelta(days=1)
            self.hours = Decimal(str((end - start).total_seconds() / 3600)).quantize(Decimal('0.01'))
        super().save(*args, **kwargs)


class PayrollPeriod(models.Model):
    """Розрахунковий період зарплати."""

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Чернетка'
        APPROVED = 'approved', 'Затверджено'
        PAID = 'paid', 'Виплачено'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='payroll_periods', verbose_name='Працівник',
    )
    organization = models.ForeignKey(
        'clinic.Organization', on_delete=models.CASCADE,
        related_name='payroll_periods', verbose_name='Організація',
    )
    period_start = models.DateField('Початок періоду')
    period_end = models.DateField('Кінець періоду')
    shifts_count = models.PositiveIntegerField('Кількість змін', default=0)
    hours_total = models.DecimalField('Всього годин', max_digits=6, decimal_places=2, default=0)
    revenue_total = models.DecimalField('Виручка за період', max_digits=12, decimal_places=2, default=0)
    salary_fixed = models.DecimalField('Фіксована частина', max_digits=10, decimal_places=2, default=0)
    salary_bonus = models.DecimalField('Бонус (відсоток)', max_digits=10, decimal_places=2, default=0)
    salary_hourly_total = models.DecimalField('За години', max_digits=10, decimal_places=2, default=0)
    deductions = models.DecimalField('Утримання', max_digits=10, decimal_places=2, default=0)
    salary_total = models.DecimalField('До виплати', max_digits=10, decimal_places=2, default=0)
    status = models.CharField(
        'Статус', max_length=10, choices=Status.choices, default=Status.DRAFT,
    )
    notes = models.TextField('Нотатки', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField('Затверджено', null=True, blank=True)
    paid_at = models.DateTimeField('Виплачено', null=True, blank=True)

    class Meta:
        ordering = ['-period_end']
        verbose_name = 'Розрахунок зарплати'
        verbose_name_plural = 'Розрахунки зарплат'
        unique_together = ['user', 'period_start', 'period_end']

    def __str__(self):
        return f'{self.user} — {self.period_start} — {self.period_end}'

    def calculate(self):
        """Розраховує зарплату на основі типу і даних за період."""
        from apps.billing.models import Invoice
        from django.db.models import Sum

        user = self.user

        # Зміни за період
        shifts = Shift.objects.filter(
            user=user, organization=self.organization,
            date__gte=self.period_start, date__lte=self.period_end,
        )
        self.shifts_count = shifts.count()
        self.hours_total = shifts.aggregate(h=Sum('hours'))['h'] or 0

        # Виручка (чеки де лікар = цей user)
        self.revenue_total = Invoice.objects.filter(
            doctor=user, organization=self.organization,
            status='paid',
            created_at__date__gte=self.period_start,
            created_at__date__lte=self.period_end,
        ).aggregate(t=Sum('total'))['t'] or 0

        # Розрахунок по типу
        salary_type = getattr(user, 'salary_type', 'fixed')

        if salary_type == 'fixed':
            self.salary_fixed = user.salary_fixed or 0
            self.salary_bonus = 0
            self.salary_hourly_total = 0

        elif salary_type == 'percent':
            self.salary_fixed = 0
            self.salary_bonus = self.revenue_total * (user.salary_percent or 0) / 100
            self.salary_hourly_total = 0

        elif salary_type in ('mixed', 'fixed_percent'):
            self.salary_fixed = user.salary_fixed or 0
            self.salary_bonus = self.revenue_total * (user.salary_percent or 0) / 100
            self.salary_hourly_total = 0

        elif salary_type == 'per_shift':
            self.salary_fixed = 0
            self.salary_bonus = 0
            self.salary_hourly_total = self.shifts_count * (getattr(user, 'salary_per_shift', 0) or 0)

        elif salary_type == 'hourly':
            self.salary_fixed = 0
            self.salary_bonus = 0
            self.salary_hourly_total = self.hours_total * (user.salary_hourly or 0)

        self.salary_total = self.salary_fixed + self.salary_bonus + self.salary_hourly_total - self.deductions
