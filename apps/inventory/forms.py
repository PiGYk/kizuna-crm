from django import forms
from .models import Category, Product, StockMovement, Unit
from apps.finance.models import Supplier

FIELD_CLASS = (
    'w-full px-4 py-2.5 border border-gray-300 rounded-lg text-sm '
    'focus:outline-none focus:ring-2 focus:ring-brand-gold focus:border-transparent'
)


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ('name', 'sku', 'category', 'unit', 'buy_price', 'sell_price', 'min_quantity', 'notes', 'is_active', 'expiry_date')
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, org=None, **kwargs):
        super().__init__(*args, **kwargs)
        if org:
            from django.db.models import Q
            self.fields['unit'].queryset = Unit.objects.filter(
                Q(organization__isnull=True) | Q(organization=org)
            ).order_by('name')
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', FIELD_CLASS)


class StockInForm(forms.ModelForm):
    """Прихід товару."""
    class Meta:
        model = StockMovement
        fields = ('quantity', 'price', 'supplier', 'reason')
        labels = {
            'quantity': 'Кількість',
            'price': 'Вхідна ціна за од.',
            'supplier': 'Постачальник',
            'reason': 'Нотатки',
        }

    def __init__(self, *args, suppliers_qs=None, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', FIELD_CLASS)
        self.fields['reason'].required = False
        self.fields['price'].required = False
        self.fields['supplier'].required = False
        if suppliers_qs is not None:
            self.fields['supplier'].queryset = suppliers_qs
        else:
            self.fields['supplier'].queryset = Supplier.objects.none()
        self.fields['supplier'].empty_label = '— Обрати постачальника —'


class StockAdjustForm(forms.ModelForm):
    """Коригування залишку."""
    class Meta:
        model = StockMovement
        fields = ('quantity', 'reason')
        labels = {
            'quantity': 'Новий залишок',
            'reason': 'Причина',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', FIELD_CLASS)
        self.fields['reason'].required = False


class ImportForm(forms.Form):
    file = forms.FileField(
        label='Файл CSV або Excel (.xlsx)',
        widget=forms.FileInput(attrs={'accept': '.csv,.xlsx', 'class': FIELD_CLASS}),
    )
