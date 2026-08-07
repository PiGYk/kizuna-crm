"""Швидка реєстрація клієнта+тваринки прямо зі сторінки запису."""
import re

from django import forms

from apps.clients.models import Client, Patient


_PHONE_RE = re.compile(r'^[\d+]+$')


def normalize_phone(raw: str) -> str:
    """Залишає лише цифри для пошуку дублів. '+380 (50) 123-45-67' → '380501234567'."""
    return re.sub(r'\D', '', raw or '')


class QuickClientForm(forms.ModelForm):
    """Мінімальна форма клієнта для inline-створення з appointment-form."""

    class Meta:
        model = Client
        fields = ('first_name', 'last_name', 'phone', 'email', 'discount_percent')

    def clean_phone(self):
        phone = (self.cleaned_data.get('phone') or '').strip()
        if not phone:
            raise forms.ValidationError('Телефон обовʼязковий.')
        if not _PHONE_RE.match(phone.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')):
            raise forms.ValidationError('Телефон може містити лише цифри та "+".')
        return phone

    def clean(self):
        cleaned = super().clean()
        # Перевірка дубля у межах org — встановлюється у view через kwarg `org`.
        org = getattr(self, '_org', None)
        phone = cleaned.get('phone')
        if org and phone:
            digits = normalize_phone(phone)
            if digits:
                # Шукаємо за останніми 9 цифрами (без країнного коду) — найнадійніше.
                tail = digits[-9:]
                existing = Client.objects.filter(
                    organization=org, phone__regex=fr'.*{tail}$',
                ).exclude(pk=self.instance.pk or 0).first()
                if existing:
                    raise forms.ValidationError({
                        'phone': f'Клієнт з таким телефоном вже є: {existing} (id={existing.pk})',
                    })
        return cleaned


class QuickPatientForm(forms.ModelForm):
    """Тваринка: обовʼязкові лише name + species."""

    class Meta:
        model = Patient
        fields = ('name', 'species', 'breed', 'sex', 'date_of_birth')
        widgets = {
            'date_of_birth': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['breed'].required = False
        self.fields['sex'].required = False
        self.fields['date_of_birth'].required = False
