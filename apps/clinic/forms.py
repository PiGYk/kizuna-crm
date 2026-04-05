from django import forms
from .models import Organization

_input = lambda extra='': f'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-gold {extra}'.strip()


class OrganizationSettingsForm(forms.ModelForm):
    class Meta:
        model = Organization
        fields = (
            'name', 'short_name', 'address', 'phone', 'email',
            'work_hours', 'website', 'currency_symbol',
            'telegram_bot_token', 'checkbox_license_key', 'checkbox_pin',
        )
        widgets = {
            'name':                 forms.TextInput(attrs={'class': _input()}),
            'short_name':           forms.TextInput(attrs={'class': _input()}),
            'address':              forms.TextInput(attrs={'class': _input()}),
            'phone':                forms.TextInput(attrs={'class': _input()}),
            'email':                forms.EmailInput(attrs={'class': _input()}),
            'work_hours':           forms.TextInput(attrs={'class': _input(), 'placeholder': 'Пн–Нд: 10:00–18:00'}),
            'website':              forms.TextInput(attrs={'class': _input()}),
            'currency_symbol':      forms.TextInput(attrs={'class': 'w-20 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-gold'}),
            'telegram_bot_token':   forms.TextInput(attrs={'class': _input(), 'placeholder': '123456:ABC-DEF...', 'autocomplete': 'off'}),
            'checkbox_license_key': forms.TextInput(attrs={'class': _input(), 'autocomplete': 'off'}),
            'checkbox_pin':         forms.TextInput(attrs={'class': _input(), 'autocomplete': 'off'}),
        }
