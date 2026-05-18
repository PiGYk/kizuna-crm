"""
Реєстр віджетів для конструктора дашборду.

Кожен віджет — це функція render(request, config) -> str (HTML).
Декоратор @register('key', ...) додає метадані: label, icon, category,
розмір за замовчуванням (GridStack), дозволені ролі, конфіг-поля.

Контракт з backend agent:
    WIDGETS[key]['render'](request, config) -> str
    WIDGETS[key]['roles_allowed'] -> list[str]   # ['admin', 'doctor', 'assistant']
    WIDGETS[key]['label'] / icon / category / default_w / default_h
    WIDGETS[key]['config_fields'] -> list[dict]  # для UI налаштування

ВАЖЛИВО:
- Фінансові віджети — лише admin+doctor.
- Multi-tenant: усі моделі мають OrgManager → .objects.filter() сам ріже.
- Chart.js — інший агент має підключити CDN у головному шаблоні дашборду.
"""

import json
from datetime import timedelta, date, datetime, time
from decimal import Decimal

from django.db.models import Sum, Count, F, Q, DecimalField
from django.db.models.functions import TruncDate, Coalesce
from django.utils import timezone
from django.utils.html import escape
from django.utils.safestring import mark_safe


WIDGETS = {}  # глобальний реєстр {key: {render, label, icon, ...}}


def register(key, **kwargs):
    """Декоратор для реєстрації віджета у глобальний реєстр."""
    def wrapper(func):
        WIDGETS[key] = {'render': func, **kwargs}
        return func
    return wrapper


# ======================================================================
# HELPERS
# ======================================================================

ROLES_ALL = ['admin', 'doctor', 'assistant']
ROLES_FIN = ['admin', 'doctor']  # фінанси приховуємо від асистентів

CARD_CLASSES = (
    'bg-white rounded-xl border border-gray-200 p-4 h-full '
    'flex flex-col overflow-hidden'
)


def _money(value):
    """Форматує суму як '12 345 ₴' (без копійок)."""
    try:
        v = int(round(Decimal(value or 0)))
    except (TypeError, ValueError):
        v = 0
    s = f'{v:,}'.replace(',', ' ')
    return f'{s} ₴'


def _period_range(period):
    """Повертає (start_dt, end_dt) для періоду."""
    now = timezone.localtime()
    today = now.date()
    if period == 'week':
        start = today - timedelta(days=6)
    elif period == 'month':
        start = today.replace(day=1)
    else:  # 'today'
        start = today
    tz = timezone.get_current_timezone()
    start_dt = timezone.make_aware(datetime.combine(start, time.min), tz)
    end_dt = timezone.make_aware(datetime.combine(today, time.max), tz)
    return start_dt, end_dt


def _widget_id(config):
    """Унікальний id для DOM-елементів (Chart.js canvas, etc.)."""
    wid = (config or {}).get('widget_id') or (config or {}).get('id') or 'w'
    return escape(str(wid))


def _render_kpi(label, value, icon='', sub='', color='brand-gold'):
    """Стандартна KPI-картка з великим числом."""
    sub_html = (
        f'<div class="text-xs text-gray-400 mt-1">{escape(sub)}</div>'
        if sub else ''
    )
    return f'''
    <div class="{CARD_CLASSES}">
      <div class="flex items-center gap-2 mb-2">
        <span class="text-xl">{icon}</span>
        <span class="text-xs text-gray-500 uppercase tracking-wide">{escape(label)}</span>
      </div>
      <div class="text-3xl font-bold text-{color} mt-auto">{value}</div>
      {sub_html}
    </div>
    '''


def _render_card(title, icon, body_html):
    """Картка-обгортка для списків / графіків."""
    return f'''
    <div class="{CARD_CLASSES}">
      <div class="flex items-center gap-2 mb-3 shrink-0">
        <span class="text-lg">{icon}</span>
        <h3 class="text-sm font-semibold text-brand-dark">{escape(title)}</h3>
      </div>
      <div class="flex-1 overflow-y-auto -mx-4 px-4">{body_html}</div>
    </div>
    '''


def _empty(text='Немає даних'):
    return f'<div class="text-sm text-gray-400 text-center py-6">{escape(text)}</div>'


def _chart(canvas_id, chart_type, labels, datasets, options=None):
    """Генерує canvas + inline-скрипт ініціалізації Chart.js."""
    cfg = {
        'type': chart_type,
        'data': {'labels': labels, 'datasets': datasets},
        'options': options or {
            'responsive': True,
            'maintainAspectRatio': False,
            'plugins': {'legend': {'display': chart_type != 'bar'}},
        },
    }
    cfg_json = json.dumps(cfg, ensure_ascii=False)
    return mark_safe(f'''
      <div class="relative w-full h-full min-h-[180px]">
        <canvas id="{canvas_id}"></canvas>
      </div>
      <script>
      (function() {{
        function init() {{
          if (typeof Chart === 'undefined') {{ setTimeout(init, 200); return; }}
          var el = document.getElementById('{canvas_id}');
          if (!el) return;
          if (el._chart) {{ el._chart.destroy(); }}
          el._chart = new Chart(el, {cfg_json});
        }}
        init();
      }})();
      </script>
    ''')


# ======================================================================
# KPI ВІДЖЕТИ (картка з великим числом)
# ======================================================================

@register(
    'kpi_clients_total',
    label='Всього клієнтів', icon='👥', category='KPI',
    default_w=3, default_h=2, min_w=2, min_h=2,
    roles_allowed=ROLES_ALL,
)
def render_kpi_clients_total(request, config):
    from apps.clients.models import Client
    cnt = Client.objects.count()
    return _render_kpi('Клієнтів', cnt, '👥', color='brand-gold')


@register(
    'kpi_patients_total',
    label='Всього пацієнтів', icon='🐾', category='KPI',
    default_w=3, default_h=2, min_w=2, min_h=2,
    roles_allowed=ROLES_ALL,
)
def render_kpi_patients_total(request, config):
    from apps.clients.models import Patient
    cnt = Patient.objects.count()
    return _render_kpi('Пацієнтів', cnt, '🐾', color='brand-gold')


@register(
    'kpi_appointments_today',
    label='Записи сьогодні', icon='📅', category='KPI',
    default_w=3, default_h=2, min_w=2, min_h=2,
    roles_allowed=ROLES_ALL,
)
def render_kpi_appointments_today(request, config):
    from apps.appointments.models import Appointment
    start, end = _period_range('today')
    cnt = Appointment.objects.filter(starts_at__range=(start, end)).count()
    return _render_kpi('Записів сьогодні', cnt, '📅', color='brand-gold')


@register(
    'kpi_revenue_today',
    label='Виручка сьогодні', icon='💰', category='KPI',
    default_w=3, default_h=2, min_w=2, min_h=2,
    roles_allowed=ROLES_FIN,
)
def render_kpi_revenue_today(request, config):
    from apps.billing.models import Invoice
    start, end = _period_range('today')
    total = Invoice.objects.filter(
        status=Invoice.Status.PAID, created_at__range=(start, end)
    ).aggregate(s=Coalesce(Sum('total'), Decimal('0')))['s']
    return _render_kpi('Виручка сьогодні', _money(total), '💰', color='brand-gold')


@register(
    'kpi_revenue_month',
    label='Виручка за місяць', icon='💵', category='KPI',
    default_w=3, default_h=2, min_w=2, min_h=2,
    roles_allowed=ROLES_FIN,
    config_fields=[
        {'name': 'period', 'label': 'Період', 'type': 'select',
         'options': [('today', 'Сьогодні'), ('week', 'Тиждень'), ('month', 'Місяць')],
         'default': 'month'},
    ],
)
def render_kpi_revenue_month(request, config):
    from apps.billing.models import Invoice
    period = (config or {}).get('period', 'month')
    start, end = _period_range(period)
    total = Invoice.objects.filter(
        status=Invoice.Status.PAID, created_at__range=(start, end)
    ).aggregate(s=Coalesce(Sum('total'), Decimal('0')))['s']
    label_map = {'today': 'Сьогодні', 'week': 'За тиждень', 'month': 'За місяць'}
    return _render_kpi(label_map.get(period, 'За місяць'), _money(total), '💵', color='brand-gold')


@register(
    'kpi_invoices_today',
    label='Чеків сьогодні', icon='🧾', category='KPI',
    default_w=3, default_h=2, min_w=2, min_h=2,
    roles_allowed=ROLES_FIN,
)
def render_kpi_invoices_today(request, config):
    from apps.billing.models import Invoice
    start, end = _period_range('today')
    cnt = Invoice.objects.filter(
        status=Invoice.Status.PAID, created_at__range=(start, end)
    ).count()
    return _render_kpi('Чеків сьогодні', cnt, '🧾', color='brand-gold')


@register(
    'kpi_unpaid_invoices',
    label='Несплачено рахунків', icon='⏳', category='KPI',
    default_w=3, default_h=2, min_w=2, min_h=2,
    roles_allowed=ROLES_FIN,
)
def render_kpi_unpaid_invoices(request, config):
    from apps.billing.models import Invoice
    qs = Invoice.objects.filter(status=Invoice.Status.DRAFT)
    cnt = qs.count()
    total = qs.aggregate(s=Coalesce(Sum('total'), Decimal('0')))['s']
    sub = f'на {_money(total)}' if cnt else ''
    return _render_kpi('Не сплачено', cnt, '⏳', sub=sub, color='red-600')


@register(
    'kpi_low_stock_count',
    label='Малий залишок', icon='📦', category='KPI',
    default_w=3, default_h=2, min_w=2, min_h=2,
    roles_allowed=ROLES_ALL,
)
def render_kpi_low_stock(request, config):
    from apps.inventory.models import Product
    cnt = Product.objects.filter(
        is_active=True, min_quantity__gt=0, quantity__lte=F('min_quantity')
    ).count()
    color = 'red-600' if cnt else 'brand-gold'
    return _render_kpi('Товарів закінчується', cnt, '📦', color=color)


@register(
    'kpi_overdue_vaccines',
    label='Прострочені вакцини', icon='💉', category='KPI',
    default_w=3, default_h=2, min_w=2, min_h=2,
    roles_allowed=ROLES_ALL,
)
def render_kpi_overdue_vaccines(request, config):
    from apps.clients.models import Vaccine
    today = timezone.localdate()
    cnt = Vaccine.objects.filter(next_date__lt=today).count()
    color = 'red-600' if cnt else 'brand-gold'
    return _render_kpi('Прострочених вакцин', cnt, '💉', color=color)


@register(
    'kpi_tg_unread',
    label='Непрочитані Telegram', icon='💬', category='KPI',
    default_w=3, default_h=2, min_w=2, min_h=2,
    roles_allowed=ROLES_ALL,
)
def render_kpi_tg_unread(request, config):
    from apps.tg.models import TelegramMessage
    cnt = TelegramMessage.objects.filter(direction='in', is_read=False).count()
    color = 'red-600' if cnt else 'brand-gold'
    return _render_kpi('Непрочитаних TG', cnt, '💬', color=color)


# ======================================================================
# СПИСКИ (таблиці-картки)
# ======================================================================

@register(
    'list_today_appointments',
    label='Записи на сьогодні', icon='📅', category='Списки',
    default_w=6, default_h=4, min_w=3, min_h=3,
    roles_allowed=ROLES_ALL,
)
def render_list_today_appointments(request, config):
    from apps.appointments.models import Appointment
    start, end = _period_range('today')
    qs = (Appointment.objects
          .filter(starts_at__range=(start, end))
          .select_related('client', 'patient', 'doctor')
          .order_by('starts_at')[:20])

    if not qs:
        return _render_card('Записи сьогодні', '📅', _empty('Сьогодні записів немає'))

    rows = []
    status_color = {
        'scheduled': 'bg-blue-100 text-blue-700',
        'confirmed': 'bg-green-100 text-green-700',
        'completed': 'bg-gray-100 text-gray-700',
        'cancelled': 'bg-red-100 text-red-700',
        'no_show': 'bg-orange-100 text-orange-700',
    }
    for a in qs:
        time_s = timezone.localtime(a.starts_at).strftime('%H:%M')
        client = escape(str(a.client))
        patient = escape(str(a.patient or '—'))
        doctor = escape(a.doctor.get_full_name() or a.doctor.username) if a.doctor else '—'
        st = status_color.get(a.status, 'bg-gray-100 text-gray-700')
        st_label = escape(a.get_status_display())
        rows.append(f'''
          <tr class="border-b border-gray-100 hover:bg-gray-50">
            <td class="py-2 px-2 text-sm font-mono text-brand-gold">{time_s}</td>
            <td class="py-2 px-2 text-sm">{client}</td>
            <td class="py-2 px-2 text-sm text-gray-600">{patient}</td>
            <td class="py-2 px-2 text-xs text-gray-500">{doctor}</td>
            <td class="py-2 px-2"><span class="text-xs px-2 py-0.5 rounded {st}">{st_label}</span></td>
          </tr>
        ''')

    body = f'''
      <table class="w-full text-left">
        <thead class="text-xs text-gray-400 uppercase">
          <tr><th class="py-1 px-2">Час</th><th class="py-1 px-2">Клієнт</th>
          <th class="py-1 px-2">Тварина</th><th class="py-1 px-2">Лікар</th>
          <th class="py-1 px-2">Статус</th></tr>
        </thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    '''
    return _render_card('Записи сьогодні', '📅', body)


@register(
    'list_low_stock',
    label='Товари: малий залишок', icon='📦', category='Списки',
    default_w=6, default_h=4, min_w=3, min_h=3,
    roles_allowed=ROLES_ALL,
)
def render_list_low_stock(request, config):
    from apps.inventory.models import Product
    qs = (Product.objects
          .filter(is_active=True, min_quantity__gt=0, quantity__lte=F('min_quantity'))
          .select_related('unit')
          .order_by('quantity')[:15])

    if not qs:
        return _render_card('Малий залишок', '📦', _empty('Все добре, складу вистачає'))

    rows = []
    for p in qs:
        name = escape(p.name)
        qty = f'{p.quantity:.2f}'.rstrip('0').rstrip('.')
        minq = f'{p.min_quantity:.2f}'.rstrip('0').rstrip('.')
        unit = escape(p.unit.short if p.unit else '')
        critical = p.quantity <= 0
        cls = 'text-red-600 font-bold' if critical else 'text-orange-600'
        rows.append(f'''
          <tr class="border-b border-gray-100">
            <td class="py-2 px-2 text-sm">{name}</td>
            <td class="py-2 px-2 text-sm {cls}">{qty} {unit}</td>
            <td class="py-2 px-2 text-xs text-gray-400">мін {minq}</td>
          </tr>
        ''')

    body = f'<table class="w-full text-left">{("".join(rows))}</table>'
    return _render_card('Малий залишок', '📦', body)


@register(
    'list_overdue_vaccines',
    label='Прострочені вакцини', icon='💉', category='Списки',
    default_w=6, default_h=4, min_w=3, min_h=3,
    roles_allowed=ROLES_ALL,
)
def render_list_overdue_vaccines(request, config):
    from apps.clients.models import Vaccine
    today = timezone.localdate()
    qs = (Vaccine.objects
          .filter(next_date__lt=today)
          .select_related('patient', 'patient__client')
          .order_by('next_date')[:15])

    if not qs:
        return _render_card('Прострочені вакцини', '💉', _empty('Всі вакцини актуальні'))

    rows = []
    for v in qs:
        days = (today - v.next_date).days
        name = escape(v.name)
        patient = escape(v.patient.name if v.patient else '—')
        client = escape(str(v.patient.client) if v.patient and v.patient.client else '')
        rows.append(f'''
          <tr class="border-b border-gray-100">
            <td class="py-2 px-2 text-sm">{patient} <span class="text-xs text-gray-400">({client})</span></td>
            <td class="py-2 px-2 text-sm text-gray-600">{name}</td>
            <td class="py-2 px-2 text-xs text-red-600 whitespace-nowrap">{days} дн</td>
          </tr>
        ''')

    body = f'<table class="w-full text-left">{("".join(rows))}</table>'
    return _render_card('Прострочені вакцини', '💉', body)


@register(
    'list_recent_invoices',
    label='Останні чеки', icon='🧾', category='Списки',
    default_w=6, default_h=4, min_w=3, min_h=3,
    roles_allowed=ROLES_FIN,
    config_fields=[
        {'name': 'limit', 'label': 'К-сть', 'type': 'number', 'default': 8},
    ],
)
def render_list_recent_invoices(request, config):
    from apps.billing.models import Invoice
    limit = int((config or {}).get('limit', 8) or 8)
    qs = (Invoice.objects
          .filter(status=Invoice.Status.PAID)
          .select_related('client')
          .order_by('-created_at')[:limit])

    if not qs:
        return _render_card('Останні чеки', '🧾', _empty('Чеків ще немає'))

    rows = []
    for inv in qs:
        ts = timezone.localtime(inv.created_at).strftime('%d.%m %H:%M')
        client = escape(str(inv.client))
        method = escape(inv.get_payment_method_display() if inv.payment_method else '—')
        rows.append(f'''
          <tr class="border-b border-gray-100 hover:bg-gray-50">
            <td class="py-2 px-2 text-xs font-mono text-gray-500">#{inv.pk}</td>
            <td class="py-2 px-2 text-xs text-gray-500">{ts}</td>
            <td class="py-2 px-2 text-sm">{client}</td>
            <td class="py-2 px-2 text-xs text-gray-400">{method}</td>
            <td class="py-2 px-2 text-sm font-bold text-brand-gold whitespace-nowrap text-right">{_money(inv.total)}</td>
          </tr>
        ''')

    body = f'<table class="w-full text-left">{("".join(rows))}</table>'
    return _render_card('Останні чеки', '🧾', body)


@register(
    'list_top_services_month',
    label='Топ послуг (за к-стю)', icon='🏆', category='Списки',
    default_w=4, default_h=4, min_w=3, min_h=3,
    roles_allowed=ROLES_ALL,
    config_fields=[
        {'name': 'period', 'label': 'Період', 'type': 'select',
         'options': [('week', 'Тиждень'), ('month', 'Місяць')], 'default': 'month'},
    ],
)
def render_list_top_services_month(request, config):
    from apps.billing.models import InvoiceLine, Invoice
    period = (config or {}).get('period', 'month')
    start, end = _period_range(period)
    qs = (InvoiceLine.objects
          .filter(invoice__status=Invoice.Status.PAID,
                  invoice__created_at__range=(start, end),
                  line_type=InvoiceLine.LineType.SERVICE,
                  service__isnull=False)
          .values('service__name')
          .annotate(cnt=Sum('quantity'))
          .order_by('-cnt')[:5])

    if not qs:
        return _render_card('Топ послуг (к-сть)', '🏆', _empty('Поки що немає даних'))

    rows = []
    for i, row in enumerate(qs, 1):
        name = escape(row['service__name'] or 'Без назви')
        cnt = f"{row['cnt']:.0f}".rstrip('.')
        rows.append(f'''
          <li class="flex items-center justify-between py-2 border-b border-gray-100">
            <span class="text-sm"><span class="text-brand-gold font-bold mr-2">{i}.</span>{name}</span>
            <span class="text-sm font-mono text-gray-500">×{cnt}</span>
          </li>
        ''')
    body = f'<ul class="list-none">{("".join(rows))}</ul>'
    return _render_card('Топ послуг (за к-стю)', '🏆', body)


@register(
    'list_top_services_revenue',
    label='Топ послуг (за виручкою)', icon='💎', category='Списки',
    default_w=4, default_h=4, min_w=3, min_h=3,
    roles_allowed=ROLES_FIN,
    config_fields=[
        {'name': 'period', 'label': 'Період', 'type': 'select',
         'options': [('week', 'Тиждень'), ('month', 'Місяць')], 'default': 'month'},
    ],
)
def render_list_top_services_revenue(request, config):
    from apps.billing.models import InvoiceLine, Invoice
    period = (config or {}).get('period', 'month')
    start, end = _period_range(period)
    qs = (InvoiceLine.objects
          .filter(invoice__status=Invoice.Status.PAID,
                  invoice__created_at__range=(start, end),
                  line_type=InvoiceLine.LineType.SERVICE,
                  service__isnull=False)
          .values('service__name')
          .annotate(rev=Sum('total'))
          .order_by('-rev')[:5])

    if not qs:
        return _render_card('Топ послуг (виручка)', '💎', _empty('Поки що немає даних'))

    rows = []
    for i, row in enumerate(qs, 1):
        name = escape(row['service__name'] or 'Без назви')
        rev = _money(row['rev'])
        rows.append(f'''
          <li class="flex items-center justify-between py-2 border-b border-gray-100">
            <span class="text-sm"><span class="text-brand-gold font-bold mr-2">{i}.</span>{name}</span>
            <span class="text-sm font-bold text-brand-gold whitespace-nowrap">{rev}</span>
          </li>
        ''')
    body = f'<ul class="list-none">{("".join(rows))}</ul>'
    return _render_card('Топ послуг (за виручкою)', '💎', body)


@register(
    'list_debtors',
    label='Боржники', icon='⚠️', category='Списки',
    default_w=6, default_h=4, min_w=3, min_h=3,
    roles_allowed=ROLES_FIN,
)
def render_list_debtors(request, config):
    from apps.billing.models import Invoice
    qs = (Invoice.objects
          .filter(status=Invoice.Status.DRAFT, total__gt=0)
          .values('client__id', 'client__last_name', 'client__first_name')
          .annotate(debt=Sum('total'), cnt=Count('id'))
          .order_by('-debt')[:10])

    if not qs:
        return _render_card('Боржники', '⚠️', _empty('Боржників немає 🎉'))

    rows = []
    for row in qs:
        name = escape(f"{row['client__last_name']} {row['client__first_name']}".strip())
        debt = _money(row['debt'])
        cnt = row['cnt']
        rows.append(f'''
          <tr class="border-b border-gray-100">
            <td class="py-2 px-2 text-sm">{name}</td>
            <td class="py-2 px-2 text-xs text-gray-400">{cnt} чек(ів)</td>
            <td class="py-2 px-2 text-sm font-bold text-red-600 text-right whitespace-nowrap">{debt}</td>
          </tr>
        ''')
    body = f'<table class="w-full text-left">{("".join(rows))}</table>'
    return _render_card('Боржники', '⚠️', body)


# ======================================================================
# ГРАФІКИ (Chart.js)
# ======================================================================

@register(
    'chart_revenue_week',
    label='Виручка за 7 днів', icon='📊', category='Графіки',
    default_w=6, default_h=4, min_w=4, min_h=3,
    roles_allowed=ROLES_FIN,
)
def render_chart_revenue_week(request, config):
    from apps.billing.models import Invoice
    today = timezone.localdate()
    days = [today - timedelta(days=i) for i in range(6, -1, -1)]
    start_dt, end_dt = _period_range('week')

    raw = (Invoice.objects
           .filter(status=Invoice.Status.PAID,
                   created_at__range=(start_dt, end_dt))
           .annotate(d=TruncDate('created_at'))
           .values('d')
           .annotate(s=Sum('total'))
           .order_by('d'))
    by_day = {r['d']: float(r['s'] or 0) for r in raw}

    labels = [d.strftime('%d.%m') for d in days]
    data = [by_day.get(d, 0) for d in days]

    canvas_id = f'chart-rev-{_widget_id(config)}'
    chart_html = _chart(
        canvas_id, 'bar', labels,
        [{
            'label': 'Виручка, ₴',
            'data': data,
            'backgroundColor': '#c9a96e',
            'borderRadius': 6,
        }],
    )
    return _render_card('Виручка за 7 днів', '📊', chart_html)


@register(
    'chart_visits_per_doctor',
    label='Візити по лікарях', icon='🥧', category='Графіки',
    default_w=4, default_h=4, min_w=3, min_h=3,
    roles_allowed=ROLES_FIN,
    config_fields=[
        {'name': 'period', 'label': 'Період', 'type': 'select',
         'options': [('week', 'Тиждень'), ('month', 'Місяць')], 'default': 'week'},
    ],
)
def render_chart_visits_per_doctor(request, config):
    from apps.billing.models import Invoice
    period = (config or {}).get('period', 'week')
    start, end = _period_range(period)

    raw = (Invoice.objects
           .filter(status=Invoice.Status.PAID,
                   created_at__range=(start, end),
                   doctor__isnull=False)
           .values('doctor__id', 'doctor__first_name', 'doctor__last_name', 'doctor__username')
           .annotate(c=Count('id'))
           .order_by('-c')[:8])

    if not raw:
        return _render_card('Візити по лікарях', '🥧', _empty('Поки що немає даних'))

    labels = []
    data = []
    for r in raw:
        name = (f"{r['doctor__first_name']} {r['doctor__last_name']}".strip()
                or r['doctor__username'] or '—')
        labels.append(name)
        data.append(r['c'])

    palette = ['#c9a96e', '#8b7355', '#d4b896', '#a08960', '#6b5640',
               '#e8c89a', '#7a6447', '#bfa078']
    canvas_id = f'chart-doc-{_widget_id(config)}'
    chart_html = _chart(
        canvas_id, 'doughnut', labels,
        [{'data': data, 'backgroundColor': palette[:len(data)]}],
        options={
            'responsive': True, 'maintainAspectRatio': False,
            'plugins': {'legend': {'position': 'bottom', 'labels': {'boxWidth': 12, 'font': {'size': 11}}}},
        },
    )
    return _render_card('Візити по лікарях', '🥧', chart_html)


@register(
    'chart_appointments_week',
    label='Записи по днях', icon='📈', category='Графіки',
    default_w=6, default_h=4, min_w=4, min_h=3,
    roles_allowed=ROLES_ALL,
)
def render_chart_appointments_week(request, config):
    from apps.appointments.models import Appointment
    today = timezone.localdate()
    days = [today - timedelta(days=i) for i in range(6, -1, -1)]
    start_dt, end_dt = _period_range('week')

    raw = (Appointment.objects
           .filter(starts_at__range=(start_dt, end_dt))
           .annotate(d=TruncDate('starts_at'))
           .values('d')
           .annotate(c=Count('id'))
           .order_by('d'))
    by_day = {r['d']: r['c'] for r in raw}

    labels = [d.strftime('%d.%m') for d in days]
    data = [by_day.get(d, 0) for d in days]

    canvas_id = f'chart-appts-{_widget_id(config)}'
    chart_html = _chart(
        canvas_id, 'line', labels,
        [{
            'label': 'Записів',
            'data': data,
            'borderColor': '#c9a96e',
            'backgroundColor': 'rgba(201,169,110,0.18)',
            'tension': 0.3,
            'fill': True,
            'pointRadius': 4,
        }],
    )
    return _render_card('Записи по днях (тиждень)', '📈', chart_html)


# ======================================================================
# СИСТЕМНЕ
# ======================================================================

@register(
    'shifts_who_works_now',
    label='Хто на зміні', icon='🕐', category='Системне',
    default_w=4, default_h=2, min_w=2, min_h=2,
    roles_allowed=ROLES_ALL,
)
def render_shifts_who_works_now(request, config):
    from apps.accounts.models import Shift
    today = timezone.localdate()
    qs = (Shift.objects
          .filter(date=today)
          .select_related('user')
          .order_by('start_time'))

    if not qs:
        return _render_card('На зміні зараз', '🕐', _empty('Сьогодні зміни не відмічені'))

    items = []
    for s in qs:
        name = escape(s.user.get_full_name() or s.user.username)
        role = escape(s.user.get_role_display())
        if s.start_time and s.end_time:
            time_s = f'{s.start_time.strftime("%H:%M")}–{s.end_time.strftime("%H:%M")}'
        elif s.start_time:
            time_s = f'з {s.start_time.strftime("%H:%M")}'
        else:
            time_s = 'весь день'
        items.append(f'''
          <li class="flex items-center justify-between py-1.5 border-b border-gray-100 last:border-0">
            <div>
              <span class="text-sm font-medium">{name}</span>
              <span class="text-xs text-gray-400 ml-1">({role})</span>
            </div>
            <span class="text-xs font-mono text-brand-gold">{time_s}</span>
          </li>
        ''')
    body = f'<ul class="list-none">{("".join(items))}</ul>'
    return _render_card('На зміні сьогодні', '🕐', body)


@register(
    'quick_actions',
    label='Швидкі дії', icon='⚡', category='Системне',
    default_w=4, default_h=2, min_w=2, min_h=2,
    roles_allowed=ROLES_ALL,
)
def render_quick_actions(request, config):
    """Прямі лінки на створення сутностей. URL-імена резолвимо безпечно."""
    from django.urls import reverse, NoReverseMatch

    def _safe(name, fallback='#'):
        try:
            return reverse(name)
        except NoReverseMatch:
            return fallback

    actions = [
        ('📅', 'Запис', _safe('appointments:create'), ROLES_ALL),
        ('🧾', 'Чек', _safe('billing:create'), ROLES_FIN),
        ('👤', 'Клієнт', _safe('clients:create'), ROLES_ALL),
    ]

    user_role = getattr(request.user, 'role', None) if request.user.is_authenticated else None
    btns = []
    for icon, label, url, roles in actions:
        if user_role and user_role not in roles:
            continue
        btns.append(f'''
          <a href="{escape(url)}"
             class="flex flex-col items-center justify-center bg-brand-cream hover:bg-brand-gold/20
                    border border-gray-200 rounded-lg p-3 text-center transition group">
            <span class="text-2xl mb-1">{icon}</span>
            <span class="text-xs font-medium text-brand-dark group-hover:text-brand-gold">+ {escape(label)}</span>
          </a>
        ''')

    body = f'<div class="grid grid-cols-3 gap-2">{("".join(btns))}</div>'
    return _render_card('Швидкі дії', '⚡', body)


# ======================================================================
# КАТЕГОРІЇ ДЛЯ UI (опційно — backend може використати для групування)
# ======================================================================

CATEGORIES = ['KPI', 'Списки', 'Графіки', 'Системне']


def list_widgets_for_role(role):
    """Хелпер для backend agent: повертає віджети, доступні для ролі."""
    return {
        k: v for k, v in WIDGETS.items()
        if not role or role in v.get('roles_allowed', ROLES_ALL)
    }
