from datetime import timedelta, date
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.db.models import Sum, Count
from django.db.models.functions import TruncDate

from apps.billing.models import Invoice, InvoiceLine
from apps.clients.models import Client


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
    doctors = User.objects.filter(invoices__isnull=False).distinct().order_by('last_name', 'first_name')
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
            'new_clients': new_clients,
            'cash': float(cash),
            'cash_cnt': cash_cnt,
            'card': float(card),
            'card_cnt': card_cnt,
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
