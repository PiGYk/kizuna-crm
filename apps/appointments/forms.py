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


class ClientSelectWithPhone(forms.Select):
    """Select клієнта, що несе його телефон у data-phone кожної опції.

    Потрібно мобільній картці запису: під полем клієнта показується
    клікабельний номер, і він міняється разом з вибором — без запиту на сервер.
    """

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        client = getattr(value, 'instance', None)
        phone = getattr(client, 'phone', '') if client is not None else ''
        if phone:
            option['attrs']['data-phone'] = phone
        return option


class AppointmentForm(forms.ModelForm):
    appt_date = forms.DateField(
        label='Дата',
        input_formats=['%Y-%m-%d'],
        widget=forms.DateInput(attrs={'type': 'date', 'class': FIELD}, format='%Y-%m-%d'),
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
            'client': ClientSelectWithPhone(),
        }

    def __init__(self, *args, org=None, **kwargs):
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

        # Виконавець запису — БУДЬ-ЯКИЙ активний співробітник організації,
        # не лише лікарі й адміни: процедуру може вести асистент (прохання
        # Ірпеня 10.08). Лікарі показуються першими, далі решта за прізвищем.
        from django.contrib.auth import get_user_model
        from django.db.models import Case, When, IntegerField as _IntField
        from apps.clients.models import Client, Patient
        from apps.services.models import Service
        User = get_user_model()
        self.fields['doctor'].label = 'Виконавець'
        if org is not None:
            self.fields['doctor'].queryset = User.objects.filter(
                organization=org, is_active=True,
            ).annotate(
                _role_rank=Case(
                    When(role='doctor', then=0),
                    default=1,
                    output_field=_IntField(),
                )
            ).order_by('_role_rank', 'last_name', 'first_name')
            self.fields['client'].queryset = Client.objects.filter(
                organization=org,
            ).order_by('last_name', 'first_name')
            self.fields['client'].empty_label = None
            self.fields['doctor'].empty_label = '— Не вказано —'
            # Patient: явний queryset через base_manager — бо RelatedOrgManager
            # потребує thread-local org, який не доступний при імпорті форми
            # (queryset кешується як .none() назавжди → patient validation fail).
            self.fields['patient'].queryset = Patient._meta.base_manager.filter(
                client__organization=org,
            )
            self.fields['services'].queryset = Service.objects.filter(
                organization=org, is_active=True,
            ).order_by('name')
        else:
            self.fields['doctor'].queryset = User.objects.none()
            self.fields['client'].queryset = Client.objects.none()
            self.fields['patient'].queryset = Patient._meta.base_manager.none()
            self.fields['services'].queryset = Service.objects.none()

        # HTMX: клієнт → фільтр пацієнтів
        # hx-trigger='change' — Tom Select сам тригерить change на нативному select
        self.fields['client'].widget.attrs.update({
            'hx-get': '/appointments/patient-options/',
            'hx-trigger': 'change',
            'hx-target': '#id_patient',
            'hx-swap': 'innerHTML',
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
        doctor = cleaned.get('doctor')
        if appt_date and appt_time:
            h, m = map(int, appt_time.split(':'))
            naive_dt = datetime.combine(appt_date, time(h, m))
            starts_at = timezone.make_aware(naive_dt)
            self.instance.starts_at = starts_at

            # Перевірка конфлікту слотів з тим самим лікарем у тій же org.
            if doctor and self.instance.organization_id:
                conflict_qs = Appointment.objects.filter(
                    organization_id=self.instance.organization_id,
                    doctor=doctor,
                    starts_at=starts_at,
                    status__in=['scheduled', 'confirmed'],
                )
                if self.instance.pk:
                    conflict_qs = conflict_qs.exclude(pk=self.instance.pk)
                if conflict_qs.exists():
                    self.add_error(
                        'appt_time',
                        f'На {appt_time} у цього лікаря вже є запис',
                    )
        else:
            self.add_error('appt_date', 'Вкажіть дату та час')
        return cleaned
