from django import forms
from .models import Client, Patient

FIELD_CLASS = (
    'w-full px-4 py-2.5 border border-gray-300 rounded-lg text-sm '
    'focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent'
)


class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = ('first_name', 'last_name', 'phone', 'email', 'notes')
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', FIELD_CLASS)


class PatientForm(forms.ModelForm):
    class Meta:
        model = Patient
        fields = ('name', 'species', 'breed', 'sex', 'date_of_birth', 'color', 'photo', 'assigned_doctor', 'notes')
        widgets = {
            'date_of_birth': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', FIELD_CLASS)
