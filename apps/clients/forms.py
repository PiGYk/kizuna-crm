from django import forms
from .models import Client, Patient, Visit, Vaccine

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
        fields = ('name', 'species', 'breed', 'sex', 'age', 'is_neutered', 'color', 'photo', 'assigned_doctor', 'notes')
        widgets = {
            'date_of_birth': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', FIELD_CLASS)


class VisitForm(forms.ModelForm):
    class Meta:
        model = Visit
        fields = ('date', 'doctor', 'complaint', 'diagnosis', 'treatment', 'notes')
        widgets = {
            'date': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'complaint': forms.Textarea(attrs={'rows': 2}),
            'diagnosis': forms.Textarea(attrs={'rows': 2}),
            'treatment': forms.Textarea(attrs={'rows': 2}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', FIELD_CLASS)


class VaccineForm(forms.ModelForm):
    class Meta:
        model = Vaccine
        fields = ('name', 'date', 'next_date', 'doctor', 'batch_number', 'notes')
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'next_date': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', FIELD_CLASS)
