from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import ListView, DetailView
from django.urls import reverse

from .forms import ServiceForm, ComponentFormSet
from .models import Service, ServiceCategory


class ServiceListView(LoginRequiredMixin, ListView):
    model = Service
    template_name = 'services/list.html'
    context_object_name = 'services'

    def get_queryset(self):
        qs = Service.objects.select_related('category').prefetch_related('components__product')
        if not self.request.GET.get('inactive'):
            qs = qs.filter(is_active=True)
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(name__icontains=q)
        cat = self.request.GET.get('cat', '').strip()
        if cat == 'none':
            qs = qs.filter(category__isnull=True)
        elif cat.isdigit():
            qs = qs.filter(category_id=int(cat))
        return qs.order_by('category__sort_order', 'category__name', 'name')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['q'] = self.request.GET.get('q', '').strip()
        ctx['selected_cat'] = self.request.GET.get('cat', '').strip()
        ctx['categories'] = list(ServiceCategory.objects.all())

        # Згрупувати для рендеру за категорією
        groups = {}
        for s in ctx['services']:
            key = s.category.name if s.category else '— Без категорії —'
            groups.setdefault(key, []).append(s)
        cat_order = {c.name: c.sort_order for c in ctx['categories']}
        ctx['grouped_services'] = sorted(groups.items(), key=lambda kv: cat_order.get(kv[0], 9999))
        return ctx


class ServiceDetailView(LoginRequiredMixin, DetailView):
    model = Service
    template_name = 'services/detail.html'
    context_object_name = 'service'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['components'] = self.object.components.select_related('product__unit')
        return ctx


@login_required
def service_create(request):
    form = ServiceForm(request.POST or None)
    formset = ComponentFormSet(request.POST or None, prefix='comp')
    if request.method == 'POST' and form.is_valid() and formset.is_valid():
        service = form.save(commit=False)
        service.organization = request.organization
        service.save()
        formset.instance = service
        formset.save()
        messages.success(request, 'Послугу додано')
        return redirect('services:edit', pk=service.pk)
    return render(request, 'services/form.html', {'form': form, 'formset': formset})


@login_required
def service_update(request, pk):
    service = get_object_or_404(Service, pk=pk, organization=request.organization)
    form = ServiceForm(request.POST or None, instance=service)
    formset = ComponentFormSet(request.POST or None, instance=service, prefix='comp')
    if request.method == 'POST' and form.is_valid() and formset.is_valid():
        form.save()
        formset.save()
        messages.success(request, 'Збережено')
        return redirect('services:edit', pk=service.pk)
    return render(request, 'services/form.html', {'form': form, 'formset': formset, 'service': service})


@login_required
def service_delete(request, pk):
    service = get_object_or_404(Service, pk=pk, organization=request.organization)
    if request.method == 'POST':
        service.delete()
        messages.success(request, 'Послугу видалено')
        return redirect('services:list')
    return redirect('services:edit', pk=pk)


# ── Масове завантаження і коригування послуг ────────────────────────────────
# Прохання Ірпеня 10.08: «чи можна масово завантажити і скоригувати послуги?».
# Одна дія закриває обидва: рядок із назвою, якої ще немає, створює послугу;
# рядок із наявною назвою — оновлює їй ціну/категорію/опис. Тому прайс можна
# вести у звичайній таблиці й заливати сюди цілком.

_SERVICE_ALIASES = {
    'name': ['назва', 'послуга', 'name', 'service', 'найменування', 'наименование'],
    'price': ['ціна', 'вартість', 'price', 'cost', 'цена', 'сума'],
    'category': ['категорія', 'category', 'група', 'группа', 'розділ', 'тип'],
    'description': ['опис', 'description', 'примітки', 'нотатки', 'коментар'],
}


def _match_service_columns(headers):
    """Заголовок файлу → поле системи. Людина називає колонки як звикла."""
    mapping = {}
    for field, aliases in _SERVICE_ALIASES.items():
        for h in headers:
            if str(h).strip().lower() in aliases:
                mapping[field] = h
                break
    return mapping


def _to_price(raw):
    """«1 200,50 грн» → Decimal('1200.50'). Порожнє/сміття → None."""
    from decimal import Decimal, InvalidOperation
    if raw is None:
        return None
    s = str(raw).replace('\xa0', ' ').replace(' ', '').replace(',', '.')
    s = ''.join(ch for ch in s if ch.isdigit() or ch == '.')
    if not s:
        return None
    try:
        return Decimal(s).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError):
        return None


@login_required
def service_import(request):
    """Крок 1: файл → розбір → показ, що саме зміниться."""
    from apps.inventory.views import _parse_file

    if request.method == 'POST' and request.FILES.get('file'):
        headers, rows = _parse_file(request.FILES['file'])
        if not headers:
            messages.error(request, 'Не вдалося прочитати файл. Підтримуються CSV і XLSX.')
            return redirect('services:import')

        cols = _match_service_columns(headers)
        if 'name' not in cols:
            messages.error(
                request,
                'У файлі не знайдено колонки з назвою послуги. '
                'Назвіть її «Назва» або «Послуга».'
            )
            return redirect('services:import')

        existing = {
            s.name.strip().lower(): s
            for s in Service.objects.filter(organization=request.organization)
        }

        to_create, to_update, skipped = [], [], 0
        for row in rows:
            name = str(row.get(cols['name'], '') or '').strip()
            if not name:
                skipped += 1
                continue
            price = _to_price(row.get(cols['price'])) if 'price' in cols else None
            item = {
                'name': name,
                # рядком, а не Decimal: між кроками це лежить у сесії, а вона
                # серіалізується в JSON — Decimal туди не кладеться
                'price': str(price) if price is not None else None,
                'category': str(row.get(cols['category'], '') or '').strip() if 'category' in cols else '',
                'description': str(row.get(cols['description'], '') or '').strip() if 'description' in cols else '',
            }
            found = existing.get(name.lower())
            if found:
                item['old_price'] = str(found.price)
                item['pk'] = found.pk
                to_update.append(item)
            else:
                to_create.append(item)

        request.session['svc_import_create'] = to_create
        request.session['svc_import_update'] = to_update

        return render(request, 'services/import_preview.html', {
            'to_create': to_create,
            'to_update': to_update,
            'skipped': skipped,
            'filename': request.FILES['file'].name,
            'matched': cols,
        })

    return render(request, 'services/import.html')


@login_required
def service_import_execute(request):
    """Крок 2: підтверджено — створюємо і оновлюємо."""
    from django.db import transaction

    if request.method != 'POST':
        return redirect('services:import')

    to_create = request.session.get('svc_import_create', [])
    to_update = request.session.get('svc_import_update', [])
    if not to_create and not to_update:
        messages.error(request, 'Немає що імпортувати — завантажте файл ще раз.')
        return redirect('services:import')

    org = request.organization
    cat_cache = {c.name.strip().lower(): c for c in ServiceCategory.objects.all()}

    def resolve_category(title):
        """Категорія за назвою; якої немає — заводимо, щоб не губити розкладку."""
        key = (title or '').strip().lower()
        if not key:
            return None
        if key not in cat_cache:
            cat_cache[key] = ServiceCategory.objects.create(name=title.strip())
        return cat_cache[key]

    from decimal import Decimal

    def price_of(item):
        """У сесії ціна лежить рядком — повертаємо назад у число."""
        return Decimal(item['price']) if item.get('price') is not None else None

    created = updated = 0
    with transaction.atomic():
        for item in to_create:
            Service.objects.create(
                name=item['name'],
                price=price_of(item) or 0,
                description=item.get('description', ''),
                category=resolve_category(item.get('category')),
                organization=org,
            )
            created += 1

        for item in to_update:
            svc = Service.objects.filter(pk=item['pk'], organization=org).first()
            if not svc:
                continue
            changed = False
            new_price = price_of(item)
            if new_price is not None and svc.price != new_price:
                svc.price = new_price
                changed = True
            if item.get('category'):
                cat = resolve_category(item['category'])
                if cat and svc.category_id != cat.pk:
                    svc.category = cat
                    changed = True
            if item.get('description') and svc.description != item['description']:
                svc.description = item['description']
                changed = True
            if changed:
                svc.save()
                updated += 1

    request.session.pop('svc_import_create', None)
    request.session.pop('svc_import_update', None)
    messages.success(request, f'Готово: створено {created}, оновлено {updated}.')
    return redirect('services:list')


@login_required
def service_import_template(request):
    """Зразок файлу — щоб не гадати, які колонки потрібні."""
    import csv as _csv
    from django.http import HttpResponse

    response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
    response['Content-Disposition'] = 'attachment; filename="services_template.csv"'
    writer = _csv.writer(response)
    writer.writerow(['Назва', 'Ціна', 'Категорія', 'Опис'])
    writer.writerow(['Первинний прийом', '400', 'Консультації', ''])
    writer.writerow(['Стерилізація кішки', '3500', 'Хірургія', 'до 5 кг'])
    writer.writerow(['УЗД черевної порожнини', '700', 'Діагностика', ''])
    return response
