import csv
import io
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Q, Sum, ExpressionWrapper, DecimalField, F, OuterRef, Subquery
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.generic import ListView, CreateView, UpdateView, DetailView
from django.urls import reverse_lazy, reverse

from .forms import ProductForm, StockInForm, StockAdjustForm, ImportForm
from .models import Category, Product, StockMovement, Unit
from apps.finance.models import Supplier
from apps.tg.utils import is_mobile


class ProductListView(LoginRequiredMixin, ListView):
    model = Product
    template_name = 'inventory/list.html'

    def get_template_names(self):
        if is_mobile(self.request):
            return ['inventory/list_mobile.html']
        return [self.template_name]
    context_object_name = 'products'
    paginate_by = 50

    PER_PAGE_CHOICES = (50, 100, 200)

    def get_paginate_by(self, queryset):
        try:
            value = int(self.request.GET.get('per_page', self.paginate_by))
        except (TypeError, ValueError):
            return self.paginate_by
        return value if value in self.PER_PAGE_CHOICES else self.paginate_by

    SORT_FIELDS = {
        'name': 'name',
        'category': 'category__name',
        'quantity': 'quantity',
        'buy_price': 'buy_price',
        'sell_price': 'sell_price',
        'unit': 'unit__short',
    }

    def get_queryset(self):
        qs = Product.objects.select_related('unit', 'category').filter(
            is_active=True,
            organization=self.request.organization,
        )
        q = self.request.GET.get('q', '').strip()
        stock = self.request.GET.get('stock', '')
        cat = self.request.GET.get('cat', '')
        expiry = self.request.GET.get('expiry', '')
        if q:
            qs = qs.filter(name__icontains=q)
        if cat:
            qs = qs.filter(category_id=cat)

        # сортування
        sort = self.request.GET.get('sort', 'name')
        direction = self.request.GET.get('dir', 'asc')
        db_field = self.SORT_FIELDS.get(sort, 'name')
        if direction == 'desc':
            db_field = '-' + db_field
        qs = qs.order_by(db_field)

        if stock == 'low':
            qs = qs.filter(min_quantity__gt=0, quantity__lte=F('min_quantity'))
        elif stock == 'out':
            qs = qs.filter(quantity__lte=0)
        elif expiry == 'expired':
            from datetime import date
            qs = qs.filter(expiry_date__lt=date.today())
        elif expiry == 'expiring':
            from datetime import date, timedelta
            today = date.today()
            qs = qs.filter(expiry_date__gte=today, expiry_date__lte=today + timedelta(days=30))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['q'] = self.request.GET.get('q', '')
        ctx['stock'] = self.request.GET.get('stock', '')
        ctx['cat'] = self.request.GET.get('cat', '')
        ctx['expiry'] = self.request.GET.get('expiry', '')
        ctx['sort'] = self.request.GET.get('sort', 'name')
        ctx['dir'] = self.request.GET.get('dir', 'asc')
        ctx['categories'] = Category.objects.filter(organization=self.request.organization)
        ctx['per_page'] = self.get_paginate_by(None)
        ctx['per_page_choices'] = self.PER_PAGE_CHOICES

        # суми по всьому складу (незалежно від поточних фільтрів) — лише для своєї org
        money_field = DecimalField(max_digits=14, decimal_places=2)
        totals = Product.objects.filter(
            is_active=True,
            organization=self.request.organization,
        ).aggregate(
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

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['org'] = self.request.organization
        return kwargs

    def get_success_url(self):
        return reverse('inventory:detail', kwargs={'pk': self.object.pk})

    def form_valid(self, form):
        form.instance.organization = self.request.organization
        messages.success(self.request, 'Товар додано')
        return super().form_valid(form)


class ProductUpdateView(LoginRequiredMixin, UpdateView):
    model = Product
    form_class = ProductForm
    template_name = 'inventory/form.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['org'] = self.request.organization
        return kwargs

    def get_success_url(self):
        return reverse('inventory:detail', kwargs={'pk': self.object.pk})

    def form_valid(self, form):
        messages.success(self.request, 'Збережено')
        return super().form_valid(form)


class ProductDetailView(LoginRequiredMixin, DetailView):
    model = Product
    template_name = 'inventory/detail.html'
    context_object_name = 'product'

    def get_template_names(self):
        if is_mobile(self.request):
            return ['inventory/detail_mobile.html']
        return [self.template_name]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        org = getattr(self.request, 'organization', None)
        suppliers_qs = Supplier.objects.filter(organization=org).order_by('name')
        ctx['movements'] = self.object.movements.select_related('created_by', 'supplier').all()[:30]
        ctx['in_form'] = StockInForm(suppliers_qs=suppliers_qs)
        ctx['adjust_form'] = StockAdjustForm()
        return ctx


@login_required
def stock_in(request, pk):
    product = get_object_or_404(Product, pk=pk, organization=request.organization)
    org = getattr(request, 'organization', None)
    suppliers_qs = Supplier.objects.filter(organization=org).order_by('name')
    form = StockInForm(request.POST, suppliers_qs=suppliers_qs)
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
    next_url = request.POST.get('next', '')
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)
    return redirect('inventory:detail', pk=pk)


@login_required
def stock_adjust(request, pk):
    product = get_object_or_404(Product, pk=pk, organization=request.organization)
    form = StockAdjustForm(request.POST)
    if form.is_valid():
        mv = form.save(commit=False)
        mv.product = product
        mv.type = StockMovement.Type.ADJUST
        mv.created_by = request.user
        mv.save()
        product.refresh_from_db()
        messages.success(request, f'Залишок скориговано до {product.quantity} {product.unit}')
    return redirect('inventory:detail', pk=pk)


def _parse_file(f):
    """Парсить CSV/XLSX файл, повертає (headers, rows)."""
    name = f.name.lower()
    if name.endswith('.csv'):
        text = f.read().decode('utf-8-sig')
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
        headers = reader.fieldnames or []
    elif name.endswith(('.xlsx', '.xls')):
        import openpyxl
        f.seek(0)
        wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
        ws = wb.active
        headers = [str(c.value).strip() if c.value else f'col_{i}' for i, c in enumerate(next(ws.iter_rows(min_row=1, max_row=1)))]
        rows = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            rows.append(dict(zip(headers, row)))
    else:
        headers, rows = [], []
    return headers, rows


# Автоматичний маппінг колонок файлу → полів системи
_AUTO_MAP = {
    'name': ['назва', 'name', 'наименование', 'найменування', 'товар', 'product', 'назва товару'],
    'sku': ['sku', 'артикул', 'код', 'code', 'article', 'арт', 'арт.'],
    'category': ['категорія', 'category', 'группа', 'група', 'тип'],
    'unit': ['одиниця', 'unit', 'од.', 'од', 'одиниця виміру', 'единица'],
    'buy_price': ['вхідна_ціна', 'вхідна ціна', 'buy_price', 'закупка', 'вхідна', 'ціна закупки', 'цена закупки', 'purchase_price'],
    'sell_price': ['вихідна_ціна', 'вихідна ціна', 'sell_price', 'продаж', 'вихідна', 'ціна продажу', 'цена продажи', 'price', 'ціна'],
    'quantity': ['залишок', 'quantity', 'кількість', 'к-ть', 'qty', 'количество', 'кіл-ть', 'stock'],
    'min_quantity': ['мін_залишок', 'мін. залишок', 'min_quantity', 'мінімум', 'min_stock'],
    'notes': ['нотатки', 'notes', 'примітки', 'коментар', 'comment'],
}

IMPORT_FIELDS = [
    ('name', 'Назва *'),
    ('sku', 'Артикул (SKU)'),
    ('category', 'Категорія'),
    ('unit', 'Одиниця'),
    ('buy_price', 'Вхідна ціна'),
    ('sell_price', 'Вихідна ціна'),
    ('quantity', 'Залишок'),
    ('min_quantity', 'Мін. залишок'),
    ('notes', 'Нотатки'),
]


def _auto_match(file_headers):
    """Повертає dict: field_key → matched file header або ''."""
    mapping = {}
    used = set()
    for field_key, aliases in _AUTO_MAP.items():
        for h in file_headers:
            h_lower = h.strip().lower()
            if h_lower in aliases and h not in used:
                mapping[field_key] = h
                used.add(h)
                break
    return mapping


@login_required
def import_upload(request):
    """Крок 1: завантаження файлу, парсинг, показ маппінгу."""
    if request.method == 'POST' and request.FILES.get('file'):
        f = request.FILES['file']
        headers, rows = _parse_file(f)
        if not headers:
            messages.error(request, 'Не вдалося прочитати файл. Підтримуються CSV, XLSX.')
            return redirect('inventory:import')

        auto_map = _auto_match(headers)

        # зберігаємо файл у сесії (як рядки) для другого кроку
        request.session['import_headers'] = headers
        request.session['import_rows'] = rows
        request.session['import_filename'] = f.name

        # Для preview — конвертуємо dict-и в списки значень по headers
        preview = []
        for row in rows[:5]:
            preview.append([row.get(h, '') for h in headers])

        return render(request, 'inventory/import_mapping.html', {
            'headers': headers,
            'fields': IMPORT_FIELDS,
            'auto_map': auto_map,
            'preview': preview,
            'total_rows': len(rows),
            'filename': f.name,
        })

    return render(request, 'inventory/import.html')


@login_required
@transaction.atomic
def import_execute(request):
    """Крок 2: виконання імпорту з маппінгом від юзера."""
    if request.method != 'POST':
        return redirect('inventory:import')

    rows = request.session.get('import_rows', [])
    if not rows:
        messages.error(request, 'Немає даних для імпорту. Завантажте файл ще раз.')
        return redirect('inventory:import')

    # Читаємо маппінг: field_key → file column header
    mapping = {}
    for field_key, _ in IMPORT_FIELDS:
        col = request.POST.get(f'map_{field_key}', '').strip()
        if col and col != '__skip__':
            mapping[field_key] = col

    if 'name' not in mapping:
        messages.error(request, 'Поле "Назва" обов\'язкове для маппінгу.')
        return redirect('inventory:import')

    org = request.organization

    def _get(row, key):
        col = mapping.get(key)
        if not col:
            return ''
        val = row.get(col)
        if val is None:
            return ''
        return str(val).strip()

    created, updated, errors = 0, 0, []
    # IDs товарів, які потребують перегляду вихідної ціни:
    # нові товари + існуючі зі зміненою вхідною ціною
    review_ids = []

    # Pre-cache units/categories/existing products — економить ~5-6 queries per row.
    units_cache = {}  # short.lower() -> Unit
    for u in Unit.objects.filter(Q(organization__isnull=True) | Q(organization=org)):
        units_cache.setdefault(u.short.lower(), u)
    categories_cache = {c.name.lower(): c for c in Category.objects.filter(organization=org)}
    products_by_sku = {
        p.sku.lower(): p for p in Product.objects.filter(organization=org).exclude(sku='')
    }
    products_by_name = {
        p.name.lower(): p for p in Product.objects.filter(organization=org)
    }

    for i, row in enumerate(rows, start=2):
        try:
            name_val = _get(row, 'name')
            if not name_val:
                continue

            sku_val = _get(row, 'sku')

            # Пошук існуючого товару у pre-cache
            product = None
            if sku_val:
                product = products_by_sku.get(sku_val.lower())
            if not product:
                product = products_by_name.get(name_val.lower())

            # Одиниця виміру з кешу або створюємо
            unit_short = _get(row, 'unit') or 'шт'
            unit = units_cache.get(unit_short.lower())
            if not unit:
                unit = Unit.objects.create(name=unit_short, short=unit_short, organization=org)
                units_cache[unit_short.lower()] = unit

            # Категорія з кешу або створюємо
            cat_name = _get(row, 'category')
            category = None
            if cat_name:
                category = categories_cache.get(cat_name.lower())
                if not category:
                    category = Category.objects.create(name=cat_name, organization=org)
                    categories_cache[cat_name.lower()] = category

            # Числа (Decimal — не float, щоб не втрачати копійки)
            def _dec(v):
                try:
                    return Decimal(str(v).replace(',', '.')) if v not in (None, '') else Decimal('0')
                except Exception:
                    return Decimal('0')

            buy = _dec(_get(row, 'buy_price'))
            sell = _dec(_get(row, 'sell_price'))
            qty = _dec(_get(row, 'quantity'))
            min_qty = _dec(_get(row, 'min_quantity'))
            notes_val = _get(row, 'notes')

            if product:
                # Визначаємо чи змінилась вхідна ціна
                buy_changed = bool(buy) and abs(product.buy_price - buy) > Decimal('0.001')

                product.name = name_val
                if sku_val:
                    product.sku = sku_val
                product.unit = unit
                if category:
                    product.category = category
                if buy:
                    product.buy_price = buy
                if sell:
                    product.sell_price = sell
                if min_qty:
                    product.min_quantity = min_qty
                if notes_val:
                    product.notes = notes_val
                product.save()
                updated += 1

                if buy_changed:
                    review_ids.append(product.pk)
            else:
                # Створюємо новий
                new_product = Product.objects.create(
                    name=name_val,
                    sku=sku_val,
                    unit=unit,
                    category=category,
                    buy_price=buy,
                    sell_price=sell,
                    quantity=qty,
                    min_quantity=min_qty,
                    notes=notes_val,
                    organization=request.organization,
                )
                created += 1
                # Новий товар завжди потрапляє на перегляд (позначаємо префіксом 'n:')
                review_ids.append(f'n:{new_product.pk}')
        except Exception as e:
            errors.append(f'Рядок {i}: {e}')

    # Чистимо сесію від даних файлу
    for key in ('import_headers', 'import_rows', 'import_filename'):
        request.session.pop(key, None)

    msg = f'Імпорт завершено: {created} створено, {updated} оновлено.'
    if errors:
        msg += f' Помилки ({len(errors)}): {"; ".join(errors[:5])}'
        messages.warning(request, msg)
    else:
        messages.success(request, msg)

    # Якщо є товари для перегляду — переходимо на сторінку встановлення цін
    if review_ids:
        request.session['price_review_ids'] = review_ids
        return redirect('inventory:price_review')

    return redirect('inventory:list')


@login_required
def price_review(request):
    """Перегляд і встановлення вихідних цін після імпорту."""
    raw_ids = request.session.get('price_review_ids', [])
    if not raw_ids:
        messages.info(request, 'Немає товарів для перегляду цін.')
        return redirect('inventory:list')

    # Розбиваємо на нові (n:pk) і ті зі зміненою ціною (pk)
    new_pks = set()
    changed_pks = set()
    for entry in raw_ids:
        s = str(entry)
        if s.startswith('n:'):
            new_pks.add(int(s[2:]))
        else:
            changed_pks.add(int(s))

    all_pks = new_pks | changed_pks
    products = Product.objects.filter(pk__in=all_pks).select_related('category', 'unit').order_by('name')

    if request.method == 'POST':
        updated_count = 0
        for product in products:
            raw = request.POST.get(f'sell_{product.pk}', '').strip()
            if raw:
                try:
                    new_price = float(raw)
                    if abs(new_price - float(product.sell_price)) > 0.001:
                        product.sell_price = new_price
                        product.save(update_fields=['sell_price'])
                        updated_count += 1
                except ValueError:
                    pass
        request.session.pop('price_review_ids', None)
        messages.success(request, f'Вихідні ціни оновлено для {updated_count} товар(ів).')
        return redirect('inventory:list')

    return render(request, 'inventory/price_review.html', {
        'products': products,
        'new_pks': new_pks,
        'total': len(all_pks),
    })


@login_required
def product_delete(request, pk):
    from django.db.models import ProtectedError
    if not request.user.is_admin():
        messages.error(request, 'Видаляти товари може лише адміністратор')
        return redirect('inventory:detail', pk=pk)
    product = get_object_or_404(Product, pk=pk)
    if request.method == 'POST':
        try:
            product.delete()
            messages.success(request, f'Товар «{product.name}» видалено')
            next_url = request.POST.get('next')
            if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
                return redirect(next_url)
            return redirect('inventory:list')
        except ProtectedError:
            services = product.servicecomponent_set.select_related('service').values_list('service__name', flat=True)
            names = ', '.join(services)
            messages.error(request, f'Не можна видалити — товар використовується в послугах: {names}')
            return redirect('inventory:detail', pk=pk)
    return redirect('inventory:detail', pk=pk)


@login_required
def product_bulk_delete(request):
    from django.db.models import ProtectedError
    if request.method != 'POST':
        return redirect('inventory:list')
    if not request.user.is_admin():
        messages.error(request, 'Видаляти товари може лише адміністратор')
        return redirect('inventory:list')

    ids = request.POST.getlist('ids')
    if not ids:
        messages.warning(request, 'Не вибрано жодного товару')
        return redirect('inventory:list')

    products = Product.objects.filter(pk__in=ids)
    deleted = 0
    protected = []
    for product in products:
        try:
            name = product.name
            product.delete()
            deleted += 1
        except ProtectedError:
            protected.append(product.name)

    if deleted:
        messages.success(request, f'Видалено товар(ів): {deleted}')
    if protected:
        preview = ', '.join(protected[:5])
        extra = f' та ще {len(protected) - 5}' if len(protected) > 5 else ''
        messages.error(
            request,
            f'Не вдалось видалити (використовуються в послугах): {preview}{extra}'
        )

    next_url = request.POST.get('next')
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)
    return redirect('inventory:list')


@login_required
def reorder_view(request):
    # Subquery: ім'я останнього постачальника для кожного товару
    last_supplier_name = Subquery(
        StockMovement.objects.filter(
            product=OuterRef('pk'),
            type=StockMovement.Type.IN,
            supplier__isnull=False,
        ).order_by('-created_at').values('supplier__name')[:1]
    )

    products = Product.objects.filter(
        is_active=True,
        min_quantity__gt=0,
    ).select_related('unit', 'category').annotate(
        last_supplier_name=last_supplier_name,
    ).order_by('name')

    low = [p for p in products if p.quantity <= p.min_quantity]

    for p in low:
        p.shortage = max(float(p.min_quantity) - float(p.quantity), 0)

    template = 'inventory/reorder_mobile.html' if is_mobile(request) else 'inventory/reorder.html'
    return render(request, template, {
        'products': low,
        'count': len(low),
    })


@login_required
def reorder_export(request):
    """Експорт замовлення в XLSX."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    from django.utils import timezone

    products = Product.objects.filter(
        is_active=True,
        min_quantity__gt=0,
    ).select_related('unit', 'category').order_by('name')
    low = [p for p in products if p.quantity <= p.min_quantity]

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Замовлення'

    header_fill = PatternFill(start_color='DEAA01', end_color='DEAA01', fill_type='solid')
    bold = Font(bold=True)

    headers = ['Назва', 'Категорія', 'Артикул', 'Од. виміру', 'На складі',
               'Мін. залишок', 'Потрібно замовити', 'Вхідна ціна', 'Нотатки']
    ws.append(headers)
    for col_num, _ in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_num)
        cell.font = bold
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center')

    for p in low:
        shortage = max(float(p.min_quantity) - float(p.quantity), 0)
        ws.append([
            p.name,
            p.category.name if p.category else '',
            p.sku,
            p.unit.short if p.unit else '',
            float(p.quantity),
            float(p.min_quantity),
            shortage,
            float(p.buy_price),
            p.notes,
        ])

    for col in ws.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 40)

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    today = timezone.localdate().strftime('%Y-%m-%d')
    response['Content-Disposition'] = f'attachment; filename="reorder-{today}.xlsx"'
    wb.save(response)
    return response


@login_required
def export_template(request):
    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = 'attachment; filename="import_template.csv"'
    writer = csv.writer(response)
    writer.writerow(['назва', 'артикул', 'категорія', 'одиниця', 'вхідна_ціна', 'вихідна_ціна', 'залишок', 'мін_залишок', 'нотатки'])
    writer.writerow(['Приклад препарату', 'SKU001', 'Вакцини', 'мл', '50.00', '120.00', '100', '10', ''])
    writer.writerow(['Новий товар без SKU', '', 'Препарати', 'шт', '200.00', '350.00', '50', '5', 'Зберігати в холоді'])
    return response


# ── Налаштування: категорії та одиниці ───────────────────────────────────────

@login_required
def inventory_settings(request):
    return render(request, 'inventory/settings.html', {
        'categories': Category.objects.annotate_product_count() if hasattr(Category, 'annotate_product_count') else _categories_with_count(),
        'units': _units_with_count(org=request.organization),
    })


def _categories_with_count():
    from django.db.models import Count
    return Category.objects.annotate(product_count=Count('products')).order_by('name')


def _units_with_count(org=None):
    from django.db.models import Count
    qs = Unit.objects.filter(
        Q(organization__isnull=True) | Q(organization=org)
    ).annotate(product_count=Count('product')).order_by('name')
    return qs


@login_required
def category_create(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if name:
            Category.objects.get_or_create(name=name, defaults={'organization': request.organization})
    return redirect('inventory:settings')


@login_required
def category_delete(request, pk):
    if request.method == 'POST':
        cat = get_object_or_404(Category, pk=pk)
        count = Product.objects.filter(category=cat).count()
        cat.delete()
        if count:
            messages.warning(request, f'Категорію видалено. {count} товарів залишились без категорії.')
        else:
            messages.success(request, 'Категорію видалено.')
    return redirect('inventory:settings')


@login_required
def unit_create(request):
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        short = request.POST.get('short', '').strip()
        if name and short:
            org = request.organization
            # Перевірити чи немає глобальної з такою назвою
            if not Unit.objects.filter(name=name, organization__isnull=True).exists():
                Unit.objects.get_or_create(
                    name=name, organization=org,
                    defaults={'short': short},
                )
            else:
                messages.info(request, f'Одиниця «{name}» вже існує як стандартна.')
    return redirect('inventory:settings')


@login_required
def unit_delete(request, pk):
    if request.method == 'POST':
        unit = get_object_or_404(Unit, pk=pk)
        if unit.organization is None:
            messages.error(request, f'Одиницю «{unit.short}» не можна видалити — вона стандартна.')
        else:
            try:
                unit.delete()
                messages.success(request, f'Одиницю «{unit.short}» видалено.')
            except Exception:
                messages.error(request, f'Одиницю «{unit.short}» не можна видалити — вона використовується в товарах.')
    return redirect('inventory:settings')


# ── Експорт складу ────────────────────────────────────────────────────────────

@login_required
def export_page(request):
    """Сторінка з параметрами експорту."""
    return render(request, 'inventory/export.html', {
        'categories': Category.objects.filter(organization=request.organization),
    })


@login_required
def export_inventory(request):
    fmt = request.GET.get('fmt', 'xlsx')
    q = request.GET.get('q', '').strip()
    cat = request.GET.get('cat', '')
    stock = request.GET.get('stock', '')

    # Які колонки включити
    cols_param = request.GET.getlist('cols')
    all_columns = [
        ('name', 'Назва', lambda p: p.name),
        ('sku', 'Артикул (SKU)', lambda p: p.sku),
        ('category', 'Категорія', lambda p: p.category.name if p.category else ''),
        ('unit', 'Одиниця', lambda p: p.unit.short if p.unit else ''),
        ('quantity', 'Залишок', lambda p: float(p.quantity)),
        ('min_quantity', 'Мін. залишок', lambda p: float(p.min_quantity)),
        ('buy_price', 'Вхідна ціна', lambda p: float(p.buy_price)),
        ('sell_price', 'Вихідна ціна', lambda p: float(p.sell_price)),
        ('notes', 'Нотатки', lambda p: p.notes),
    ]
    if cols_param:
        columns = [(k, h, fn) for k, h, fn in all_columns if k in cols_param]
    else:
        columns = all_columns

    if not columns:
        columns = all_columns

    products = Product.objects.select_related('unit', 'category').filter(is_active=True)
    if q:
        products = products.filter(name__icontains=q)
    if cat:
        products = products.filter(category_id=cat)
    products = products.order_by('name')
    if stock == 'low':
        products = products.filter(min_quantity__gt=0, quantity__lte=F('min_quantity'))
    elif stock == 'out':
        products = products.filter(quantity__lte=0)

    headers = [h for _, h, _ in columns]

    if fmt == 'csv':
        response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
        response['Content-Disposition'] = 'attachment; filename="inventory.csv"'
        writer = csv.writer(response)
        writer.writerow(headers)
        for p in products:
            writer.writerow([fn(p) for _, _, fn in columns])
        return response

    # xlsx
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Склад'

    header_font = Font(bold=True, color='12100F')
    header_fill = PatternFill(fill_type='solid', fgColor='DEAA01')

    for col_idx, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center')

    has_qty = any(k == 'quantity' for k, _, _ in columns)
    for row_idx, p in enumerate(products, 2):
        for col_idx, (key, _, fn) in enumerate(columns, 1):
            cell = ws.cell(row=row_idx, column=col_idx, value=fn(p))
            if key in ('buy_price', 'sell_price'):
                cell.number_format = '#,##0.00'
            elif key == 'quantity':
                cell.number_format = '0.###'

        if has_qty:
            if p.is_out_of_stock():
                for c in range(1, len(columns) + 1):
                    ws.cell(row=row_idx, column=c).fill = PatternFill(fill_type='solid', fgColor='FEE2E2')
            elif p.is_low_stock():
                for c in range(1, len(columns) + 1):
                    ws.cell(row=row_idx, column=c).fill = PatternFill(fill_type='solid', fgColor='FEF9C3')

    # автоширина
    for col_idx in range(1, len(columns) + 1):
        max_len = len(str(ws.cell(row=1, column=col_idx).value))
        for row_idx in range(2, min(ws.max_row + 1, 52)):
            val = ws.cell(row=row_idx, column=col_idx).value
            if val:
                max_len = max(max_len, len(str(val)))
        ws.column_dimensions[get_column_letter(col_idx)].width = min(max_len + 4, 50)

    ws.freeze_panes = 'A2'

    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename="inventory.xlsx"'
    wb.save(response)
    return response


@login_required
@transaction.atomic
def batch_intake(request):
    """Масовий прихід товарів за накладною."""
    org = request.organization
    suppliers = Supplier.objects.filter(organization=org).order_by('name')

    if request.method == 'POST':
        supplier_id = request.POST.get('supplier_id')
        supplier = Supplier.objects.filter(pk=supplier_id, organization=org).first() if supplier_id else None
        note = request.POST.get('note', '').strip()

        product_ids = request.POST.getlist('product_id')
        quantities = request.POST.getlist('qty')
        prices = request.POST.getlist('price')
        sell_prices = request.POST.getlist('sell_price')

        created = 0
        for i, (pid, qty_str, price_str) in enumerate(zip(product_ids, quantities, prices)):
            if not pid or not qty_str:
                continue
            try:
                product = Product.objects.get(pk=pid, organization=org)
                qty = Decimal(qty_str)
                if qty <= 0:
                    continue
                price = Decimal(price_str) if price_str else None
                sell = Decimal(sell_prices[i]) if i < len(sell_prices) and sell_prices[i] else None

                StockMovement.objects.create(
                    product=product,
                    type=StockMovement.Type.IN,
                    quantity=qty,
                    price=price,
                    supplier=supplier,
                    reason=note or 'Масовий прихід',
                    created_by=request.user,
                )
                # Оновити ціни якщо передано
                update_fields = []
                if price and price > 0:
                    product.buy_price = price
                    update_fields.append('buy_price')
                if sell and sell > 0:
                    product.sell_price = sell
                    update_fields.append('sell_price')
                if update_fields:
                    product.save(update_fields=update_fields)
                created += 1
            except (Product.DoesNotExist, Exception):
                continue

        if created:
            messages.success(request, f'Прихід записано: {created} позицій.')
        else:
            messages.warning(request, 'Жоден рядок не було оброблено.')
        return redirect('inventory:batch_intake')

    return render(request, 'inventory/batch_intake.html', {
        'suppliers': suppliers,
    })


@login_required
def product_search_json(request):
    """JSON-пошук товарів для autocomplete."""
    q = request.GET.get('q', '').strip()
    org = request.organization
    qs = Product.objects.filter(organization=org, is_active=True).select_related('unit').order_by('name')
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(sku__icontains=q))
    qs = qs[:20]
    return JsonResponse({'results': [
        {
            'id': p.pk,
            'name': p.name,
            'sku': p.sku or '',
            'unit': p.unit.short if p.unit else '',
            'qty': str(p.quantity),
            'buy_price': str(p.buy_price),
            'sell_price': str(p.sell_price),
        }
        for p in qs
    ]})


@login_required
def movements_list(request):
    """Глобальна історія руху складу з фільтрами."""
    org = request.organization
    qs = StockMovement.objects.filter(
        product__organization=org
    ).select_related('product', 'product__unit', 'supplier', 'created_by').order_by('-created_at')

    # Фільтр по типу
    move_type = request.GET.get('type', '')
    if move_type in StockMovement.Type.values:
        qs = qs.filter(type=move_type)

    # Фільтр по товару (пошук)
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(product__name__icontains=q) | Q(reason__icontains=q))

    # Фільтр по даті
    date_from = request.GET.get('from', '')
    date_to = request.GET.get('to', '')
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)

    # Фільтр по постачальнику
    sup = request.GET.get('supplier', '')
    if sup:
        qs = qs.filter(supplier_id=sup)

    # Пагінація
    from django.core.paginator import Paginator
    paginator = Paginator(qs, 50)
    page = paginator.get_page(request.GET.get('page', 1))

    suppliers = Supplier.objects.filter(organization=org).order_by('name')

    return render(request, 'inventory/movements.html', {
        'movements': page,
        'move_type': move_type,
        'q': q,
        'date_from': date_from,
        'date_to': date_to,
        'supplier_filter': sup,
        'suppliers': suppliers,
        'type_choices': StockMovement.Type.choices,
    })


@login_required
@transaction.atomic
def stocktake(request):
    """Інвентаризація — звірка залишків."""
    org = request.organization
    products = Product.objects.filter(
        organization=org, is_active=True
    ).select_related('unit', 'category').order_by('category__name', 'name')

    if request.method == 'POST':
        adjusted = 0
        for product in products:
            key = f'actual_{product.pk}'
            val = request.POST.get(key, '').strip()
            if not val:
                continue
            try:
                actual = Decimal(val)
            except Exception:
                continue
            if actual != product.quantity:
                diff = actual - product.quantity
                StockMovement.objects.create(
                    product=product,
                    type=StockMovement.Type.ADJUST,
                    quantity=actual,
                    reason=f'Інвентаризація: було {product.quantity}, факт {actual} (різниця {diff:+})',
                    created_by=request.user,
                )
                adjusted += 1

        if adjusted:
            messages.success(request, f'Інвентаризація завершена: скориговано {adjusted} позицій.')
        else:
            messages.info(request, 'Розбіжностей не знайдено.')
        return redirect('inventory:list')

    template = 'inventory/stocktake_mobile.html' if is_mobile(request) else 'inventory/stocktake.html'
    return render(request, template, {
        'products': products,
    })


@login_required
def stock_writeoff(request, pk):
    """Списання товару з причиною."""
    product = get_object_or_404(Product, pk=pk, organization=request.organization)

    WRITEOFF_REASONS = [
        ('expired', 'Прострочений'),
        ('damaged', 'Бій / пошкодження'),
        ('internal', 'Внутрішнє використання'),
        ('return', 'Повернення постачальнику'),
        ('other', 'Інше'),
    ]

    if request.method == 'POST':
        try:
            qty = Decimal(request.POST.get('quantity', '0'))
        except Exception:
            messages.error(request, 'Невірна кількість.')
            return redirect('inventory:detail', pk=pk)

        if qty <= 0:
            messages.error(request, 'Кількість має бути більше 0.')
            return redirect('inventory:detail', pk=pk)

        reason_key = request.POST.get('reason', 'other')
        reason_label = dict(WRITEOFF_REASONS).get(reason_key, reason_key)
        custom_note = request.POST.get('note', '').strip()
        full_reason = f'Списання: {reason_label}'
        if custom_note:
            full_reason += f' — {custom_note}'

        StockMovement.objects.create(
            product=product,
            type=StockMovement.Type.OUT,
            quantity=qty,
            reason=full_reason,
            created_by=request.user,
        )
        messages.success(request, f'Списано {qty} {product.unit.short if product.unit else ""} — {reason_label}.')
        return redirect('inventory:detail', pk=pk)

    return render(request, 'inventory/writeoff.html', {
        'product': product,
        'reasons': WRITEOFF_REASONS,
    })


@login_required
def quick_intake_modal(request, pk):
    """HTMX: рендерить модалку швидкого приходу."""
    product = get_object_or_404(Product, pk=pk, organization=request.organization)
    return render(request, 'inventory/partials/quick_intake_modal.html', {'product': product})
