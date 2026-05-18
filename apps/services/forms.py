from django import forms
from django.forms import inlineformset_factory
from .models import Service, ServiceComponent

FIELD_CLASS = (
    'w-full px-4 py-2.5 border border-gray-300 rounded-lg text-base md:text-sm '
    'focus:outline-none focus:ring-2 focus:ring-brand-gold focus:border-transparent'
)

# Для <select> — appearance-none + кастомний chevron, бо рідний на Android жахливий.
SELECT_EXTRA_CLASS = ' appearance-none bg-white bg-no-repeat pr-9'
SELECT_CHEVRON_STYLE = (
    "background-image: url(\"data:image/svg+xml;charset=UTF-8,"
    "%3csvg xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 24 24' "
    "stroke='%239ca3af' stroke-width='2'%3e%3cpath stroke-linecap='round' "
    "stroke-linejoin='round' d='M19 9l-7 7-7-7'/%3e%3c/svg%3e\"); "
    "background-position: right 0.5rem center; background-size: 1.25rem;"
)


def _apply_field_class(form):
    for field in form.fields.values():
        widget = field.widget
        widget.attrs.setdefault('class', FIELD_CLASS)
        if isinstance(widget, forms.Select) and not isinstance(widget, forms.SelectMultiple):
            widget.attrs['class'] = widget.attrs['class'] + SELECT_EXTRA_CLASS
            widget.attrs.setdefault('style', SELECT_CHEVRON_STYLE)


class ServiceForm(forms.ModelForm):
    class Meta:
        model = Service
        fields = ('name', 'category', 'description', 'price', 'is_active', 'show_on_website')
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_field_class(self)
        self.fields['category'].empty_label = '— Без категорії —'


class ServiceComponentForm(forms.ModelForm):
    class Meta:
        model = ServiceComponent
        fields = ('product', 'quantity')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_field_class(self)
        self.fields['product'].queryset = self.fields['product'].queryset.filter(is_active=True)
        self.fields['product'].empty_label = '— Товар —'


ComponentFormSet = inlineformset_factory(
    Service, ServiceComponent,
    form=ServiceComponentForm,
    extra=1,
    can_delete=True,
)
