import re

from django import forms
from django.db.models import Q

from .models import Organization

_input = lambda extra='': f'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-gold {extra}'.strip()
_color = 'w-14 h-9 p-0.5 border border-gray-300 rounded-lg cursor-pointer'

_HEX_COLOR = re.compile(r'^#[0-9A-Fa-f]{6}$')
# Токен від @BotFather: «<id бота>:<ключ>», ключ ~35 символів.
_TG_TOKEN = re.compile(r'^\d+:[A-Za-z0-9_-]{30,}$')

DAY_NAMES = ('Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Нд')

_WIDGETS = {
    'name':                 forms.TextInput(attrs={'class': _input()}),
    'short_name':           forms.TextInput(attrs={'class': _input()}),
    'address':              forms.TextInput(attrs={'class': _input()}),
    'phone':                forms.TextInput(attrs={'class': _input()}),
    'email':                forms.EmailInput(attrs={'class': _input()}),
    'work_hours':           forms.TextInput(attrs={'class': _input(), 'placeholder': 'Пн–Нд: 10:00–18:00'}),
    'website':              forms.TextInput(attrs={'class': _input()}),
    'route_video_url':      forms.TextInput(attrs={'class': _input(),
                            'placeholder': 'https://... (відео або карта з дорогою)'}),
    'currency_symbol':      forms.TextInput(attrs={'class': 'w-20 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-gold'}),
    'default_doctor':       forms.Select(attrs={'class': _input()}),
    'logo':                 forms.FileInput(attrs={'class': _input(), 'accept': 'image/png,image/jpeg,image/webp'}),
    'primary_color':        forms.TextInput(attrs={'type': 'color', 'class': _color}),
    'sidebar_color':        forms.TextInput(attrs={'type': 'color', 'class': _color}),
    'telegram_bot_token':   forms.TextInput(attrs={'class': _input(), 'placeholder': '123456:ABC-DEF...', 'autocomplete': 'off'}),
    'checkbox_license_key': forms.TextInput(attrs={'class': _input(), 'autocomplete': 'off'}),
    'checkbox_pin':         forms.TextInput(attrs={'class': _input(), 'autocomplete': 'off'}),
    'work_start':           forms.TimeInput(format='%H:%M', attrs={'type': 'time', 'class': _input()}),
    'work_end':             forms.TimeInput(format='%H:%M', attrs={'type': 'time', 'class': _input()}),
    'slot_duration':        forms.NumberInput(attrs={'min': '10', 'max': '120', 'step': '5', 'class': _input()}),
}


class _OrgSectionForm(forms.ModelForm):
    """Одна вкладка налаштувань = одна форма = лише ЇЇ поля.

    Сторінка налаштувань має окрему <form> на кожну вкладку. Раніше сервер
    перевіряв їх однією спільною формою на всі поля клініки: вкладка «Графік»
    не надсилає назву, «Клініка» — кольорів, тож кожне збереження падало на
    «обов'язкове поле» з чужої вкладки і нічого не записувало (скарга
    клієнта 31.10.2026: галочки Сб/Нд злітають, колір скидається, вкладка
    «Клініка» після збереження дизайну стоїть порожня).
    """

    class Meta:
        model = Organization
        fields = ()
        widgets = _WIDGETS


class ClinicInfoForm(_OrgSectionForm):
    class Meta(_OrgSectionForm.Meta):
        fields = (
            'name', 'short_name', 'address', 'phone', 'email',
            'work_hours', 'website', 'route_video_url', 'currency_symbol',
            'default_doctor',
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.accounts.models import User
        org = self.instance
        # Лише свої активні лікарі й адміни; уже вибраного лишаємо, навіть якщо
        # його вимкнули, — інакше форма мовчки скинула б його при збереженні.
        active = Q(is_active=True, takes_visits=True)
        if org.default_doctor_id:
            active |= Q(pk=org.default_doctor_id)
        field = self.fields['default_doctor']
        if org.pk:
            field.queryset = User.objects.filter(
                Q(organization=org) & Q(role__in=['admin', 'doctor']) & active,
            ).order_by('last_name', 'first_name')
        else:
            field.queryset = User.objects.none()
        field.empty_label = '— не вибрано —'


class ScheduleForm(_OrgSectionForm):
    """Робочі дні (галочки work_day_0…6) + години прийому і довжина слота."""

    class Meta(_OrgSectionForm.Meta):
        fields = ('work_start', 'work_end', 'slot_duration')

    def selected_days(self):
        if self.is_bound:
            return [d for d in range(7) if self.data.get(f'work_day_{d}')]
        days = self.instance.work_days or []
        return sorted(d for d in days if isinstance(d, int) and 0 <= d <= 6)

    def clean_slot_duration(self):
        value = self.cleaned_data.get('slot_duration')
        if value is not None and not 10 <= value <= 120:
            raise forms.ValidationError('Слот — від 10 до 120 хвилин.')
        return value

    def clean(self):
        cleaned = super().clean()
        days = self.selected_days()
        if not days:
            raise forms.ValidationError('Позначте хоча б один робочий день.')
        start, end = cleaned.get('work_start'), cleaned.get('work_end')
        if start and end and end <= start:
            self.add_error('work_end', 'Кінець прийому має бути пізніше за початок.')
        cleaned['work_days'] = days
        return cleaned

    def save(self, commit=True):
        self.instance.work_days = self.cleaned_data['work_days']
        return super().save(commit=commit)


class DesignForm(_OrgSectionForm):
    class Meta(_OrgSectionForm.Meta):
        fields = ('logo', 'primary_color', 'sidebar_color', 'page_background')
        widgets = {**_WIDGETS, 'page_background': forms.RadioSelect}

    def _clean_color(self, name):
        value = (self.cleaned_data.get(name) or '').strip()
        if not _HEX_COLOR.match(value):
            raise forms.ValidationError('Колір має бути у вигляді #RRGGBB.')
        return value.upper()

    def clean_primary_color(self):
        return self._clean_color('primary_color')

    def clean_sidebar_color(self):
        return self._clean_color('sidebar_color')

    def clean(self):
        cleaned = super().clean()
        # Нового файлу нема, а галочку «Видалити» поставили — прибираємо логотип.
        self.clear_logo = bool(self.data.get('logo-clear')) and not self.files.get('logo')
        return cleaned

    def save(self, commit=True):
        org = super().save(commit=False)
        if getattr(self, 'clear_logo', False) and org.logo:
            org.logo.delete(save=False)
            org.logo = None
        if commit:
            org.save()
        return org


class TelegramTokenForm(_OrgSectionForm):
    class Meta(_OrgSectionForm.Meta):
        fields = ('telegram_bot_token',)

    def clean_telegram_bot_token(self):
        token = ''.join((self.cleaned_data.get('telegram_bot_token') or '').split())
        if token and not _TG_TOKEN.match(token):
            raise forms.ValidationError(
                'Це не схоже на токен бота. Скопіюйте його з @BotFather повністю: '
                'цифри, двокрапка і довгий ключ.')
        return token


class CheckboxForm(_OrgSectionForm):
    class Meta(_OrgSectionForm.Meta):
        fields = ('checkbox_license_key', 'checkbox_pin')

    def clean_checkbox_license_key(self):
        return (self.cleaned_data.get('checkbox_license_key') or '').strip()

    def clean_checkbox_pin(self):
        return (self.cleaned_data.get('checkbox_pin') or '').strip()
