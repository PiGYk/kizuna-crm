from django import forms
from .models import ExpenseCategory, Supplier, Expense, CashOperation


_tw = 'w-full rounded-lg border-gray-300 bg-white px-3 py-2 text-sm focus:ring-brand-gold focus:border-brand-gold'
_tw_select = _tw


class ExpenseCategoryForm(forms.ModelForm):
    class Meta:
        model = ExpenseCategory
        fields = ('name', 'icon')
        widgets = {
            'name': forms.TextInput(attrs={'class': _tw, 'placeholder': 'Назва категорії'}),
            'icon': forms.TextInput(attrs={'class': 'w-20 rounded-lg border-gray-300 bg-white px-3 py-2 text-sm text-center', 'placeholder': '📦'}),
        }


class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ('name', 'contact_person', 'phone', 'email', 'notes')
        widgets = {
            'name': forms.TextInput(attrs={'class': _tw}),
            'contact_person': forms.TextInput(attrs={'class': _tw}),
            'phone': forms.TextInput(attrs={'class': _tw}),
            'email': forms.EmailInput(attrs={'class': _tw}),
            'notes': forms.Textarea(attrs={'class': _tw, 'rows': 3}),
        }


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = ('category', 'supplier', 'amount', 'date', 'payment_method',
                  'description', 'receipt_photo')
        widgets = {
            'category': forms.Select(attrs={'class': _tw_select}),
            'supplier': forms.Select(attrs={'class': _tw_select}),
            'amount': forms.NumberInput(attrs={'class': _tw, 'step': '0.01', 'min': '0.01'}),
            'date': forms.DateInput(attrs={'class': _tw, 'type': 'date'}),
            'payment_method': forms.Select(attrs={'class': _tw_select}),
            'description': forms.TextInput(attrs={'class': _tw}),
            'receipt_photo': forms.ClearableFileInput(attrs={'class': _tw}),
        }


class CashOperationForm(forms.ModelForm):
    class Meta:
        model = CashOperation
        fields = ('type', 'amount', 'date', 'description')
        widgets = {
            'type': forms.Select(attrs={'class': _tw_select}),
            'amount': forms.NumberInput(attrs={'class': _tw, 'step': '0.01', 'min': '0.01'}),
            'date': forms.DateInput(attrs={'class': _tw, 'type': 'date'}),
            'description': forms.TextInput(attrs={'class': _tw, 'placeholder': 'Коментар (необов\'язково)'}),
        }
