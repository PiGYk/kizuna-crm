import logging
from decimal import Decimal, InvalidOperation


def _parse_decimal(raw, default):
    """Толерантний парсинг для мобільних клавіатур: кома → крапка, пробіли, NBSP."""
    if raw is None:
        return default
    s = str(raw).strip().replace(' ', '').replace(' ', '').replace(',', '.')
    if not s:
        return default
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return default

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Prefetch, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

logger = logging.getLogger(__name__)

from apps.clients.models import Client, Patient
from apps.inventory.models import Product, StockMovement
from apps.services.models import Service
from apps.tg.utils import is_mobile

from .models import Invoice, InvoiceLine
from .payments import add_payment, parse_payment_rows, pay_rest
from . import deposits


def _lines_render(request, invoice):
    """Render lines partial — обирає mobile або desktop варіант за UA."""
    template = 'billing/partials/mobile_lines.html' if is_mobile(request) else 'billing/partials/lines_table.html'
    return render(request, template, _lines_context(invoice))


def _lines_context(invoice):
    """Контекст для partial lines_table — top-level рядки з prefetch дітей."""
    from django.db.models import Sum
    lines = list(
        invoice.lines
        .filter(parent_line__isnull=True)
        .select_related('service', 'product', 'product__unit')
        .prefetch_related(
            Prefetch(
                'children',
                queryset=InvoiceLine.objects.select_related('product', 'product__unit'),
            )
        )
    )
    subtotal = invoice.lines.filter(parent_line__isnull=True).aggregate(s=Sum('total'))['s'] or Decimal('0')
    if invoice.discount_type == Invoice.DiscountType.PERCENT:
        discount_amt = subtotal * invoice.discount / Decimal('100')
    else:
        discount_amt = invoice.discount
    has_vaccination = any(
        l.line_type == 'service' and l.service and 'вакцинац' in l.service.name.lower()
        for l in lines
    )
    vaccine_products = []
    vaccine_in_invoice = set()
    if has_vaccination:
        vaccine_products = list(
            Product.objects.filter(category__name='Вакцини', is_active=True, organization=invoice.organization).order_by('name')
        )
        vaccine_in_invoice = set(
            invoice.lines.filter(
                product__category__name='Вакцини', unit_price=0, parent_line__isnull=True
            ).values_list('product_id', flat=True)
        )
    return {
        'invoice': invoice,
        'lines': lines,
        'subtotal': subtotal,
        'discount_amt': discount_amt,
        'has_vaccination': has_vaccination,
        'vaccine_products': vaccine_products,
        'vaccine_in_invoice': vaccine_in_invoice,
    }


# ── список рахунків ──────────────────────────────────────────────────────────

def _only_own_invoices(request):
    """«Рахунки (всі)» у «Доступі до меню»: без цієї галочки роль бачить лише свої рахунки.
    До 01.11.2026 так було завжди й лише для лікаря, а галочка нічого не робила."""
    org = request.organization
    return (not request.user.is_admin() and org is not None
            and not org.can_see_menu(request.user.role, 'billing'))


def dostupni_rakhunky(request, qs=None):
    """Рахунки, які ця людина може відкрити й чіпати. Без «Рахунки (всі)» — лише свої: де вона лікар АБО які створила
    сама (лікарі Kizuna створюють рахунок на лікаря за замовчуванням — з 01.10 так 62 з 62). Один набір і для списку,
    і для кожної дії за номером: до 27.11.2026 список ховав чужі, а відкриття, правка, оплата й PDF брали будь-який
    рахунок клініки за адресою (Ревізор, №867)."""
    if qs is None:
        qs = Invoice.objects.all()
    qs = qs.filter(organization=request.organization)
    if _only_own_invoices(request):
        qs = qs.filter(Q(doctor=request.user) | Q(created_by=request.user))
    return qs


# Кнопки періоду над списком (16.11.2026, ANVAR): «Рахунки» відкриваються за сьогодні.
# ключ → (підпис кнопки, днів разом із сьогоднішнім, підпис біля лічильника)
INVOICE_PERIODS = {
    'today': ('Сьогодні', 1, 'за сьогодні'),
    '3d': ('3 дні', 3, 'за 3 дні'),
    '7d': ('7 днів', 7, 'за 7 днів'),
    'month': ('Місяць', 30, 'за місяць'),
    'year': ('Рік', 365, 'за рік'),
    'all': ('Увесь час', None, 'всього'),
}


def _invoice_period(request, q, date_from, date_to):
    """Діючий період: свої дати «від/до» важливіші за кнопки; без кнопки — сьогодні,
    а пошук без кнопки шукає за весь час (старий рахунок клієнта мусить знаходитись)."""
    chosen = request.GET.get('period', '')
    if chosen not in INVOICE_PERIODS:
        chosen = ''
    if date_from or date_to:
        return '', chosen
    return chosen or ('all' if q else 'today'), chosen


@login_required
def invoice_list(request):
    from datetime import datetime, time, timedelta
    from django.core.paginator import Paginator
    from django.db.models import Sum
    from django.utils import timezone

    base = Invoice.objects.select_related('client', 'patient', 'doctor').filter(
        organization=request.organization
    )
    # без «Рахунки (всі)» — лише свої: лікар або сам створив
    only_own = _only_own_invoices(request)
    base = dostupni_rakhunky(request, base)

    q = request.GET.get('q', '').strip()
    payment = request.GET.get('payment', '')
    status = request.GET.get('status', '')
    doctor_id = request.GET.get('doctor', '')
    date_from = request.GET.get('from', '')
    date_to = request.GET.get('to', '')
    sort = request.GET.get('sort', '-created_at')
    try:
        per_page = int(request.GET.get('per_page', '50'))
    except (TypeError, ValueError):
        per_page = 50
    if per_page not in (25, 50, 100):
        per_page = 50

    filtered = base
    if q:
        cond = (
            Q(client__last_name__icontains=q)
            | Q(client__first_name__icontains=q)
            | Q(client__phone__icontains=q)
            | Q(patient__name__icontains=q)
        )
        if q.lstrip('#').isdigit():
            cond = cond | Q(pk=int(q.lstrip('#')))
        filtered = filtered.filter(cond)
    if payment in Invoice.PaymentMethod.values:
        filtered = filtered.filter(payment_method=payment)
    if status in Invoice.Status.values:
        filtered = filtered.filter(status=status)
    if doctor_id:
        try:
            filtered = filtered.filter(doctor_id=int(doctor_id))
        except (TypeError, ValueError):
            doctor_id = ''
    if date_from:
        try:
            df = datetime.combine(datetime.fromisoformat(date_from).date(), time.min)
            filtered = filtered.filter(created_at__gte=df)
        except ValueError:
            date_from = ''
    if date_to:
        try:
            dt = datetime.combine(datetime.fromisoformat(date_to).date(), time.max)
            filtered = filtered.filter(created_at__lte=dt)
        except ValueError:
            date_to = ''

    period, period_chosen = _invoice_period(request, q, date_from, date_to)
    period_range = ''
    if period and period != 'all':
        today = timezone.localdate()
        start = today - timedelta(days=INVOICE_PERIODS[period][1] - 1)
        filtered = filtered.filter(created_at__gte=timezone.make_aware(datetime.combine(start, time.min)))
        if start == today:
            period_range = f'{today:%d.%m.%Y}'
        elif start.year == today.year:
            period_range = f'{start:%d.%m} – {today:%d.%m.%Y}'
        else:
            period_range = f'{start:%d.%m.%Y} – {today:%d.%m.%Y}'
    # посилання кнопок: решта фільтрів лишається, свої дати й сторінка — ні
    keep = request.GET.copy()
    for k in ('page', 'from', 'to', 'period'):
        keep.pop(k, None)
    period_links = []
    for key, (label, _days, _caption) in INVOICE_PERIODS.items():
        keep['period'] = key
        period_links.append({'key': key, 'label': label, 'qs': keep.urlencode(), 'active': key == period})
    qs_no_page = request.GET.copy()
    qs_no_page.pop('page', None)

    sort_allowed = {'-created_at', 'created_at', '-total', 'total', '-pk', 'pk'}
    if sort not in sort_allowed:
        sort = '-created_at'
    invoices_qs = filtered.order_by(sort)

    # ── KPI aggregates over filtered set ───────────────────────────────────
    paid_qs = filtered.filter(status=Invoice.Status.PAID)
    paid_agg = paid_qs.aggregate(s=Sum('total'))
    paid_sum = paid_agg['s'] or 0
    paid_count = paid_qs.count()
    avg_check = (paid_sum / paid_count) if paid_count else 0
    cutoff = timezone.now() - timedelta(hours=24)
    debtor_count = base.filter(status=Invoice.Status.DRAFT, created_at__lt=cutoff).count()

    total_count = filtered.count()

    doctors = []
    if request.user.is_admin():
        from apps.accounts.models import User as UserModel
        doctors = UserModel.objects.filter(
            organization=request.organization,
            role__in=(UserModel.Role.DOCTOR, UserModel.Role.ADMIN, UserModel.Role.ASSISTANT, UserModel.Role.RECEPTION),
        ).order_by('first_name', 'last_name', 'username')

    paginator = Paginator(invoices_qs, per_page)
    page = paginator.get_page(request.GET.get('page', 1))

    template = 'billing/list_mobile.html' if is_mobile(request) else 'billing/list.html'
    return render(request, template, {
        'invoices': page,
        'payment_filter': payment,
        'only_own': only_own,
        'status_filter': status,
        'doctor_filter': doctor_id,
        'q': q,
        'date_from': date_from,
        'date_to': date_to,
        'per_page': per_page,
        'sort': sort,
        'kpi': {
            'paid_sum': paid_sum,
            'paid_count': paid_count,
            'avg_check': avg_check,
            'debtor_count': debtor_count,
        },
        'doctors': doctors,
        'total_count': total_count,
        'overdue_cutoff': cutoff,
        'has_active_filter': bool(q or payment or status or doctor_id or date_from or date_to),
        'period': period,
        'period_chosen': period_chosen,
        'period_links': period_links,
        'period_all_qs': next(p['qs'] for p in period_links if p['key'] == 'all'),
        'period_range': period_range,
        'period_caption': INVOICE_PERIODS[period][2] if period else 'за період',
        'qs_no_page': qs_no_page.urlencode(),
    })


# ── новий рахунок: вибір клієнта ────────────────────────────────────────────

@login_required
def invoice_create(request):
    if request.method == 'POST':
        client_id = request.POST.get('client_id')
        patient_id = request.POST.get('patient_id') or None
        client = get_object_or_404(Client, pk=client_id)
        patient = get_object_or_404(Patient, pk=patient_id) if patient_id else None
        org = request.organization
        default_doc = org.get_default_doctor(request.user) if org else request.user
        # Персональна знижка клієнта
        client_discount = client.discount_percent or 0
        invoice = Invoice.objects.create(
            client=client,
            patient=patient,
            doctor=default_doc,
            created_by=request.user,
            organization=org,
            discount=client_discount,
            discount_type=Invoice.DiscountType.PERCENT,
        )
        return redirect('billing:edit', pk=invoice.pk)

    # Недавні клієнти: топ-5 за останніми рахунками (60 днів)
    from datetime import timedelta
    from django.utils import timezone
    recent_cutoff = timezone.now() - timedelta(days=60)
    recent_qs = (
        Invoice.objects
        .filter(organization=request.organization, created_at__gte=recent_cutoff)
        .values('client_id').distinct()
        .order_by('-created_at')[:20]
    )
    recent_client_ids = [r['client_id'] for r in recent_qs][:5]
    recent_clients = []
    if recent_client_ids:
        cmap = {c.pk: c for c in Client.objects.filter(pk__in=recent_client_ids)}
        recent_clients = [cmap[pk] for pk in recent_client_ids if pk in cmap]

    # Кнопка «Новий чек» у картці тварини веде сюди з ?patient=<id>.
    # Раніше параметр ігнорувався і тварину доводилось шукати руками —
    # тепер вона одразу підставлена (скарга персоналу 26.07).
    preselect_patient = None
    patient_pk = request.GET.get('patient')
    if patient_pk:
        preselect_patient = (
            Patient.objects
            .select_related('client')
            .filter(pk=patient_pk, client__organization=request.organization)
            .first()
        )

    template = 'billing/create_mobile.html' if is_mobile(request) else 'billing/create.html'
    return render(request, template, {
        'recent_clients': recent_clients,
        'preselect_patient': preselect_patient,
    })


# ── HTMX: пошук клієнтів при створенні рахунку ──────────────────────────────

@login_required
def client_search(request):
    q = request.GET.get('q', '').strip()
    clients = []
    if len(q) >= 2:
        clients = Client.objects.filter(
            Q(last_name__icontains=q) |
            Q(first_name__icontains=q) |
            Q(phone__icontains=q),
            organization=request.organization,
        )[:10]
    mobile = request.GET.get('mobile') == '1' or is_mobile(request)
    template = 'billing/partials/mobile_client_results.html' if mobile else 'billing/partials/client_results.html'
    return render(request, template, {'clients': clients, 'q': q})


# ── HTMX: пошук пацієнтів по кличці ────────────────────────────────────────

@login_required
def patient_search(request):
    q = request.GET.get('q', '').strip()
    patients = []
    if q:
        patients = Patient.objects.select_related('client').filter(
            Q(name__icontains=q) |
            Q(breed__icontains=q),
            client__organization=request.organization,
            is_archived=False,
        )[:10]
    mobile = request.GET.get('mobile') == '1' or is_mobile(request)
    template = 'billing/partials/mobile_patient_search_results.html' if mobile else 'billing/partials/patient_search_results.html'
    return render(request, template, {'patients': patients, 'q': q})


# ── HTMX: пацієнти клієнта ──────────────────────────────────────────────────

@login_required
def patient_list(request, client_id):
    client = get_object_or_404(Client, pk=client_id)
    patients = client.patients.filter(is_archived=False)
    mobile = request.GET.get('mobile') == '1' or is_mobile(request)
    template = 'billing/partials/mobile_patient_list.html' if mobile else 'billing/partials/patient_list.html'
    return render(request, template, {'client': client, 'patients': patients})


# ── редагування рахунку (основна сторінка checkout) ─────────────────────────

def _today_appointment(invoice):
    """Запис календаря на сьогодні для тварини цього чека — для мʼякої підказки.

    Саме підказка, не гейт: 85% чеків узагалі не мають запису (люди приходять
    з вулиці, беруть корм), тому заборона «чек лише після закритого запису»
    зупинила б чотири чеки з пʼяти.
    """
    if not invoice.patient_id:
        return None
    from apps.appointments.models import Appointment
    from django.utils import timezone
    return (
        Appointment.objects
        .filter(
            patient_id=invoice.patient_id,
            organization_id=invoice.organization_id,
            starts_at__date=timezone.localdate(),
        )
        .exclude(status__in=[Appointment.Status.CANCELLED, Appointment.Status.NO_SHOW])
        .prefetch_related('visits')
        .order_by('starts_at')
        .first()
    )


def _payments_of(invoice):
    from .models import InvoicePayment
    return list(InvoicePayment._base_manager.filter(invoice=invoice).select_related('created_by'))


@login_required
def invoice_edit(request, pk):
    invoice = get_object_or_404(dostupni_rakhunky(request), pk=pk)
    if invoice.status != Invoice.Status.DRAFT:
        return redirect('billing:detail', pk=pk)

    org = request.organization
    services = Service.objects.filter(organization=org, is_active=True).order_by('name')
    products = Product.objects.filter(organization=org, is_active=True).order_by('name')
    ctx = _lines_context(invoice)
    ctx['services'] = services
    ctx['products'] = products
    appt = _today_appointment(invoice)
    ctx['today_appointment'] = appt
    ctx['today_appointment_visit'] = appt.visits.first() if appt else None
    ctx['payments'] = _payments_of(invoice)
    ctx['client_deposit'] = deposits.balance(invoice.client)
    template = 'billing/edit_mobile.html' if is_mobile(request) else 'billing/edit.html'
    return render(request, template, ctx)


# ── HTMX: додати рядок ──────────────────────────────────────────────────────

@login_required
@require_POST
def add_line(request, pk):
    invoice = get_object_or_404(dostupni_rakhunky(request), pk=pk, status=Invoice.Status.DRAFT)
    line_type = request.POST.get('line_type')

    if line_type == 'service':
        service_id = request.POST.get('service_id')
        if not service_id:
            return HttpResponse(status=400)
        service = get_object_or_404(Service, pk=service_id)
        qty = _parse_decimal(request.POST.get('quantity'), Decimal('1'))
        discount = _parse_decimal(request.POST.get('discount'), Decimal('0'))
        discount_type = request.POST.get('discount_type', Invoice.DiscountType.PERCENT)
        line = InvoiceLine(
            invoice=invoice,
            line_type='service',
            service=service,
            name=service.name,
            quantity=qty,
            unit_price=service.price,
            discount=discount,
            discount_type=discount_type,
        )
        line.save()

        # Автоматично додаємо компоненти послуги як дочірні рядки (ціна 0)
        for comp in service.components.select_related('product').all():
            InvoiceLine.objects.create(
                invoice=invoice,
                parent_line=line,
                line_type='product',
                product=comp.product,
                name=comp.product.name,
                quantity=comp.quantity * qty,
                unit_price=Decimal('0'),
            )

    elif line_type == 'product':
        product_id = request.POST.get('product_id')
        if not product_id:
            return HttpResponse(status=400)
        product = get_object_or_404(Product, pk=product_id)
        qty = _parse_decimal(request.POST.get('quantity'), Decimal('1'))
        discount = _parse_decimal(request.POST.get('discount'), Decimal('0'))
        discount_type = request.POST.get('discount_type', Invoice.DiscountType.PERCENT)
        line = InvoiceLine(
            invoice=invoice,
            line_type='product',
            product=product,
            name=product.name,
            quantity=qty,
            unit_price=product.sell_price,
            discount=discount,
            discount_type=discount_type,
        )
        line.save()

    invoice.save_total()
    return _lines_render(request, invoice)


# ── HTMX: додати компонент (препарат) до послуги в чеку ─────────────────────

@login_required
@require_POST
def add_component(request, pk, line_id):
    """Додає препарат зі складу як дочірній рядок до послуги (ціна 0)."""
    invoice = get_object_or_404(dostupni_rakhunky(request), pk=pk, status=Invoice.Status.DRAFT)
    parent = get_object_or_404(InvoiceLine, pk=line_id, invoice=invoice, line_type='service')

    product_id = request.POST.get('product_id')
    if not product_id:
        return _lines_render(request, invoice)

    product = get_object_or_404(Product, pk=product_id, organization=request.organization)
    qty = _parse_decimal(request.POST.get('quantity'), Decimal('1'))

    InvoiceLine.objects.create(
        invoice=invoice,
        parent_line=parent,
        line_type='product',
        product=product,
        name=product.name,
        quantity=qty,
        unit_price=Decimal('0'),
    )

    invoice.save_total()
    return _lines_render(request, invoice)


# ── HTMX: оновити ціну / кількість рядка ────────────────────────────────────

@login_required
@require_POST
def update_line(request, pk, line_id):
    invoice = get_object_or_404(dostupni_rakhunky(request), pk=pk, status=Invoice.Status.DRAFT)
    line = get_object_or_404(InvoiceLine, pk=line_id, invoice=invoice)
    line.unit_price = _parse_decimal(request.POST.get('unit_price'), line.unit_price)
    line.quantity = _parse_decimal(request.POST.get('quantity'), line.quantity)
    line.save()
    invoice.save_total()
    return _lines_render(request, invoice)


# ── HTMX: видалити рядок ────────────────────────────────────────────────────

@login_required
@require_POST
def remove_line(request, pk, line_id):
    invoice = get_object_or_404(dostupni_rakhunky(request), pk=pk, status=Invoice.Status.DRAFT)
    line = get_object_or_404(InvoiceLine, pk=line_id, invoice=invoice)
    line.delete()
    invoice.save_total()
    return _lines_render(request, invoice)


# ── HTMX: оновити знижку на рахунок ─────────────────────────────────────────

@login_required
@require_POST
def update_discount(request, pk):
    invoice = get_object_or_404(dostupni_rakhunky(request), pk=pk, status=Invoice.Status.DRAFT)
    invoice.discount = _parse_decimal(request.POST.get('discount'), Decimal('0'))
    invoice.discount_type = request.POST.get('discount_type', Invoice.DiscountType.PERCENT)
    invoice.notes = request.POST.get('notes', '')
    invoice.save(update_fields=['discount', 'discount_type', 'notes'])
    invoice.save_total()
    return _lines_render(request, invoice)


# ── HTMX: перемикач вакцини (додати/видалити з ціною 0) ─────────────────────

@login_required
@require_POST
def toggle_vaccine(request, pk):
    invoice = get_object_or_404(dostupni_rakhunky(request), pk=pk, status=Invoice.Status.DRAFT)
    product_id = request.POST.get('product_id')
    checked = request.POST.get('checked') == 'true'
    product = get_object_or_404(Product, pk=product_id, category__name='Вакцини')

    if checked:
        if not invoice.lines.filter(product=product, unit_price=0).exists():
            InvoiceLine.objects.create(
                invoice=invoice,
                line_type=InvoiceLine.LineType.PRODUCT,
                product=product,
                name=product.name,
                quantity=Decimal('1'),
                unit_price=Decimal('0'),
            )
    else:
        invoice.lines.filter(product=product, unit_price=0).delete()

    invoice.save_total()
    return _lines_render(request, invoice)


# ── JSON-пошук послуг і товарів ─────────────────────────────────────────────

@login_required
def service_search_json(request):
    q = request.GET.get('q', '').strip()
    qs = Service.objects.filter(organization=request.organization, is_active=True).order_by('name')
    if q:
        from django.db.models import Q
        qs = qs.filter(Q(name__icontains=q) | Q(code__icontains=q))
    qs = qs.prefetch_related('components__product__unit')[:25]
    return JsonResponse({'results': [
        {
            'id': s.pk,
            'name': s.name,
            'code': s.code,
            'price': str(s.price),
            'components': [
                {
                    'name': c.product.name,
                    'qty': str(c.quantity),
                    'unit': c.product.unit.short if c.product.unit else '',
                }
                for c in s.components.all()
            ],
        }
        for s in qs
    ]})


@login_required
def product_search_json(request):
    q = request.GET.get('q', '').strip()
    qs = Product.objects.filter(organization=request.organization, is_active=True).order_by('name')
    if q:
        qs = qs.filter(name__icontains=q)
    qs = qs[:25]
    return JsonResponse({'results': [
        {'id': p.pk, 'name': p.name, 'price': str(p.sell_price),
         'qty': str(p.quantity), 'unit': p.unit.name if p.unit else ''} for p in qs
    ]})


# ── Оплатити (фіналізувати) ──────────────────────────────────────────────────

@login_required
@require_POST
@transaction.atomic
def pay_invoice(request, pk):
    """Оплата рахунку (ANVAR 01.11.2026): кілька рядків «спосіб + сума» (pay_method / pay_amount).
    action=close — закрити рахунок (склад списується; недоплачене стає боргом клієнта);
    action=keep_open — лише внести оплату (аванс), рахунок лишається відкритим.
    Стара форма з одним payment_method — оплата всього залишку цим способом."""
    invoice = get_object_or_404(dostupni_rakhunky(request), pk=pk, status=Invoice.Status.DRAFT)
    invoice.refresh_paid()
    try:
        rows = parse_payment_rows(request.POST)
        deposits.check_rows(invoice.client, rows)
    except ValueError as exc:
        messages.error(request, f'Оплата не прийнята: {exc}.')
        return redirect('billing:edit', pk=pk)
    if not rows and 'pay_method' not in request.POST:
        method = request.POST.get('payment_method', Invoice.PaymentMethod.CASH)
        if method not in (Invoice.PaymentMethod.CASH, Invoice.PaymentMethod.CARD, Invoice.PaymentMethod.TRANSFER):
            method = Invoice.PaymentMethod.CASH
        if invoice.balance_due > 0:
            rows = [(method, invoice.balance_due)]
    paying = sum((amount for _, amount in rows), Decimal('0'))
    if paying > invoice.balance_due:
        messages.error(request, f'Платежі ({paying} ₴) більші за залишок до сплати ({invoice.balance_due} ₴).')
        return redirect('billing:edit', pk=pk)

    if request.POST.get('action') == 'keep_open':
        if invoice.fiscal_status == Invoice.FiscalStatus.PENDING:
            # на терміналі висить QR — аванс зверху міг би дати переплату
            messages.error(request, f'Клієнт зараз оплачує {invoice.qr_amount or invoice.balance_due} ₴ за QR-кодом — аванс не вноситься. Скасуйте очікування оплати або дочекайтесь її.')
            return redirect('billing:edit', pk=pk)
        if not rows:
            messages.error(request, 'Вкажіть суму, яку внесли.')
            return redirect('billing:edit', pk=pk)
        for method, amount in rows:
            add_payment(invoice, amount, method, request.user)
        messages.success(request, f'Внесено {paying} ₴. Рахунок відкритий, до сплати ще {invoice.balance_due} ₴.')
        return redirect('billing:edit', pk=pk)

    # QR на всю суму ще чекає оплати (19.11.2026: 55 рахунків закрили «Оплатити» з QR, що висів, і 3 з них
    # клієнт таки оплатив за QR — гроші прийшли, а чека нема). Спершу питаємо Checkbox.
    if invoice.fiscal_status == Invoice.FiscalStatus.PENDING and invoice.fiscal_receipt_id:
        qr = _settle_pending_qr(request.organization, invoice)
        if qr == 'paid':
            messages.error(request, _QR_MSG[qr])
            return redirect('billing:edit', pk=pk)
        if qr == 'error':
            # «Оплатити» не блокуємо (01.11: цим шляхом закривали рахунки з живим QR десятки разів) — лише попереджаємо
            messages.warning(request, _QR_MSG['unknown'])

    try:
        _writeoff_stock(invoice, request.user)
    except InsufficientStockError as exc:
        transaction.set_rollback(True)
        messages.error(
            request,
            'Недостатньо залишку: ' + '; '.join(exc.items)
            + '. Поповніть склад або приберіть позиції перед оплатою.'
        )
        return redirect('billing:edit', pk=pk)

    for method, amount in rows:
        add_payment(invoice, amount, method, request.user)
    invoice.status = Invoice.Status.PAID
    if not invoice.payment_method:
        invoice.payment_method = rows[0][0] if rows else Invoice.PaymentMethod.CASH
    invoice.save(update_fields=['status', 'payment_method'])
    invoice.refresh_paid()
    if invoice.has_debt:
        messages.warning(request, f'Рахунок закрито з боргом {invoice.balance_due} ₴ — він у розділі «Боржники».')
    return redirect('billing:detail', pk=pk)


@login_required
@require_POST
@transaction.atomic
def pay_debt(request, pk):
    """Погасити борг за закритим рахунком — повністю або частинами, будь-яким способом."""
    invoice = get_object_or_404(dostupni_rakhunky(request), pk=pk, status=Invoice.Status.PAID)
    invoice.refresh_paid()
    try:
        rows = parse_payment_rows(request.POST)
        deposits.check_rows(invoice.client, rows)
    except ValueError as exc:
        messages.error(request, f'Оплата не прийнята: {exc}.')
        return redirect('billing:detail', pk=pk)
    # на частину боргу висить QR (Олег 19.11.2026) — клієнт уже заплатив: спершу «Перевірити оплату», інакше чека не буде
    if invoice.fiscal_status == Invoice.FiscalStatus.PENDING and invoice.fiscal_receipt_id:
        qr = _settle_pending_qr(request.organization, invoice)
        if qr == 'paid':
            messages.error(request, _QR_MSG[qr])
            return redirect('billing:detail', pk=pk)
        if qr == 'error':
            messages.warning(request, _QR_MSG['unknown'])
    paying = sum((amount for _, amount in rows), Decimal('0'))
    if not rows:
        messages.error(request, 'Вкажіть суму.')
    elif paying > invoice.balance_due:
        messages.error(request, f'Платежі ({paying} ₴) більші за борг ({invoice.balance_due} ₴).')
    else:
        for method, amount in rows:
            add_payment(invoice, amount, method, request.user)
        messages.success(request, 'Борг погашено.' if not invoice.has_debt
                         else f'Внесено {paying} ₴, борг ще {invoice.balance_due} ₴.')
    return redirect('billing:detail', pk=pk)


@login_required
@require_POST
@transaction.atomic
def delete_payment(request, pk, payment_id):
    """Прибрати помилковий платіж (лише адміністратор): сума повертається в борг / до сплати."""
    from .models import InvoicePayment
    invoice = get_object_or_404(dostupni_rakhunky(request), pk=pk)
    if not request.user.is_admin():
        messages.error(request, 'Платежі прибирає лише адміністратор.')
    else:
        gone = InvoicePayment._base_manager.filter(pk=payment_id, invoice=invoice)
        had_receipt = gone.exclude(fiscal_receipt_id__isnull=True).exclude(fiscal_receipt_id='').exists()
        gone.delete()
        invoice.refresh_paid()
        messages.success(request, 'Платіж прибрано.' + (' Його фіскальний чек лишається в ДПС — за потреби зробіть '
                                                       'чек повернення в Checkbox.' if had_receipt else ''))
    return redirect('billing:detail' if invoice.status == Invoice.Status.PAID else 'billing:edit', pk=pk)


# ── детальний вигляд (рецепт/чек) ───────────────────────────────────────────

@login_required
def invoice_detail(request, pk):
    invoice = get_object_or_404(dostupni_rakhunky(request), pk=pk)
    lines = invoice.lines.select_related('service', 'product').all()

    base_nav = dostupni_rakhunky(request)
    prev_invoice = base_nav.filter(pk__lt=invoice.pk).order_by('-pk').values_list('pk', flat=True).first()
    next_invoice = base_nav.filter(pk__gt=invoice.pk).order_by('pk').values_list('pk', flat=True).first()

    template = 'billing/detail_mobile.html' if is_mobile(request) else 'billing/detail.html'
    return render(request, template, {
        'invoice': invoice,
        'lines': lines,
        'prev_pk': prev_invoice,
        'next_pk': next_invoice,
        'payments': _payments_of(invoice),
        'client_deposit': deposits.balance(invoice.client) if invoice.has_debt else 0,
    })


# ── скасувати рахунок ────────────────────────────────────────────────────────

@login_required
@require_POST
def cancel_invoice(request, pk):
    invoice = get_object_or_404(dostupni_rakhunky(request), pk=pk, status=Invoice.Status.DRAFT)
    if invoice.amount_paid > 0:
        messages.error(request, f'На рахунку внесено {invoice.amount_paid} ₴ — спершу приберіть платежі (поверніть гроші клієнту).')
        return redirect('billing:edit', pk=pk)
    invoice.status = Invoice.Status.CANCELLED
    invoice.save(update_fields=['status'])
    return redirect('billing:list')


# ── видалити рахунок ─────────────────────────────────────────────────────────
# DRAFT / CANCELLED — будь-який користувач
# PAID — тільки admin; два режими: з поверненням або без

@login_required
@require_POST
def delete_invoice(request, pk):
    from django.contrib import messages

    invoice = get_object_or_404(dostupni_rakhunky(request), pk=pk)

    if invoice.status in (Invoice.Status.DRAFT, Invoice.Status.CANCELLED):
        if invoice.amount_paid > 0:
            messages.error(request, f'На рахунку внесено {invoice.amount_paid} ₴ — спершу приберіть платежі (поверніть гроші клієнту).')
            return redirect('billing:edit', pk=pk)
        invoice.delete()
        return redirect('billing:list')

    if invoice.status == Invoice.Status.PAID:
        if not request.user.is_admin():
            messages.error(request, 'Тільки адміністратор може видаляти оплачені рахунки')
            return redirect('billing:detail', pk=pk)

        restore = request.POST.get('restore')
        if restore not in ('yes', 'no'):
            messages.error(request, 'Оберіть режим видалення: з поверненням чи без.')
            return redirect('billing:detail', pk=pk)

        fiscal_note = ' Фіскальний чек Checkbox лишається в ДПС.' if invoice.fiscal_status == Invoice.FiscalStatus.SENT else ''
        invoice_id = invoice.pk

        if restore == 'yes':
            _restore_stock_from_invoice(invoice, request.user)
            invoice.delete()
            messages.success(
                request,
                f'Рахунок #{invoice_id} видалено. Товари повернуто на склад.{fiscal_note}'
            )
        else:
            invoice.delete()
            messages.success(
                request,
                f'Рахунок #{invoice_id} видалено. Товари на склад НЕ повернуто.{fiscal_note}'
            )
        return redirect('billing:list')

    return redirect('billing:detail', pk=pk)


def _restore_stock_from_invoice(invoice, user):
    """Повертає на склад товари зі списаних рядків рахунку (компенсуючий прихід IN)."""
    lines = invoice.lines.filter(line_type='product', stock_written_off=True).select_related('product')
    for line in lines:
        if line.product and line.quantity > 0:
            StockMovement.objects.create(
                product=line.product,
                type=StockMovement.Type.IN,
                quantity=line.quantity,
                reason=f'Повернення з рахунку #{invoice.pk} (скасовано)',
                created_by=user,
            )


# ── змінити спосіб оплати на оплаченому рахунку ─────────────────────────────

@login_required
@require_POST
def update_payment_method(request, pk):
    invoice = get_object_or_404(dostupni_rakhunky(request), pk=pk, status=Invoice.Status.PAID)
    method = request.POST.get('payment_method')
    # лише готівка / картка / переказ: перемикач на «з депозиту» обійшов би перевірку залишку депозиту
    if method in (Invoice.PaymentMethod.CASH, Invoice.PaymentMethod.CARD, Invoice.PaymentMethod.TRANSFER):
        from .models import InvoicePayment
        pays = list(InvoicePayment._base_manager.filter(invoice=invoice))
        if len(pays) > 1:
            messages.error(request, 'Оплата з кількох платежів — змініть спосіб у самих платежах.')
            return redirect('billing:detail', pk=pk)
        if pays and pays[0].method == Invoice.PaymentMethod.DEPOSIT:
            messages.error(request, 'Рахунок сплачено з депозиту — щоб змінити, приберіть платіж і внесіть заново.')
            return redirect('billing:detail', pk=pk)
        if pays:
            InvoicePayment._base_manager.filter(pk=pays[0].pk).update(method=method)
        invoice.payment_method = method
        invoice.save(update_fields=['payment_method'])
        invoice.refresh_paid()
    return redirect('billing:detail', pk=pk)


# ── Відправка посилання на оплату в Telegram ─────────────────────────────────

def _send_payment_link_tg(invoice, org) -> bool:
    """Відправляє посилання на оплату в TG клієнту. Повертає True якщо відправлено."""
    if not invoice.fiscal_page_url:
        return False
    try:
        from apps.tg.models import TelegramChat
        from apps.tg.views import _send_tg
        tg_chat = TelegramChat.objects.filter(
            client=invoice.client, organization=org
        ).first()
        if not tg_chat:
            return False
        patient_str = f' ({invoice.patient.name})' if invoice.patient else ''
        # QR на частину (Олег 19.11.2026) — клієнт бачить, скільки платить зараз, а не лише суму рахунку
        amount = invoice.qr_amount or invoice.total
        now_str = f', до сплати зараз {amount} грн' if amount != invoice.total else ''
        text = (
            f'💳 Рахунок #{invoice.pk}{patient_str} на суму {invoice.total} грн{now_str}\n\n'
            f'Оплатіть за посиланням:\n{invoice.fiscal_page_url}'
        )
        _send_tg(tg_chat.tg_user_id, text, org=org)
        return True
    except Exception:
        logger.exception('TG payment link send failed for invoice=%s', invoice.pk)
        return False


# ── Відправка посилання в TG вручну (якщо вже є page_url) ────────────────────

@login_required
@require_POST
def send_payment_link_tg(request, pk):
    invoice = get_object_or_404(dostupni_rakhunky(request), pk=pk)
    if not invoice.fiscal_page_url:
        messages.error(request, 'Немає активного посилання на оплату.')
        return _back(invoice)

    org = request.organization
    sent = _send_payment_link_tg(invoice, org)
    if sent:
        messages.success(request, 'Посилання на оплату надіслано клієнту в Telegram.')
    else:
        messages.warning(request, 'Клієнт не прив\'язаний до Telegram або посилання відсутнє.')
    return _back(invoice)


# ── Фіскалізація через Checkbox ─────────────────────────────────────────────

def _back(invoice):
    """Чернетка — назад у редагування, закритий рахунок (борг) — на сторінку рахунку."""
    return redirect('billing:detail' if invoice.status == Invoice.Status.PAID else 'billing:edit', pk=invoice.pk)


def _parse_amount(raw, due):
    """«Скільки платять зараз» (Олег 19.11.2026): порожньо — увесь залишок; не більше залишку."""
    import re
    s = (raw or '').strip().replace(' ', '').replace('\xa0', '').replace(',', '.')
    if not s:
        return due
    if not re.fullmatch(r'\d+(\.\d{1,2})?', s):
        raise ValueError(f'«{raw}» — не сума')
    amount = Decimal(s).quantize(Decimal('0.01'))
    if amount <= 0:
        raise ValueError('має бути більше нуля')
    if amount > due:
        raise ValueError(f'{amount} ₴ — більше, ніж до сплати ({due} ₴)')
    return amount


def _left_note(invoice, closed):
    """Що лишилось після платежу — для повідомлення персоналу."""
    if closed:
        return 'Рахунок закрито.'
    if invoice.status == Invoice.Status.DRAFT:
        return f'Рахунок відкритий, до сплати ще {invoice.balance_due} ₴.'
    return 'Борг погашено.' if not invoice.has_debt else f'Борг ще {invoice.balance_due} ₴.'


def _fiscal_reset(invoice):
    """QR знято (скасували, протух, не пройшов) — стан чека рахунку знову з платежів: є платіж із чеком — «Оплачено»
    з його чеком, нема — «—»."""
    from .models import InvoicePayment
    last = (InvoicePayment._base_manager.filter(invoice=invoice).exclude(fiscal_receipt_id__isnull=True)
            .exclude(fiscal_receipt_id='').order_by('-paid_at', '-pk').values_list('fiscal_receipt_id', flat=True).first())
    invoice.fiscal_receipt_id = last or ''
    invoice.fiscal_status = Invoice.FiscalStatus.SENT if last else Invoice.FiscalStatus.NONE
    invoice.fiscal_page_url = ''
    invoice.qr_amount = None
    invoice.save(update_fields=['fiscal_receipt_id', 'fiscal_status', 'fiscal_page_url', 'qr_amount'])


@login_required
@require_POST
@transaction.atomic
def fiscalize_invoice(request, pk):
    """Оплата з фіскальним чеком Checkbox — на весь залишок або на частину (Олег 19.11.2026: «вручну виставляти, скільки
    оплачують з боргу, на QR або готівкою»). Чернетка: сплачено все — рахунок закривається (склад списується), частина —
    аванс, рахунок лишається відкритим. Закритий рахунок із боргом — частина боргу або весь. Чек — на суму цього платежу:
    перша оплата на весь рахунок — з позиціями, як раніше, інакше один рядок «Оплата за рахунком №N (частина)»."""
    org = request.organization
    invoice = get_object_or_404(dostupni_rakhunky(request, Invoice.objects.select_for_update()), pk=pk,
                                status__in=(Invoice.Status.DRAFT, Invoice.Status.PAID))
    if org and not request.user.is_superuser and not org.can_use_checkbox:
        messages.error(request, 'Фіскалізація Checkbox доступна з тарифу «Клініка».')
        return _back(invoice)
    invoice.refresh_paid()
    due = invoice.balance_due
    if due <= 0:
        messages.error(request, 'За рахунком уже все сплачено.' if invoice.total else 'Рахунок порожній.')
        return _back(invoice)
    # форма показувала одну суму до сплати, а тепер інша (дописали рядки, хтось вніс платіж) — сума могла бути хибна
    seen = request.POST.get('due_seen')
    if seen and _parse_decimal(seen, None) != due:
        messages.error(request, f'Сума до сплати змінилась — тепер {due} ₴. Перевірте суму й розрахуйте ще раз.')
        return _back(invoice)
    try:
        amount = _parse_amount(request.POST.get('amount'), due)
    except ValueError as exc:
        messages.error(request, f'Сума: {exc}.')
        return _back(invoice)
    payment_type = request.POST.get('payment_type', 'card')
    # QR на всю суму ще чекає оплати (19.11.2026: 55 рахунків закрили «Оплатити» з QR, що висів, і 3 з них
    # клієнт таки оплатив за QR — гроші прийшли, а чека нема). Спершу питаємо Checkbox.
    if invoice.fiscal_status == Invoice.FiscalStatus.PENDING and invoice.fiscal_receipt_id:
        qr = _settle_pending_qr(org, invoice)
        if qr != 'dropped':
            messages.error(request, _QR_MSG[qr])
            return _back(invoice)
    whole = invoice.amount_paid == 0 and amount == invoice.total   # чек з позиціями рахунку, як раніше
    part = None if whole else amount
    closes = invoice.status == Invoice.Status.DRAFT and amount >= due

    from .checkbox_service import CheckboxService
    from .models import InvoicePayment
    svc = CheckboxService(org)

    try:
        svc.authenticate()
        svc.ensure_shift_open()

        if payment_type in ('cash', 'transfer'):
            # Готівка або переказ на рахунок ФОП (Олег 19.11.2026): гроші вже в нас — чек одразу. Переказ — чек
            # безготівкою «Інтернет банкінг». Не вистачає складу або чек не пробився — ні платежу, ні списання.
            method = Invoice.PaymentMethod.TRANSFER if payment_type == 'transfer' else Invoice.PaymentMethod.CASH
            with transaction.atomic():
                if closes:
                    _writeoff_stock(invoice, request.user)   # спершу склад: не вистачає — чек не б'ємо
                pay = add_payment(invoice, amount, method, request.user)
                if method == Invoice.PaymentMethod.TRANSFER:
                    receipt = svc.create_transfer_receipt(invoice, amount=part)
                else:
                    receipt = svc.create_cash_receipt(invoice, amount=part)
                receipt_id = receipt.get('id') or ''
                InvoicePayment._base_manager.filter(pk=pay.pk).update(fiscal_receipt_id=receipt_id or None)
                invoice.fiscal_receipt_id = receipt_id
                invoice.fiscal_status = Invoice.FiscalStatus.SENT
                fields = ['fiscal_receipt_id', 'fiscal_status']
                if closes:
                    invoice.status = Invoice.Status.PAID
                    fields.append('status')
                invoice.save(update_fields=fields)
                invoice.refresh_paid()
            what = 'Чек на переказ' if method == Invoice.PaymentMethod.TRANSFER else 'Готівковий чек'
            messages.success(request, f'{what} на {amount} ₴ пробито. {_left_note(invoice, closes)}')

        else:
            # Картка: Checkbox invoice → сума на QR-терміналі (і посилання клієнту в Telegram) → «Перевірити оплату»
            cb_invoice = svc.create_invoice(invoice, amount=part)
            invoice.fiscal_receipt_id = cb_invoice.get('id', '')
            invoice.fiscal_page_url = cb_invoice.get('page_url', '') or ''
            invoice.fiscal_status = Invoice.FiscalStatus.PENDING
            invoice.qr_amount = amount
            fields = ['fiscal_receipt_id', 'fiscal_page_url', 'fiscal_status', 'qr_amount']
            if invoice.status == Invoice.Status.DRAFT:
                invoice.payment_method = Invoice.PaymentMethod.CARD
                fields.append('payment_method')
            invoice.save(update_fields=fields)

            # Відправляємо посилання на оплату в Telegram якщо клієнт верифікований
            tg_sent = _send_payment_link_tg(invoice, org)
            messages.success(request, f'{amount} ₴ відправлено на QR-термінал. ' + (
                'Посилання на оплату надіслано клієнту в Telegram.' if tg_sent else 'Очікуємо оплату від клієнта.'))

    except InsufficientStockError as exc:
        messages.error(request, 'Недостатньо залишку: ' + '; '.join(exc.items)
                       + '. Поповніть склад або приберіть позиції — чек не пробито.')
    except Exception as exc:
        logger.error('Checkbox error invoice=%s: %s', pk, exc)
        if invoice.status == Invoice.Status.DRAFT:
            Invoice._base_manager.filter(pk=invoice.pk).update(fiscal_status=Invoice.FiscalStatus.ERROR)
        messages.error(request, f'Помилка Checkbox: {exc}')
        invoice.refresh_from_db()

    return _back(invoice)


# ── Підтвердження оплати через Checkbox (картка/QR) ──────────────────────────

@login_required
@require_POST
@transaction.atomic
def confirm_checkbox_payment(request, pk):
    """
    Перевіряє оплату за QR у Checkbox. Оплачено — платіж на суму, що прийшла, і фіскальний чек на неї; чернетку,
    сплачену повністю, закриваємо (склад списується). QR на весь рахунок без авансу — чек з позиціями, як раніше;
    на частину (Олег 19.11.2026) — один рядок «Оплата за рахунком №N (частина)».
    """
    invoice = get_object_or_404(dostupni_rakhunky(request, Invoice.objects.select_for_update()), pk=pk,
                                status__in=(Invoice.Status.DRAFT, Invoice.Status.PAID))

    if invoice.fiscal_status != Invoice.FiscalStatus.PENDING or not invoice.fiscal_receipt_id:
        messages.error(request, 'Немає активного очікування оплати.')
        return _back(invoice)

    org = request.organization
    from .checkbox_service import CheckboxService
    from .models import InvoicePayment
    svc = CheckboxService(org)

    try:
        svc.authenticate()
        cb_data = svc.get_invoice_status(invoice.fiscal_receipt_id)
        status = cb_data.get('status', '')

        PAID_STATUSES = {'SUCCESS', 'DONE'}
        FAILED_STATUSES = {'EXPIRED', 'CANCELLED', 'FAILED', 'FAILURE'}   # FAILURE — так Checkbox віддає невдалу оплату

        if status in PAID_STATUSES:
            invoice.refresh_paid()
            # скільки клієнт заплатив — зі слів Checkbox (копійки); інакше — сума QR, старі QR (до 19.11) — увесь залишок
            paid_kop = cb_data.get('final_amount') or cb_data.get('amount')
            if paid_kop:
                amount = (Decimal(paid_kop) / 100).quantize(Decimal('0.01'))
            else:
                amount = invoice.qr_amount or invoice.balance_due
            whole = invoice.amount_paid == 0 and amount == invoice.total
            closes = invoice.status == Invoice.Status.DRAFT and amount >= invoice.balance_due
            fiscal_warn = None
            with transaction.atomic():
                if closes:
                    try:
                        _writeoff_stock(invoice, request.user)
                    except InsufficientStockError as exc:
                        logger.error('Insufficient stock on checkbox confirm invoice=%s: %s', pk, exc.items)
                        messages.error(
                            request,
                            'Оплата прийнята, але не вистачає на складі: ' + '; '.join(exc.items)
                            + '. Поповніть склад і повторіть або скоригуйте рахунок.'
                        )
                        return _back(invoice)

                # Друга дія: фіскальний чек через /receipts/sell. Без цього кроку Checkbox знає про оплату через
                # термінал, але ДПС-чека не існує. Чек не пробився — платіж однаково записуємо: гроші вже прийшли.
                receipt_id = ''
                try:
                    receipt = svc.fiscalize_card_invoice(invoice, cb_data, amount=None if whole else amount)
                    receipt_id = receipt.get('id') or ''
                except Exception as exc:
                    logger.error('Checkbox card fiscalize failed invoice=%s: %s', pk, exc)
                    fiscal_warn = str(exc)

                pay = add_payment(invoice, amount, Invoice.PaymentMethod.CARD, request.user)
                if receipt_id:
                    InvoicePayment._base_manager.filter(pk=pay.pk).update(fiscal_receipt_id=receipt_id)
                invoice.fiscal_receipt_id = receipt_id or invoice.fiscal_receipt_id
                invoice.fiscal_status = Invoice.FiscalStatus.ERROR if fiscal_warn else Invoice.FiscalStatus.SENT
                invoice.fiscal_page_url = ''
                invoice.qr_amount = None
                fields = ['fiscal_receipt_id', 'fiscal_status', 'fiscal_page_url', 'qr_amount']
                if closes:
                    invoice.status = Invoice.Status.PAID
                    fields.append('status')
                invoice.save(update_fields=fields)
                invoice.refresh_paid()

            if fiscal_warn:
                messages.warning(request, f'Оплату {amount} ₴ прийнято, але фіскальний чек не пробився: {fiscal_warn}. '
                                          f'{_left_note(invoice, closes)}')
            else:
                messages.success(request, f'Оплату {amount} ₴ підтверджено, фіскальний чек пробито. {_left_note(invoice, closes)}')
            return _back(invoice)

        elif status in FAILED_STATUSES:
            _fiscal_reset(invoice)
            messages.error(request, f'Оплата не пройшла (статус: {status}). Спробуйте ще раз.')

        else:
            messages.info(request, f'Оплата ще не надійшла (статус: {status}). Зачекайте і натисніть знову.')

    except Exception as exc:
        logger.error('Checkbox confirm error invoice=%s: %s', pk, exc)
        messages.error(request, f'Помилка перевірки оплати: {exc}')

    return _back(invoice)


# ── QR, що висить, коли рахунок закривають іншим способом ────────────────────

_QR_MSG = {
    'paid': 'Клієнт уже оплатив за QR-кодом — натисніть «Перевірити оплату»: пробʼється чек, і платіж запишеться.',
    'error': 'Не вдалося перевірити QR-оплату в Checkbox. Спробуйте ще раз або натисніть «Скасувати» в блоці очікування оплати.',
    'unknown': 'Checkbox не відповів, чи оплачено QR-код. Якщо клієнт таки заплатив за QR, гроші прийшли без чека — перевірте в Checkbox.',
}


def _settle_pending_qr(org, invoice):
    """'paid' — клієнт уже заплатив за QR: закривати лише «Перевірити оплату», інакше гроші без чека;
    'dropped' — QR знято з термінала, очікування скинуто; 'error' — Checkbox не відповів."""
    from .checkbox_service import CheckboxService
    svc = CheckboxService(org)
    try:
        svc.authenticate()
        status = (svc.get_invoice_status(invoice.fiscal_receipt_id) or {}).get('status', '')
        if status in ('SUCCESS', 'DONE'):
            return 'paid'
        if status not in ('EXPIRED', 'CANCELLED', 'FAILED', 'FAILURE'):
            svc.cancel_invoice(invoice.fiscal_receipt_id)
    except Exception as exc:
        logger.warning('Checkbox: pending QR check failed invoice=%s: %s', invoice.pk, exc)
        return 'error'
    _fiscal_reset(invoice)
    return 'dropped'


# ── Скасування Checkbox invoice (до оплати) ──────────────────────────────────

@login_required
@require_POST
def cancel_fiscal(request, pk):
    org = request.organization
    invoice = get_object_or_404(dostupni_rakhunky(request), pk=pk, status__in=(Invoice.Status.DRAFT, Invoice.Status.PAID))
    if org and not request.user.is_superuser and not org.can_use_checkbox:
        messages.error(request, 'Фіскалізація Checkbox доступна з тарифу «Клініка».')
        return _back(invoice)
    # закритий рахунок — лише QR, що висить: чек, уже пробитий на платіж, тут не чіпаємо
    if not invoice.fiscal_receipt_id or (invoice.status == Invoice.Status.PAID
                                         and invoice.fiscal_status != Invoice.FiscalStatus.PENDING):
        messages.error(request, 'Немає активного очікування оплати для скасування.')
        return _back(invoice)

    from .checkbox_service import CheckboxService
    svc = CheckboxService(org)

    try:
        svc.authenticate()
        if invoice.fiscal_status in (Invoice.FiscalStatus.PENDING, Invoice.FiscalStatus.ERROR):
            # клієнт уже заплатив за QR — скасувати = гроші без чека (19.11.2026: так загубились чеки на 3 850 ₴)
            try:
                st = (svc.get_invoice_status(invoice.fiscal_receipt_id) or {}).get('status', '')
            except Exception:
                st = ''   # Checkbox не знає такого QR — скидаємо, як і раніше
            if st in ('SUCCESS', 'DONE'):
                messages.error(request, _QR_MSG['paid'])
                return _back(invoice)
            if st not in ('EXPIRED', 'CANCELLED', 'FAILED', 'FAILURE'):
                try:
                    svc.cancel_invoice(invoice.fiscal_receipt_id)
                except Exception as cancel_exc:
                    # Якщо Checkbox каже invoice не існує/вже завершено — все одно скидаємо state.
                    logger.warning('Checkbox cancel returned error (continuing): %s', cancel_exc)
        _fiscal_reset(invoice)
        if invoice.status == Invoice.Status.DRAFT:
            invoice.payment_method = None   # спосіб обирали під QR; закритий рахунок свій спосіб бере з платежів
            invoice.save(update_fields=['payment_method'])
        messages.success(request, 'Платіж скасовано. Можна розрахувати знову.')
    except Exception as exc:
        logger.error('Checkbox cancel error invoice=%s: %s', pk, exc)
        messages.error(request, f'Помилка скасування: {exc}')

    return _back(invoice)


# ── Допоміжна функція списання залишків ──────────────────────────────────────

class InsufficientStockError(Exception):
    """Залишку на складі не вистачає для списання."""
    def __init__(self, items: list[str]):
        self.items = items
        super().__init__('; '.join(items))


@transaction.atomic
def _writeoff_stock(invoice, user):
    from apps.inventory.models import Product

    lines = list(
        invoice.lines
        .select_related('product', 'parent_line', 'parent_line__service')
        .all()
    )

    # Збираємо PKs продуктів які треба списати (унікальні).
    product_pks = {
        line.product_id
        for line in lines
        if line.line_type == 'product' and line.product_id and not line.stock_written_off
    }

    # Row-level lock щоб уникнути race з паралельними оплатами/списаннями.
    locked_products = {
        p.pk: p
        for p in Product.objects.select_for_update().filter(
            pk__in=product_pks,
            organization=invoice.organization,
        )
    }

    # ВАЖЛИВО: не блокуємо закриття чека через нестачу складу. Розбіжності
    # допускаються (зловживання залишком, неточний прихід). StockMovement
    # пише в мінус — буде видно у звіті inventory для подальшого reconciliation.
    for line in lines:
        if line.line_type == 'product' and line.product and not line.stock_written_off:
            product = locked_products.get(line.product_id)
            if product is None:
                logger.warning(
                    'Product %s (line %s) недоступний при списанні invoice=%s — пропускаємо',
                    line.product.name, line.pk, invoice.pk,
                )
                continue
            if product.quantity < line.quantity:
                logger.warning(
                    'Stock below zero: invoice=%s product=%s have=%s wrote=%s',
                    invoice.pk, product.name, product.quantity, line.quantity,
                )

    for line in lines:
        if line.line_type == 'product' and line.product and not line.stock_written_off:
            product = locked_products.get(line.product_id)
            if product is None:
                continue
            if line.parent_line and line.parent_line.service:
                reason = f'Послуга «{line.parent_line.service.name}», рахунок #{invoice.pk}'
            else:
                reason = f'Рахунок #{invoice.pk}'
            StockMovement.objects.create(
                product=product,
                type=StockMovement.Type.OUT,
                quantity=line.quantity,
                price=product.sell_price,
                reason=reason,
                created_by=user,
            )
            line.stock_written_off = True
            line.save(update_fields=['stock_written_off'])


# ── PDF ──────────────────────────────────────────────────────────────────────

@login_required
def invoice_pdf(request, pk):
    from django.template.loader import render_to_string
    try:
        from weasyprint import HTML
    except ImportError:
        return HttpResponse('WeasyPrint не встановлено', status=500)

    invoice = get_object_or_404(dostupni_rakhunky(request), pk=pk, organization=request.organization)
    lines = list(invoice.lines.select_related('service', 'product').all())
    html_string = render_to_string('billing/pdf.html', {
        'invoice': invoice,
        'lines': lines,
        # Колонка «Знижка» — лише коли знижка справді є (клієнт ANVAR 31.10:
        # порожня колонка підказує покупцю, що знижку можна попросити).
        'has_line_discount': any(l.discount and not l.parent_line_id for l in lines),
        'clinic': request.organization,
        'request': request,
    })
    pdf = HTML(string=html_string, base_url=request.build_absolute_uri('/')).write_pdf()
    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = f'filename="invoice-{invoice.pk}.pdf"'
    return response
