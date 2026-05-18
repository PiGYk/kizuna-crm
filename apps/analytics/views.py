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
    return render(request, 'analytics/index.html', {'doctors': doctors, 'presets': presets})


@login_required
def analytics_data(request):
    start, end, preset = _parse_range(request)
    doctor_id = request.GET.get('doctor') or None

    qs = Invoice.objects.filter(
        status='paid',
        created_at__date__gte=start,
        created_at__date__lte=end,
    )
    if doctor_id:
        qs = qs.filter(doctor_id=doctor_id)

    # KPIs
    revenue = qs.aggregate(t=Sum('total'))['t'] or 0
    count = qs.count()
    avg_check = (revenue / count) if count else 0
    delta_days = (end - start).days + 1
    active_days = qs.annotate(day=TruncDate('created_at')).values('day').distinct().count()
    avg_daily = revenue / active_days if active_days else 0
    new_clients = Client.objects.filter(
        created_at__date__gte=start,
        created_at__date__lte=end,
    ).count()
    cash_qs = qs.filter(payment_method='cash').aggregate(t=Sum('total'), c=Count('id'))
    card_qs = qs.filter(payment_method='card').aggregate(t=Sum('total'), c=Count('id'))
    cash = cash_qs['t'] or 0
    cash_cnt = cash_qs['c'] or 0
    card = card_qs['t'] or 0
    card_cnt = card_qs['c'] or 0

    # Рекордна каса за весь час (для організації, без фільтрів)
    record_day = (
        Invoice.objects.filter(status='paid')
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

    return render(request, 'analytics/debtors.html', {
        'debtors': debtors,
        'grand_total': grand_total,
        'count': len(debtors),
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

    return render(request, 'analytics/services.html', {
        'services': services,
        'products': products,
        'total_revenue': total_revenue,
        'start': start,
        'end': end,
        'preset': preset,
        'presets': presets,
    })


@login_required
def payroll_view(request):
    from apps.accounts.models import User
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

    results = []
    for doctor in doctors:
        if doctor_id and str(doctor.pk) != str(doctor_id):
            continue

        s = stats_by_doc.get(doctor.pk, {'revenue': 0, 'inv_count': 0})
        revenue = s['revenue'] or 0
        count = s['inv_count'] or 0

        salary = 0
        if doctor.salary_type == 'fixed':
            salary = float(doctor.salary_fixed)
        elif doctor.salary_type == 'percent':
            salary = float(revenue) * float(doctor.salary_percent) / 100
        elif doctor.salary_type == 'mixed':
            salary = float(doctor.salary_fixed) + float(revenue) * float(doctor.salary_percent) / 100

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
    return render(request, 'analytics/payroll.html', {
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
    return render(request, 'analytics/profit.html', {
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
        # помісячно за рік
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
        # по днях за місяць
        mstart = today.replace(day=1)
        days = (today - mstart).days + 1
        labels, net_series, rev_series = [], [], []
        for i in range(days):
            d = mstart + timedelta(days=i)
            r = _profit_for_range_cached(org, d, d, exclude_categories, exclude_expenses)
            labels.append(d.strftime('%d.%m'))
            net_series.append(r['net'])
            rev_series.append(r['revenue'])

    return JsonResponse({
        'cards': cards,
        'chart': {'labels': labels, 'net': net_series, 'revenue': rev_series, 'period': chart_period},
        'consumables_rate_pct': float(CONSUMABLES_RATE * 100),
    })
