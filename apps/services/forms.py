from django import forms
from django.forms import inlineformset_factory
from .models import Service, ServiceCategory, ServiceComponent

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


CHECKBOX_CLASS = 'w-4 h-4 shrink-0 accent-brand-gold cursor-pointer'


def _apply_field_class(form):
    for field in form.fields.values():
        widget = field.widget
        if isinstance(widget, forms.HiddenInput):
            continue
        # Галочці клас текстового поля не годиться: `w-full` розтягував її
        # на всю ширину рядка і вона з'їжджала на середину.
        if isinstance(widget, forms.CheckboxInput):
            widget.attrs.setdefault('class', CHECKBOX_CLASS)
            continue
        widget.attrs.setdefault('class', FIELD_CLASS)
        if isinstance(widget, forms.Select) and not isinstance(widget, forms.SelectMultiple):
            widget.attrs['class'] = widget.attrs['class'] + SELECT_EXTRA_CLASS
            widget.attrs.setdefault('style', SELECT_CHEVRON_STYLE)


class ServiceForm(forms.ModelForm):
    # Категорію можна завести прямо звідси: окремої сторінки категорій немає,
    # а гнати заради однієї назви цілий файл імпорту — знущання (прохання
    # Ірпеня 22.08).
    new_category = forms.CharField(
        label='Нова категорія',
        required=False,
        max_length=100,
        widget=forms.TextInput(attrs={'placeholder': 'Наприклад: Стоматологія'}),
    )

    class Meta:
        model = Service
        fields = ('code', 'name', 'category', 'description', 'price', 'is_active', 'show_on_website')
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'code': forms.TextInput(attrs={'placeholder': 'з прайсу, необов\'язково'}),
        }

    def __init__(self, *args, org=None, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_field_class(self)
        self.org = org
        # Списки ЗАВЖДИ будуємо тут, а не покладаємось на менеджер моделі.
        # Django рахує queryset поля один раз — коли імпортується цей модуль,
        # а тоді контексту клініки ще немає: OrgManager fail-closed віддає
        # порожньо, і ця порожнеча лишається у формі до кінця життя процесу.
        # Спіймано 22.08: в Ірпеня категорії й товари не підтягувались зовсім,
        # а на «прогрітому» процесі — падали чужі, з іншої клініки.
        if org is not None:
            self.fields['category'].queryset = ServiceCategory._base_manager.filter(
                organization=org,
            ).order_by('sort_order', 'name')
        else:
            self.fields['category'].queryset = ServiceCategory._base_manager.none()
        self.fields['category'].empty_label = '— Без категорії —'

    def clean_new_category(self):
        title = (self.cleaned_data.get('new_category') or '').strip()
        if title and self.org is None:
            raise forms.ValidationError('Не вдалося визначити клініку — оновіть сторінку.')
        return title

    def save(self, commit=True):
        service = super().save(commit=False)
        title = (self.cleaned_data.get('new_category') or '').strip()
        if title and self.org is not None:
            category = ServiceCategory._base_manager.filter(
                organization=self.org, name__iexact=title,
            ).first()
            if category is None:
                category = ServiceCategory._base_manager.create(
                    organization=self.org, name=title,
                )
            service.category = category
        if commit:
            service.save()
            self.save_m2m()
        return service


class ServiceComponentForm(forms.ModelForm):
    # Текстова назва товару для JS-поля comp-name. Без цього поля при POST
    # з помилками comp-name стає порожнім (f.instance.pk=None для нових рядків),
    # хоча hidden product може мати правильне значення — товар невидимий у формі.
    product_name = forms.CharField(
        widget=forms.HiddenInput(),
        required=False,
        label='',
    )

    class Meta:
        model = ServiceComponent
        fields = ('product', 'quantity')
        widgets = {
            # Товар обирається пошуком (розмітка у services/form.html): у складі
            # клініки бувають сотні позицій — гортати їх випадайкою неможливо.
            'product': forms.HiddenInput(),
        }

    def __init__(self, *args, org=None, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_field_class(self)
        from apps.inventory.models import Product
        # Той самий фікс, що й у ServiceForm вище. Заразом це і захист: зберегти
        # можна лише товар СВОЄЇ клініки — чужий номер форма відкине.
        if org is not None:
            self.fields['product'].queryset = Product._base_manager.filter(
                organization=org, is_active=True,
            ).order_by('name')
        else:
            self.fields['product'].queryset = Product._base_manager.none()
        # Для існуючого компонента заповнюємо product_name з instance — щоб
        # при GET і при ре-рендері після POST, comp-name завжди показував назву.
        if self.instance.pk and self.instance.product_id:
            try:
                self.initial.setdefault('product_name', self.instance.product.name)
            except Exception:
                pass

    def clean_quantity(self):
        from decimal import Decimal
        qty = self.cleaned_data.get('quantity')
        if qty is not None and qty <= Decimal('0'):
            raise forms.ValidationError('Кількість має бути більше 0.')
        return qty


ComponentFormSet = inlineformset_factory(
    Service, ServiceComponent,
    form=ServiceComponentForm,
    extra=1,
    can_delete=True,
)
