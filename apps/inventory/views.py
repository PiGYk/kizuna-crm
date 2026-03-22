import csv
import io

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q, Sum, ExpressionWrapper, DecimalField, F
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import ListView, CreateView, UpdateView, DetailView
from django.urls import reverse_lazy, reverse

from .forms import ProductForm, StockInForm, StockAdjustForm, ImportForm
from .models import Category, Product, StockMovement, Unit


class ProductListView(LoginRequiredMixin, ListView):
    model = Product
    template_name = 'inventory/list.html'
    context_object_name = 'products'
    paginate_by = 50

    def get_queryset(self):
        qs = Product.objects.select_related('unit', 'category').filter(is_active=True)
        q = self.request.GET.get('q', '').strip()
        stock = self.request.GET.get('stock', '')
        cat = self.request.GET.get('cat', '')
        if q:
            qs = qs.filter(name__icontains=q)
        if cat:
            qs = qs.filter(category_id=cat)
        if stock == 'low':
            qs = [p for p in qs if p.is_low_stock()]
        elif stock == 'out':
            qs = [p for p in qs if p.is_out_of_stock()]
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['q'] = self.request.GET.get('q', '')
        ctx['stock'] = self.request.GET.get('stock', '')
        ctx['cat'] = self.request.GET.get('cat', '')
        ctx['categories'] = Category.objects.all()

        # суми по всьому складу (незалежно від поточних фільтрів)
        money_field = DecimalField(max_digits=14, decimal_places=2)
        totals = Product.objects.filter(is_active=True).aggregate(
            total_buy=Sum(
                ExpressionWrapper(F('quantity') * F('buy_price'), output_field=money_field)
            ),
            total_sell=Sum(
                ExpressionWrapper(F('quantity') * F('sell_price'), output_field=money_field)
            ),
        )
        ctx['total_buy'] = totals['total_buy'] or 0
        ctx['total_sell'] = totals['total_sell'] or 0
        return ctx


class ProductCreateView(LoginRequiredMixin, CreateView):
    model = Product
    form_class = ProductForm
    template_name = 'inventory/form.html'

    def get_success_url(self):
        return reverse('inventory:detail', kwargs={'pk': self.object.pk})

    def form_valid(self, form):
        messages.success(self.request, 'Товар додано')
        return super().form_valid(form)


class ProductUpdateView(LoginRequiredMixin, UpdateView):
    model = Product
    form_class = ProductForm
    template_name = 'inventory/form.html'

    def get_success_url(self):
        return reverse('inventory:detail', kwargs={'pk': self.object.pk})

    def form_valid(self, form):
        messages.success(self.request, 'Збережено')
        return super().form_valid(form)


class ProductDetailView(LoginRequiredMixin, DetailView):
    model = Product
    template_name = 'inventory/detail.html'
    context_object_name = 'product'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['movements'] = self.object.movements.select_related('created_by').all()[:30]
        ctx['in_form'] = StockInForm()
        ctx['adjust_form'] = StockAdjustForm()
        return ctx


@login_required
def stock_in(request, pk):
    product = get_object_or_404(Product, pk=pk)
    form = StockInForm(request.POST)
    if form.is_valid():
        mv = form.save(commit=False)
        mv.product = product
        mv.type = StockMovement.Type.IN
        mv.created_by = request.user
        if form.cleaned_data.get('price'):
            product.buy_price = form.cleaned_data['price']
            product.save(update_fields=['buy_price'])
        mv.save()
        messages.success(request, f'Прихід {mv.quantity} {product.unit} записано')
    return redirect('inventory:detail', pk=pk)


@login_required
def stock_adjust(request, pk):
    product = get_object_or_404(Product, pk=pk)
    form = StockAdjustForm(request.POST)
    if form.is_valid():
        mv = form.save(commit=False)
        mv.product = product
        mv.type = StockMovement.Type.ADJUST
        mv.created_by = request.user
        mv.save()
        messages.success(request, f'Залишок скориговано до {product.quantity} {product.unit}')
    return redirect('inventory:detail', pk=pk)


@login_required
def import_products(request):
    if request.method == 'POST':
        form = ImportForm(request.POST, request.FILES)
        if form.is_valid():
            f = request.FILES['file']
            name = f.name.lower()
            rows, errors = [], []

            if name.endswith('.csv'):
                text = f.read().decode('utf-8-sig')
                reader = csv.DictReader(io.StringIO(text))
                rows = list(reader)
            elif name.endswith('.xlsx'):
                import openpyxl
                wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
                ws = wb.active
                headers = [str(c.value).strip() if c.value else '' for c in next(ws.iter_rows(min_row=1, max_row=1))]
                for row in ws.iter_rows(min_row=2, values_only=True):
                    rows.append(dict(zip(headers, row)))

            # очікувані колонки: назва, одиниця, вхідна_ціна, вихідна_ціна, залишок
            created, updated = 0, 0
            for i, row in enumerate(rows, start=2):
                try:
                    name_val = str(row.get('назва') or row.get('name') or '').strip()
                    if not name_val:
                        continue
                    unit_short = str(row.get('одиниця') or row.get('unit') or 'шт').strip()
                    unit, _ = Unit.objects.get_or_create(
                        short__iexact=unit_short,
                        defaults={'name': unit_short, 'short': unit_short}
                    )
                    buy = float(row.get('вхідна_ціна') or row.get('buy_price') or 0)
                    sell = float(row.get('вихідна_ціна') or row.get('sell_price') or 0)
                    qty = float(row.get('залишок') or row.get('quantity') or 0)

                    cat_name = str(row.get('категорія') or row.get('category') or '').strip()
                    category = None
                    if cat_name:
                        category, _ = Category.objects.get_or_create(name=cat_name)

                    product, is_new = Product.objects.get_or_create(
                        name=name_val,
                        defaults={'unit': unit, 'buy_price': buy, 'sell_price': sell,
                                  'quantity': qty, 'category': category}
                    )
                    if not is_new:
                        product.buy_price = buy
                        product.sell_price = sell
                        product.unit = unit
                        if category:
                            product.category = category
                        product.save(update_fields=['buy_price', 'sell_price', 'unit', 'category'])
                        updated += 1
                    else:
                        created += 1
                except Exception as e:
                    errors.append(f'Рядок {i}: {e}')

            msg = f'Імпортовано: {created} нових, {updated} оновлено.'
            if errors:
                msg += f' Помилки: {"; ".join(errors[:3])}'
                messages.warning(request, msg)
            else:
                messages.success(request, msg)
            return redirect('inventory:list')
    else:
        form = ImportForm()
    return render(request, 'inventory/import.html', {'form': form})


@login_required
def export_template(request):
    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = 'attachment; filename="import_template.csv"'
    writer = csv.writer(response)
    writer.writerow(['назва', 'категорія', 'одиниця', 'вхідна_ціна', 'вихідна_ціна', 'залишок'])
    writer.writerow(['Приклад препарату', 'Вакцини', 'мл', '50.00', '120.00', '100'])
    return response
