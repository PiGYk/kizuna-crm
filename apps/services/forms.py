from django import forms
from django.forms import inlineformset_factory
from .models import Service, ServiceComponent

FIELD_CLASS = (
    'w-full px-4 py-2.5 border border-gray-300 rounded-lg text-sm '
    'focus:outline-none focus:ring-2 focus:ring-brand-gold focus:border-transparent'
)


class ServiceForm(forms.ModelForm):
    class Meta:
        model = Service
        fields = ('name', 'description', 'price', 'is_active')
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', FIELD_CLASS)


class ServiceComponentForm(forms.ModelForm):
    class Meta:
        model = ServiceComponent
        fields = ('product', 'quantity')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', FIELD_CLASS)
        self.fields['product'].queryset = self.fields['product'].queryset.filter(is_active=True)
        self.fields['product'].empty_label = '— Товар —'


ComponentFormSet = inlineformset_factory(
    Service, ServiceComponent,
    form=ServiceComponentForm,
    extra=1,
    can_delete=True,
)
