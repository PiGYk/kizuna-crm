from datetime import timedelta, date
from decimal import Decimal
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.db.models import Sum, Count, F, DecimalField
from django.db.models.functions import TruncDate

from apps.billing.models import Invoice, InvoiceLine
from apps.clients.models import Client
from apps.inventory.models import StockMovement
from apps.finance.models import Expense, ExpenseCategory
from apps.accounts.mixins import admin_required
from apps.tg.utils import is_mobile

CONSUMABLES_RATE = Decimal('0.05')  # 5% від COGS — шприци/рукавички/пелюшки


def _parse_range(request):
    preset = request.GET.get('preset', 'month')
    today = timezone.localdate()

    if preset == 'today':
        start, end = today, today
    elif preset == 'week':
        start, end = today - timedelta(days=6), today
    elif preset == 'year':
        start, end = date(today.year, 1, 1), today
    elif preset == 'custom':
        try:
            start = date.fromisoformat(request.GET.get('start', ''))
            end = date.fromisoformat(request.GET.get('end', ''))
        except (ValueError, TypeError):
            start, end = today.replace(day=1), today
    else:  # month
        start, end = today.replace(day=1), today

    return start, end, preset


@login_required
def analytics_view(request):
    from apps.accounts.models import User
    doctors = User.objects.filter(
        invoices__isnull=False,
        organization=request.organization,
    ).distinct().order_by('last_name', 'first_name')
    presets = [
        ('today', 'Сьогодні'),
        ('week', '7 днів'),
        ('month', 'Місяць'),
        ('year', 'Рік'),
        ('custom', 'Довільно'),
    ]
    template = 'analytics/index_mobile.html' if is_mobile(request) else 'analytics/index.html'
    return render(request, template, {'doctors': doctors, 'presets': presets})


@login_required
def analytics_data(request):
    start, end, preset = _parse_range(request)
    doctor_id = request.GET.get('doctor') or None

    qs = Invoice.objects.filter(
        status='paid',
        organization=request.organization,
        created_at__date__gte=start,
        created_at__date__lte=end,
    )
    if doctor_id:
        qs = qs.filter(doctor_id=doctor_id)

    # KPIs — об'єднано у 1 aggregate (раніше було 6 окремих).
    from django.db.models import Q
    agg = qs.aggregate(
        revenue=Sum('total'),
        count=Count('id'),
        cash=Sum('total', filter=Q(payment_method='cash')),
        cash_cnt=Count('id', filter=Q(payment_method='cash')),
        card=Sum('total', filter=Q(payment_method='card')),
        card_cnt=Count('id', filter=Q(payment_method='card')),
    )
    revenue = agg['revenue'] or 0
    count = agg['count'] or 0
    cash = agg['cash'] or 0
    cash_cnt = agg['cash_cnt'] or 0
    card = agg['card'] or 0
    card_cnt = agg['card_cnt'] or 0
    avg_check = (revenue / count) if count else 0
    delta_days = (end - start).days + 1
    active_days = qs.annotate(day=TruncDate('created_at')).values('day').distinct().count()
    avg_daily = revenue / active_days if active_days else 0
    new_clients = Client.objects.filter(
        organization=request.organization,
        created_at__date__gte=start,
        created_at__date__lte=end,
    ).count()

    # Рекордна каса за весь час (для організації)
    record_day = (
        Invoice.objects.filter(status='paid', organization=request.organization)
        .annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(total=Sum('total'))
        .order_by('-total')
        .first()
    )

    # Revenue by day
    daily = (
        qs.annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(revenue=Sum('total'), invoices=Count('id'))
        .order_by('day')
    )
    day_map = {r['day']: {'revenue': float(r['revenue']), 'invoices': r['invoices']} for r in daily}
    delta = (end - start).days + 1
    days_labels, days_revenue, days_invoices = [], [], []
    for i in range(delta):
        d = start + timedelta(days=i)
        days_labels.append(d.strftime('%d.%m'))
        days_revenue.append(day_map.get(d, {}).get('revenue', 0))
        days_invoices.append(day_map.get(d, {}).get('invoices', 0))

    # Top services
    top_services = list(
        InvoiceLine.objects
        .filter(invoice__in=qs, line_type='service')
        .values('name')
        .annotate(cnt=Count('id'), total=Sum('total'))
        .order_by('-total')[:8]
    )

    # Top products
    top_products = list(
        InvoiceLine.objects
        .filter(invoice__in=qs, line_type='product')
        .values('name')
        .annotate(cnt=Count('id'), total=Sum('total'))
        .order_by('-total')[:8]
    )

    # Payment methods
    pay_map = {'cash': 'Готівка', 'card': 'Картка', None: 'Не вказано'}
    pay_methods = list(
        qs.values('payment_method')
        .annotate(total=Sum('total'), cnt=Count('id'))
    )

    # By doctor
    by_doctor = list(
        qs.filter(doctor__isnull=False)
        .values('doctor__first_name', 'doctor__last_name')
        .annotate(total=Sum('total'), cnt=Count('id'))
        .order_by('-total')[:10]
    )

    return JsonResponse({
        'kpi': {
            'revenue': float(revenue),
            'count': count,
            'avg_check': float(avg_check),
            'avg_daily': float(avg_daily),
            'new_clients': new_clients,
            'cash': float(cash),
            'cash_cnt': cash_cnt,
            'card': float(card),
            'card_cnt': card_cnt,
            'record_day_total': float(record_day['total']) if record_day else 0,
            'record_day_date': record_day['day'].isoformat() if record_day else None,
        },
        'daily': {
            'labels': days_labels,
            'revenue': days_revenue,
            'invoices': days_invoices,
        },
        'top_services': [
            {'name': s['name'], 'total': float(s['total']), 'cnt': s['cnt']}
            for s in top_services
        ],
        'top_products': [
            {'name': p['name'], 'total': float(p['total']), 'cnt': p['cnt']}
            for p in top_products
        ],
        'payment_methods': [
            {'label': pay_map.get(p['payment_method'], p['payment_method'] or 'Не вказано'),
             'total': float(p['total']), 'cnt': p['cnt']}
            for p in pay_methods
        ],
        'by_doctor': [
            {'name': f"{d['doctor__last_name']} {d['doctor__first_name']}",
             'total': float(d['total']), 'cnt': d['cnt']}
            for d in by_doctor
        ],
        'meta': {
            'start': start.isoformat(),
            'end': end.isoformat(),
            'preset': preset,
        },
    })


@login_required
def debtors_view(request):
    from apps.billing.models import Invoice
    from collections import defaultdict

    drafts = Invoice.objects.filter(
        status='draft',
        total__gt=0,
        organization=request.organization,
    ).select_related('client', 'patient', 'doctor').order_by('client', '-created_at')

    client_map = defaultdict(lambda: {'client': None, 'invoices': [], 'total': 0})
    for inv in drafts:
        g = client_map[inv.client_id]
        g['client'] = inv.client
        g['invoices'].append(inv)
        g['total'] += float(inv.total)

    debtors = sorted(client_map.values(), key=lambda x: x['total'], reverse=True)
    grand_total = sum(d['total'] for d in debtors)

    template = 'analytics/debtors_mobile.html' if is_mobile(request) else 'analytics/debtors.html'
    return render(request, template, {
        'debtors': debtors,
        'grand_total': grand_total,
        'count': len(debtors),
    })


@login_required
def usage_view(request):
    """Сторінка: статистика використання конкретної послуги/товару за період."""
    from apps.services.models import Service
    from apps.inventory.models import Product

    services = Service.objects.filter(
        organization=request.organization, is_active=True
    ).order_by('name').values('id', 'name')
    products = Product.objects.filter(
        organization=request.organization, is_active=True
    ).order_by('name').values('id', 'name', 'sku')

    presets = [
        ('today', 'Сьогодні'), ('week', '7 днів'),
        ('month', 'Місяць'), ('year', 'Рік'), ('custom', 'Довільно'),
    ]
    template = 'analytics/usage_mobile.html' if is_mobile(request) else 'analytics/usage.html'
    return render(request, template, {
        'services': list(services),
        'products': list(products),
        'presets': presets,
    })


@login_required
def usage_data(request):
    """JSON endpoint: aggregate counts/qty/revenue + daily breakdown + top doctors."""
    kind = request.GET.get('kind', 'service')  # service | product
    try:
        obj_id = int(request.GET.get('id', 0))
    except (TypeError, ValueError):
        obj_id = 0
    start, end, preset = _parse_range(request)

    if not obj_id:
        return JsonResponse({'error': 'Оберіть позицію'}, status=400)

    paid_invoices = Invoice.objects.filter(
        status='paid',
        organization=request.organization,
        created_at__date__gte=start,
        created_at__date__lte=end,
    )

    lines_qs = InvoiceLine.objects.filter(invoice__in=paid_invoices)
    if kind == 'service':
        lines_qs = lines_qs.filter(line_type='service', service_id=obj_id)
        title_name = ''
        from apps.services.models import Service
        svc = Service.objects.filter(
            pk=obj_id, organization=request.organization
        ).first()
        if svc:
            title_name = svc.name
    elif kind == 'product':
        lines_qs = lines_qs.filter(line_type='product', product_id=obj_id)
        title_name = ''
        from apps.inventory.models import Product
        prod = Product.objects.filter(
            pk=obj_id, organization=request.organization
        ).first()
        if prod:
            title_name = prod.name
    else:
        return JsonResponse({'error': 'Невідомий тип'}, status=400)

    # Підсумок одним aggregate
    agg = lines_qs.aggregate(
        count=Count('id'),
        qty=Sum('quantity'),
        revenue=Sum('total'),
    )

    # По днях для графіка
    per_day = (
        lines_qs
        .annotate(d=TruncDate('invoice__created_at'))
        .values('d')
        .annotate(cnt=Count('id'), qty=Sum('quantity'), rev=Sum('total'))
        .order_by('d')
    )
    per_day_map = {row['d']: row for row in per_day}

    labels, cnt_series, qty_series, rev_series = [], [], [], []
    d = start
    while d <= end:
        row = per_day_map.get(d)
        labels.append(d.strftime('%d.%m'))
        cnt_series.append(row['cnt'] if row else 0)
        qty_series.append(float(row['qty']) if row and row['qty'] else 0)
        rev_series.append(float(row['rev']) if row and row['rev'] else 0)
        d += timedelta(days=1)

    # Топ-лікарі (хто найбільше надавав/продавав)
    top_doctors = (
        lines_qs
        .filter(invoice__doctor__isnull=False)
        .values('invoice__doctor_id', 'invoice__doctor__first_name', 'invoice__doctor__last_name')
        .annotate(cnt=Count('id'), qty=Sum('quantity'), rev=Sum('total'))
        .order_by('-cnt')[:10]
    )
    top_doctors_list = [
        {
            'name': f"{r['invoice__doctor__last_name']} {r['invoice__doctor__first_name']}".strip() or '—',
            'cnt': r['cnt'],
            'qty': float(r['qty'] or 0),
            'rev': float(r['rev'] or 0),
        }
        for r in top_doctors
    ]

    return JsonResponse({
        'kind': kind,
        'name': title_name,
        'period': {'start': start.isoformat(), 'end': end.isoformat(), 'preset': preset},
        'summary': {
            'count': agg['count'] or 0,
            'qty': float(agg['qty'] or 0),
            'revenue': float(agg['revenue'] or 0),
        },
        'chart': {
            'labels': labels,
            'count': cnt_series,
            'qty': qty_series,
            'revenue': rev_series,
        },
        'top_doctors': top_doctors_list,
    })


@login_required
def services_view(request):
    from django.db.models import Avg

    start, end, preset = _parse_range(request)

    paid_invoices = Invoice.objects.filter(
        status='paid',
        organization=request.organization,
        created_at__date__gte=start,
        created_at__date__lte=end,
    )
    total_revenue = paid_invoices.aggregate(t=Sum('total'))['t'] or 0

    services = (
        InvoiceLine.objects
        .filter(invoice__in=paid_invoices, line_type='service')
        .values('name')
        .annotate(cnt=Count('id'), total=Sum('total'), avg_price=Avg('unit_price'))
        .order_by('-total')
    )

    products = (
        InvoiceLine.objects
        .filter(invoice__in=paid_invoices, line_type='product')
        .values('name')
        .annotate(cnt=Count('id'), total=Sum('total'), avg_price=Avg('unit_price'))
        .order_by('-total')
    )

    presets = [
        ('today', 'Сьогодні'), ('week', '7 днів'),
        ('month', 'Місяць'), ('year', 'Рік'), ('custom', 'Довільно'),
    ]

    template = 'analytics/services_mobile.html' if is_mobile(request) else 'analytics/services.html'
    return render(request, template, {
        'services': services,
        'products': products,
        'total_revenue': total_revenue,
        'start': start,
        'end': end,
        'preset': preset,
        'presets': presets,
    })


@admin_required
def payroll_view(request):
    from apps.accounts.models import User
    from apps.accounts.models_payroll import Shift
    start, end, preset = _parse_range(request)
    doctor_id = request.GET.get('doctor') or None

    doctors = User.objects.filter(
        organization=request.organization,
        role__in=['doctor', 'admin'],
    ).order_by('last_name', 'first_name')

    # Один запит замість циклу N×aggregate: values+annotate по doctor_id.
    doctor_stats_qs = (
        Invoice.objects
        .filter(
            status='paid',
            organization=request.organization,
            created_at__date__gte=start,
            created_at__date__lte=end,
            doctor__isnull=False,
        )
        .values('doctor_id')
        .annotate(revenue=Sum('total'), inv_count=Count('id'))
    )
    stats_by_doc = {s['doctor_id']: s for s in doctor_stats_qs}

    # Shift aggregate для per_shift/hourly типів.
    shift_stats_qs = (
        Shift.objects
        .filter(
            organization=request.organization,
            date__gte=start,
            date__lte=end,
        )
        .values('user_id')
        .annotate(shift_count=Count('id'), hours_total=Sum('hours'))
    )
    shifts_by_doc = {s['user_id']: s for s in shift_stats_qs}

    results = []
    for doctor in doctors:
        if doctor_id and str(doctor.pk) != str(doctor_id):
            continue

        s = stats_by_doc.get(doctor.pk, {'revenue': 0, 'inv_count': 0})
        revenue = s['revenue'] or 0
        count = s['inv_count'] or 0
        sh = shifts_by_doc.get(doctor.pk, {'shift_count': 0, 'hours_total': 0})
        shift_count = sh['shift_count'] or 0
        hours_total = float(sh['hours_total'] or 0)

        salary = 0
        st = doctor.salary_type
        if st == 'fixed':
            salary = float(doctor.salary_fixed)
        elif st == 'percent':
            salary = float(revenue) * float(doctor.salary_percent) / 100
        elif st in ('mixed', 'fixed_percent'):
            salary = float(doctor.salary_fixed) + float(revenue) * float(doctor.salary_percent) / 100
        elif st == 'per_shift':
            salary = shift_count * float(doctor.salary_per_shift)
        elif st == 'hourly':
            salary = hours_total * float(doctor.salary_hourly)

        results.append({
            'doctor': doctor,
            'revenue': float(revenue),
            'count': count,
            'salary': round(salary, 2),
            'salary_type': doctor.get_salary_type_display(),
        })

    presets = [
        ('today', 'Сьогодні'), ('week', '7 днів'),
        ('month', 'Місяць'), ('year', 'Рік'), ('custom', 'Довільно'),
    ]
    template = 'analytics/payroll_mobile.html' if is_mobile(request) else 'analytics/payroll.html'
    return render(request, template, {
        'results': results,
        'doctors': doctors,
        'presets': presets,
        'selected_doctor': doctor_id,
        'start': start,
        'end': end,
        'preset': preset,
        'total_salary': sum(r['salary'] for r in results),
        'total_revenue': sum(r['revenue'] for r in results),
    })


# ── Чистий прибуток ─────────────────────────────────────────────────────────

def _profit_cache_key(org_id, start, end, exclude_categories, exclude_expenses):
    import hashlib
    payload = repr((sorted(exclude_categories or []), sorted(exclude_expenses or [])))
    h = hashlib.md5(payload.encode()).hexdigest()[:8]
    return f'profit:{org_id}:{start.isoformat()}:{end.isoformat()}:{h}'


def _profit_for_range_cached(org, start, end, exclude_categories, exclude_expenses):
    """Кеш Redis на 5хв — drop-in замість прямого виклику _profit_for_range у циклах."""
    from django.core.cache import cache
    key = _profit_cache_key(org.id, start, end, exclude_categories, exclude_expenses)
    data = cache.get(key)
    if data is None:
        data = _profit_for_range(org, start, end, exclude_categories, exclude_expenses)
        cache.set(key, data, 300)
    return data


def _profit_for_range(org, start, end, exclude_categories, exclude_expenses):
    """Виручка − COGS − витратники(5%) − витрати з фінансів за період."""
    revenue = Invoice.objects.filter(
        status='paid', organization=org,
        created_at__date__gte=start, created_at__date__lte=end,
    ).aggregate(t=Sum('total'))['t'] or Decimal('0')

    cogs = StockMovement.objects.filter(
        type='out',
        product__organization=org,
        created_at__date__gte=start, created_at__date__lte=end,
    ).aggregate(
        t=Sum(F('quantity') * F('product__buy_price'), output_field=DecimalField(max_digits=14, decimal_places=2))
    )['t'] or Decimal('0')

    consumables = (cogs * CONSUMABLES_RATE).quantize(Decimal('0.01'))

    expenses_qs = Expense.objects.filter(
        organization=org, date__gte=start, date__lte=end,
    )
    if exclude_categories:
        expenses_qs = expenses_qs.exclude(category_id__in=exclude_categories)
    if exclude_expenses:
        expenses_qs = expenses_qs.exclude(pk__in=exclude_expenses)
    expenses = expenses_qs.aggregate(t=Sum('amount'))['t'] or Decimal('0')

    net = Decimal(revenue) - Decimal(cogs) - consumables - Decimal(expenses)
    return {
        'revenue': float(revenue),
        'cogs': float(cogs),
        'consumables': float(consumables),
        'expenses': float(expenses),
        'net': float(net),
    }


def _profit_per_day(org, start, end, exclude_categories, exclude_expenses):
    """Повертає dict {date: profit_dict} для всього range — 3 query замість 3×N.

    Замість _profit_for_range_cached × 31 день (cold cache = ~93 queries),
    три anotate з TruncDate і агрегацією в Python.
    """
    rev_per_day = dict(
        Invoice.objects
        .filter(status='paid', organization=org,
                created_at__date__gte=start, created_at__date__lte=end)
        .annotate(d=TruncDate('created_at'))
        .values('d')
        .annotate(t=Sum('total'))
        .values_list('d', 't')
    )

    cogs_per_day = dict(
        StockMovement.objects
        .filter(type='out', product__organization=org,
                created_at__date__gte=start, created_at__date__lte=end)
        .annotate(d=TruncDate('created_at'))
        .values('d')
        .annotate(t=Sum(F('quantity') * F('product__buy_price'),
                        output_field=DecimalField(max_digits=14, decimal_places=2)))
        .values_list('d', 't')
    )

    exp_qs = Expense.objects.filter(organization=org, date__gte=start, date__lte=end)
    if exclude_categories:
        exp_qs = exp_qs.exclude(category_id__in=exclude_categories)
    if exclude_expenses:
        exp_qs = exp_qs.exclude(pk__in=exclude_expenses)
    exp_per_day = dict(
        exp_qs.values('date').annotate(t=Sum('amount')).values_list('date', 't')
    )

    result = {}
    d = start
    while d <= end:
        revenue = rev_per_day.get(d) or Decimal('0')
        cogs = cogs_per_day.get(d) or Decimal('0')
        consumables = (cogs * CONSUMABLES_RATE).quantize(Decimal('0.01'))
        expenses = exp_per_day.get(d) or Decimal('0')
        net = revenue - cogs - consumables - expenses
        result[d] = {
            'revenue': float(revenue),
            'cogs': float(cogs),
            'consumables': float(consumables),
            'expenses': float(expenses),
            'net': float(net),
        }
        d += timedelta(days=1)
    return result


def _parse_id_list(raw):
    if not raw:
        return []
    out = []
    for s in raw.split(','):
        s = s.strip()
        if s.isdigit():
            out.append(int(s))
    return out


@login_required
def profit_view(request):
    org = request.organization
    categories = ExpenseCategory.objects.filter(organization=org).order_by('name')
    today = timezone.localdate()
    month_start = today.replace(day=1)
    month_expenses = (
        Expense.objects.filter(organization=org, date__gte=month_start, date__lte=today)
        .select_related('category')
        .order_by('-date', '-id')
    )
    template = 'analytics/profit_mobile.html' if is_mobile(request) else 'analytics/profit.html'
    return render(request, template, {
        'categories': categories,
        'month_expenses': month_expenses,
        'periods': [
            ('day', 'Сьогодні'),
            ('week', 'Цей тиждень'),
            ('month', 'Цей місяць'),
            ('year', 'Цей рік'),
        ],
    })


@login_required
def profit_data(request):
    org = request.organization
    today = timezone.localdate()

    exclude_categories = _parse_id_list(request.GET.get('exclude_categories', ''))
    exclude_expenses = _parse_id_list(request.GET.get('exclude_expenses', ''))

    # 4 фіксовані періоди
    periods = {
        'day': (today, today),
        'week': (today - timedelta(days=today.weekday()), today),  # Пн поточного тижня → сьогодні
        'month': (today.replace(day=1), today),
        'year': (date(today.year, 1, 1), today),
    }
    cards = {
        key: _profit_for_range_cached(org, s, e, exclude_categories, exclude_expenses)
        for key, (s, e) in periods.items()
    }

    # Графік: чистий прибуток по днях за поточний місяць
    chart_period = request.GET.get('chart', 'month')
    if chart_period == 'year':
        # помісячно за рік — _profit_for_range_cached × 12 (max), кеш покриває.
        labels, net_series, rev_series = [], [], []
        for m in range(1, today.month + 1):
            mstart = date(today.year, m, 1)
            if m == 12:
                mend = date(today.year, 12, 31)
            else:
                mend = date(today.year, m + 1, 1) - timedelta(days=1)
            if mend > today:
                mend = today
            r = _profit_for_range_cached(org, mstart, mend, exclude_categories, exclude_expenses)
            labels.append(mstart.strftime('%b'))
            net_series.append(r['net'])
            rev_series.append(r['revenue'])
    else:
        # по днях за місяць — один TruncDate annotate замість 31× _profit_for_range
        mstart = today.replace(day=1)
        per_day = _profit_per_day(org, mstart, today, exclude_categories, exclude_expenses)
        labels, net_series, rev_series = [], [], []
        d = mstart
        while d <= today:
            r = per_day.get(d, {'net': 0, 'revenue': 0})
            labels.append(d.strftime('%d.%m'))
            net_series.append(r['net'])
            rev_series.append(r['revenue'])
            d += timedelta(days=1)

    return JsonResponse({
        'cards': cards,
        'chart': {'labels': labels, 'net': net_series, 'revenue': rev_series, 'period': chart_period},
        'consumables_rate_pct': float(CONSUMABLES_RATE * 100),
    })
