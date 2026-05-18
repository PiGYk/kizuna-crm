from django import forms
from .models import Organization

_input = lambda extra='': f'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-gold {extra}'.strip()
_color = 'w-14 h-9 p-0.5 border border-gray-300 rounded-lg cursor-pointer'


class OrganizationSettingsForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Ці поля обробляються окремими action handlers, не основною формою
        for f in ('work_start', 'work_end', 'slot_duration',
                  'notify_appointment_24h', 'notify_appointment_2h', 'notify_vaccines'):
            if f in self.fields:
                self.fields[f].required = False

    class Meta:
        model = Organization
        fields = (
            'name', 'short_name', 'address', 'phone', 'email',
            'work_hours', 'website', 'currency_symbol',
            'default_doctor',
            'logo', 'primary_color', 'sidebar_color',
            'telegram_bot_token', 'checkbox_license_key', 'checkbox_pin',
            'work_start', 'work_end', 'slot_duration',
            'notify_appointment_24h', 'notify_appointment_2h', 'notify_vaccines',
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
            'default_doctor':       forms.Select(attrs={'class': _input()}),
            'logo':                 forms.FileInput(attrs={'class': _input(), 'accept': 'image/*'}),
            'primary_color':        forms.TextInput(attrs={'type': 'color', 'class': _color}),
            'sidebar_color':        forms.TextInput(attrs={'type': 'color', 'class': _color}),
            'telegram_bot_token':   forms.TextInput(attrs={'class': _input(), 'placeholder': '123456:ABC-DEF...', 'autocomplete': 'off'}),
            'checkbox_license_key': forms.TextInput(attrs={'class': _input(), 'autocomplete': 'off'}),
            'checkbox_pin':         forms.TextInput(attrs={'class': _input(), 'autocomplete': 'off'}),
            'work_start':           forms.TimeInput(attrs={'type': 'time', 'class': _input()}),
            'work_end':             forms.TimeInput(attrs={'type': 'time', 'class': _input()}),
            'slot_duration':        forms.NumberInput(attrs={'min': '10', 'max': '120', 'step': '5', 'class': _input()}),
            'notify_appointment_24h': forms.CheckboxInput(attrs={'class': 'rounded border-gray-300 text-brand-gold focus:ring-brand-gold'}),
            'notify_appointment_2h':  forms.CheckboxInput(attrs={'class': 'rounded border-gray-300 text-brand-gold focus:ring-brand-gold'}),
            'notify_vaccines':        forms.CheckboxInput(attrs={'class': 'rounded border-gray-300 text-brand-gold focus:ring-brand-gold'}),
        }
