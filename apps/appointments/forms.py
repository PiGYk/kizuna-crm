from datetime import datetime, time, timedelta

from django import forms
from django.utils import timezone

from .models import Appointment

FIELD = (
    'w-full px-3 py-2 border border-gray-300 rounded-lg text-sm '
    'focus:outline-none focus:ring-2 focus:ring-brand-gold'
)

# Слоти 08:00–20:00 по 30 хв (24-годинний формат)
_t = time(8, 0)
_end = time(20, 0)
TIME_CHOICES = []
while _t <= _end:
    label = _t.strftime('%H:%M')
    TIME_CHOICES.append((label, label))
    dt = datetime.combine(datetime.today(), _t) + timedelta(minutes=30)
    _t = dt.time()


class AppointmentForm(forms.ModelForm):
    appt_date = forms.DateField(
        label='Дата',
        widget=forms.DateInput(attrs={'type': 'date', 'class': FIELD}),
    )
    appt_time = forms.ChoiceField(
        label='Час',
        choices=TIME_CHOICES,
        widget=forms.Select(attrs={'class': FIELD}),
    )

    class Meta:
        model = Appointment
        fields = ('client', 'patient', 'doctor', 'appt_date', 'appt_time',
                  'duration', 'services', 'notes', 'status')
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 2, 'class': FIELD}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Заповнити дату/час з існуючого запису або з initial['starts_at']
        starts_at = None
        if self.instance and self.instance.pk and self.instance.starts_at:
            starts_at = timezone.localtime(self.instance.starts_at)
        elif self.initial.get('starts_at'):
            raw = self.initial['starts_at']
            if isinstance(raw, datetime):
                starts_at = timezone.localtime(raw) if timezone.is_aware(raw) else raw

        if starts_at:
            self.initial['appt_date'] = starts_at.date()
            self.initial['appt_time'] = starts_at.strftime('%H:%M')

        # Стилі для всіх звичайних полів
        for name, field in self.fields.items():
            if name not in ('appt_date', 'appt_time', 'notes'):
                field.widget.attrs.setdefault('class', FIELD)

        self.fields['patient'].required = False
        self.fields['doctor'].required = False
        self.fields['notes'].required = False
        self.fields['services'].required = False

        # Тільки лікарі/адміни у виборі лікаря
        from django.contrib.auth import get_user_model
        User = get_user_model()
        self.fields['doctor'].queryset = User.objects.filter(
            role__in=['admin', 'doctor'], is_active=True
        )

        # HTMX: клієнт → фільтр пацієнтів (заміна innerHTML у <select>)
        self.fields['client'].widget.attrs.update({
            'hx-get': '/appointments/patient-options/',
            'hx-trigger': 'change',
            'hx-target': '#id_patient',
            'hx-swap': 'innerHTML',
            'hx-include': '[name=client]',
        })

        # Послуги: висота щоб бачити кілька варіантів
        self.fields['services'].widget.attrs.update({
            'class': FIELD + ' h-32',
            'size': '5',
        })

    def clean(self):
        cleaned = super().clean()
        appt_date = cleaned.get('appt_date')
        appt_time = cleaned.get('appt_time')
        if appt_date and appt_time:
            h, m = map(int, appt_time.split(':'))
            naive_dt = datetime.combine(appt_date, time(h, m))
            self.instance.starts_at = timezone.make_aware(naive_dt)
        else:
            self.add_error('appt_date', 'Вкажіть дату та час')
        return cleaned
