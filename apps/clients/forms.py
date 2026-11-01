import re

from django import forms
from django.contrib.auth import get_user_model
from .models import (
    Client, Patient, Visit, Vaccine, PatientAnalysis, WeightRecord,
    VisitTemplate, Prescription, PatientDocument, Hospitalization,
    UltrasoundReport, LabResult,
)

FIELD_CLASS = (
    'w-full px-4 py-2.5 border border-gray-300 rounded-lg text-base md:text-sm '
    'focus:outline-none focus:ring-2 focus:ring-brand-gold focus:border-transparent'
)

# Поля дат: px-2 замість px-4 — інакше «дд.мм.рррр» + іконка календаря
# не влазять і браузер обрізає рік (скарга Каті 26.09).
DATE_FIELD_CLASS = FIELD_CLASS.replace('px-4', 'px-2')

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
        # Галочка — НЕ текстове поле: FIELD_CLASS має w-full + padding, від чого
        # чекбокс розтягувався на всю ширину і підпис відлітав убік (спіймано 18.09).
        if isinstance(widget, forms.CheckboxInput):
            widget.attrs.setdefault(
                'class', 'h-4 w-4 rounded border-gray-300 text-brand-gold focus:ring-brand-gold')
            continue
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

    def __init__(self, *args, org=None, **kwargs):
        self._org = org
        # Виставляється у clean(), якщо телефон уже є в базі — шаблон показує кнопку
        # «Все одно створити».
        self.phone_duplicate = None
        super().__init__(*args, **kwargs)
        _apply_field_class(self)

    def clean(self):
        cleaned = super().clean()
        self.phone_duplicate = None
        # Користувач уже підтвердив, що заводить окрему картку — не заважаємо.
        if self.data.get('confirm_duplicate'):
            return cleaned
        org = self._org
        phone = cleaned.get('phone')
        if org and phone:
            digits = re.sub(r'\D', '', phone)
            if digits:
                # Порівнюємо за останніми 9 цифрами — без коду країни, найнадійніше.
                tail = digits[-9:]
                dup = Client.objects.filter(
                    organization=org, phone__regex=fr'.*{tail}$',
                ).exclude(pk=self.instance.pk or 0).first()
                if dup:
                    self.phone_duplicate = dup
                    self.add_error('phone', f'Клієнт із цим номером уже є: {dup}. Перевірте нижче.')
        return cleaned


class PatientForm(forms.ModelForm):
    class Meta:
        model = Patient
        fields = ('name', 'species', 'breed', 'sex', 'date_of_birth', 'age', 'is_neutered', 'color', 'microchip', 'microchip_date', 'photo', 'assigned_doctor', 'notes', 'allergies')
        widgets = {
            'date_of_birth': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'microchip_date': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'microchip': forms.TextInput(attrs={'placeholder': '15 цифр з чіпа', 'inputmode': 'numeric'}),
            'notes': forms.Textarea(attrs={'rows': 3}),
            'allergies': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, org=None, **kwargs):
        super().__init__(*args, **kwargs)
        User = get_user_model()
        if org is not None:
            self.fields['assigned_doctor'].queryset = User.practitioners(
                org, keep=self.instance.assigned_doctor_id,
            ).order_by('last_name', 'first_name')
        else:
            self.fields['assigned_doctor'].queryset = User.objects.none()
        _apply_field_class(self)


class VisitForm(forms.ModelForm):
    class Meta:
        model = Visit
        fields = ('date', 'doctor', 'complaint', 'exam', 'diagnosis', 'treatment', 'notes', 'follow_up_date')
        widgets = {
            'date': forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'type': 'datetime-local'}),
            'complaint': forms.Textarea(attrs={'rows': 2}),
            'exam': forms.Textarea(attrs={'rows': 2}),
            'diagnosis': forms.Textarea(attrs={'rows': 2}),
            'treatment': forms.Textarea(attrs={'rows': 2}),
            'notes': forms.Textarea(attrs={'rows': 2}),
            'follow_up_date': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
        }

    def __init__(self, *args, org=None, **kwargs):
        super().__init__(*args, **kwargs)
        User = get_user_model()
        if org is not None:
            self.fields['doctor'].queryset = User.practitioners(
                org, keep=self.instance.doctor_id,
            ).order_by('last_name', 'first_name')
        else:
            self.fields['doctor'].queryset = User.objects.none()
        # «Клінічний огляд» — лише клінікам, що його ввімкнули; інакше поля нема у формі взагалі
        # (і збереження не зачепить його значення)
        if not (org is not None and org.uses_visit_exam):
            self.fields.pop('exam', None)
        _apply_field_class(self)


class VaccineForm(forms.ModelForm):
    class Meta:
        model = Vaccine
        fields = ('name', 'date', 'next_date', 'valid_until', 'doctor', 'batch_number', 'notes')
        widgets = {
            'date': forms.DateInput(format='%Y-%m-%d',
                                    attrs={'type': 'date', 'class': DATE_FIELD_CLASS}),
            'next_date': forms.DateInput(format='%Y-%m-%d',
                                         attrs={'type': 'date', 'class': DATE_FIELD_CLASS}),
            'valid_until': forms.DateInput(format='%Y-%m-%d',
                                           attrs={'type': 'date', 'class': DATE_FIELD_CLASS}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, org=None, **kwargs):
        super().__init__(*args, **kwargs)
        User = get_user_model()
        if org is not None:
            self.fields['doctor'].queryset = User.practitioners(
                org, keep=self.instance.doctor_id,
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


_DT_LOCAL = ['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M']
_DT_SLACK = 10  # хвилин: годинник телефона може трохи бігти вперед


def _not_in_future(value, what):
    from datetime import timedelta
    from django.utils import timezone
    if value and value > timezone.now() + timedelta(minutes=_DT_SLACK):
        raise forms.ValidationError(f'{what} не може бути в майбутньому.')
    return value


class HospitalizationForm(forms.ModelForm):
    admitted_at = forms.DateTimeField(label='Надійшов', input_formats=_DT_LOCAL)

    class Meta:
        model = Hospitalization
        fields = ('admitted_at', 'reason', 'diagnosis', 'treatment', 'notes')
        widgets = {
            'reason': forms.Textarea(attrs={'rows': 2}),
            'diagnosis': forms.Textarea(attrs={'rows': 2}),
            'treatment': forms.Textarea(attrs={'rows': 2}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_field_class(self)

    def clean_admitted_at(self):
        return _not_in_future(self.cleaned_data.get('admitted_at'), 'Час надходження')


class DischargeForm(forms.ModelForm):
    """Виписка зі стаціонару: коли, з яким результатом і в якому стані (ANVAR 01.11 — для
    статистики лікаря й клініки). Цією ж формою дописують результат давнішим випискам."""
    discharged_at = forms.DateTimeField(label='Виписаний', input_formats=_DT_LOCAL)

    class Meta:
        model = Hospitalization
        fields = ('discharged_at', 'outcome', 'discharge_condition', 'discharge_notes')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['outcome'].required = True
        self.fields['outcome'].choices = [('', '— оберіть —')] + list(Hospitalization.Outcome.choices)
        _apply_field_class(self)

    def clean_discharged_at(self):
        value = _not_in_future(self.cleaned_data.get('discharged_at'), 'Час виписки')
        if value and self.instance.admitted_at and value < self.instance.admitted_at:
            raise forms.ValidationError('Виписка не може бути раніше за надходження.')
        return value


class LabResultForm(forms.ModelForm):
    """Поля бланку аналізу; показники (rows) і лікаря збирає view — вони рядками й списком."""
    class Meta:
        model = LabResult
        fields = ('date', 'title', 'material', 'description', 'conclusion')
        widgets = {
            'date': forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
            'description': forms.Textarea(attrs={'rows': 4}),
            'conclusion': forms.Textarea(attrs={'rows': 3}),
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
            'pancreas_notes': forms.Textarea(attrs={'rows': 2}),
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
        fields = ('name', 'complaint', 'exam', 'diagnosis', 'treatment', 'notes')
        widgets = {
            'complaint': forms.Textarea(attrs={'rows': 3}),
            'exam': forms.Textarea(attrs={'rows': 3}),
            'diagnosis': forms.Textarea(attrs={'rows': 3}),
            'treatment': forms.Textarea(attrs={'rows': 3}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, org=None, **kwargs):
        super().__init__(*args, **kwargs)
        if not (org is not None and org.uses_visit_exam):
            self.fields.pop('exam', None)
        _apply_field_class(self)
