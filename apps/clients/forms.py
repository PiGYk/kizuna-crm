from django import forms
from django.contrib.auth import get_user_model
from .models import (
    Client, Patient, Visit, Vaccine, PatientAnalysis, WeightRecord,
    VisitTemplate, Prescription, PatientDocument, Hospitalization,
    UltrasoundReport,
)

FIELD_CLASS = (
    'w-full px-4 py-2.5 border border-gray-300 rounded-lg text-base md:text-sm '
    'focus:outline-none focus:ring-2 focus:ring-brand-gold focus:border-transparent'
)

# Для <select> — додаємо appearance-none + кастомний chevron, бо рідний на Android жахливий.
SELECT_EXTRA_CLASS = ' appearance-none bg-white bg-no-repeat pr-9'
SELECT_CHEVRON_STYLE = (
    "background-image: url(\"data:image/svg+xml;charset=UTF-8,"
    "%3csvg xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 24 24' "
    "stroke='%239ca3af' stroke-width='2'%3e%3cpath stroke-linecap='round' "
    "stroke-linejoin='round' d='M19 9l-7 7-7-7'/%3e%3c/svg%3e\"); "
    "background-position: right 0.5rem center; background-size: 1.25rem;"
)


def _apply_field_class(form):
    """Виставляє FIELD_CLASS для всіх полів і додатково стилізує <select>."""
    for field in form.fields.values():
        widget = field.widget
        widget.attrs.setdefault('class', FIELD_CLASS)
        if isinstance(widget, forms.Select) and not isinstance(widget, forms.SelectMultiple):
            widget.attrs['class'] = widget.attrs['class'] + SELECT_EXTRA_CLASS
            widget.attrs.setdefault('style', SELECT_CHEVRON_STYLE)


class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = ('first_name', 'last_name', 'phone', 'email', 'notes', 'discount_percent')
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_field_class(self)


class PatientForm(forms.ModelForm):
    class Meta:
        model = Patient
        fields = ('name', 'species', 'breed', 'sex', 'date_of_birth', 'age', 'is_neutered', 'color', 'photo', 'assigned_doctor', 'notes', 'allergies')
        widgets = {
            'date_of_birth': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 3}),
            'allergies': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, org=None, **kwargs):
        super().__init__(*args, **kwargs)
        User = get_user_model()
        if org is not None:
            self.fields['assigned_doctor'].queryset = User.objects.filter(
                organization=org, role__in=['admin', 'doctor'],
            ).order_by('last_name', 'first_name')
        else:
            self.fields['assigned_doctor'].queryset = User.objects.none()
        _apply_field_class(self)


class VisitForm(forms.ModelForm):
    class Meta:
        model = Visit
        fields = ('date', 'doctor', 'complaint', 'diagnosis', 'treatment', 'notes', 'follow_up_date')
        widgets = {
            'date': forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'type': 'datetime-local'}),
            'complaint': forms.Textarea(attrs={'rows': 2}),
            'diagnosis': forms.Textarea(attrs={'rows': 2}),
            'treatment': forms.Textarea(attrs={'rows': 2}),
            'notes': forms.Textarea(attrs={'rows': 2}),
            'follow_up_date': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
        }

    def __init__(self, *args, org=None, **kwargs):
        super().__init__(*args, **kwargs)
        User = get_user_model()
        if org is not None:
            self.fields['doctor'].queryset = User.objects.filter(
                organization=org, role__in=['admin', 'doctor'],
            ).order_by('last_name', 'first_name')
        else:
            self.fields['doctor'].queryset = User.objects.none()
        _apply_field_class(self)


class VaccineForm(forms.ModelForm):
    class Meta:
        model = Vaccine
        fields = ('name', 'date', 'next_date', 'valid_until', 'doctor', 'batch_number', 'notes')
        widgets = {
            'date': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'next_date': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'valid_until': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, org=None, **kwargs):
        super().__init__(*args, **kwargs)
        User = get_user_model()
        if org is not None:
            self.fields['doctor'].queryset = User.objects.filter(
                organization=org, role__in=['admin', 'doctor'],
            ).order_by('last_name', 'first_name')
        else:
            self.fields['doctor'].queryset = User.objects.none()
        _apply_field_class(self)


class AnalysisForm(forms.ModelForm):
    class Meta:
        model = PatientAnalysis
        fields = ('title', 'image', 'date', 'notes')
        widgets = {
            'date': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_field_class(self)


class WeightForm(forms.ModelForm):
    class Meta:
        model = WeightRecord
        fields = ('date', 'weight', 'notes')
        widgets = {
            'date': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_field_class(self)
        self.fields['notes'].required = False


class PrescriptionForm(forms.ModelForm):
    class Meta:
        model = Prescription
        fields = ('medication', 'dosage', 'frequency', 'duration', 'notes')
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_field_class(self)


class PatientDocumentForm(forms.ModelForm):
    class Meta:
        model = PatientDocument
        fields = ('title', 'file', 'date', 'notes')
        widgets = {
            'date': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_field_class(self)


class HospitalizationForm(forms.ModelForm):
    class Meta:
        model = Hospitalization
        fields = ('reason', 'diagnosis', 'treatment', 'notes')
        widgets = {
            'reason': forms.Textarea(attrs={'rows': 2}),
            'diagnosis': forms.Textarea(attrs={'rows': 2}),
            'treatment': forms.Textarea(attrs={'rows': 2}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_field_class(self)


class UltrasoundForm(forms.ModelForm):
    class Meta:
        model = UltrasoundReport
        exclude = ('patient', 'visit', 'doctor', 'created_at')
        widgets = {
            'date': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'liver_notes': forms.Textarea(attrs={'rows': 2}),
            'gallbladder_notes': forms.Textarea(attrs={'rows': 2}),
            'spleen_notes': forms.Textarea(attrs={'rows': 2}),
            'kidney_notes': forms.Textarea(attrs={'rows': 2}),
            'bladder_notes': forms.Textarea(attrs={'rows': 2}),
            'gi_notes': forms.Textarea(attrs={'rows': 3}),
            'reproductive_notes': forms.Textarea(attrs={'rows': 2}),
            'conclusion': forms.Textarea(attrs={'rows': 3}),
            'recommendations': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_field_class(self)
        for field in self.fields.values():
            field.required = False
        self.fields['date'].required = True


class VisitTemplateForm(forms.ModelForm):
    class Meta:
        model = VisitTemplate
        fields = ('name', 'complaint', 'diagnosis', 'treatment', 'notes')
        widgets = {
            'complaint': forms.Textarea(attrs={'rows': 3}),
            'diagnosis': forms.Textarea(attrs={'rows': 3}),
            'treatment': forms.Textarea(attrs={'rows': 3}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_field_class(self)
