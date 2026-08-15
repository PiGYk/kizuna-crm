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

@login_required
def invoice_list(request):
    from datetime import datetime, time, timedelta
    from django.core.paginator import Paginator
    from django.db.models import Sum
    from django.utils import timezone

    base = Invoice.objects.select_related('client', 'patient', 'doctor').filter(
        organization=request.organization
    )
    # Лікар бачить тільки свої рахунки
    if request.user.role == 'doctor':
        base = base.filter(doctor=request.user)

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
            role__in=(UserModel.Role.DOCTOR, UserModel.Role.ADMIN, UserModel.Role.ASSISTANT),
        ).order_by('first_name', 'last_name', 'username')

    paginator = Paginator(invoices_qs, per_page)
    page = paginator.get_page(request.GET.get('page', 1))

    template = 'billing/list_mobile.html' if is_mobile(request) else 'billing/list.html'
    return render(request, template, {
        'invoices': page,
        'payment_filter': payment,
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

@login_required
def invoice_edit(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    if invoice.status != Invoice.Status.DRAFT:
        return redirect('billing:detail', pk=pk)

    org = request.organization
    services = Service.objects.filter(organization=org, is_active=True).order_by('name')
    products = Product.objects.filter(organization=org, is_active=True).order_by('name')
    ctx = _lines_context(invoice)
    ctx['services'] = services
    ctx['products'] = products
    template = 'billing/edit_mobile.html' if is_mobile(request) else 'billing/edit.html'
    return render(request, template, ctx)


# ── HTMX: додати рядок ──────────────────────────────────────────────────────

@login_required
@require_POST
def add_line(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk, status=Invoice.Status.DRAFT)
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
    invoice = get_object_or_404(Invoice, pk=pk, status=Invoice.Status.DRAFT)
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
    invoice = get_object_or_404(Invoice, pk=pk, status=Invoice.Status.DRAFT)
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
    invoice = get_object_or_404(Invoice, pk=pk, status=Invoice.Status.DRAFT)
    line = get_object_or_404(InvoiceLine, pk=line_id, invoice=invoice)
    line.delete()
    invoice.save_total()
    return _lines_render(request, invoice)


# ── HTMX: оновити знижку на рахунок ─────────────────────────────────────────

@login_required
@require_POST
def update_discount(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk, status=Invoice.Status.DRAFT)
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
    invoice = get_object_or_404(Invoice, pk=pk, status=Invoice.Status.DRAFT)
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
        qs = qs.filter(name__icontains=q)
    qs = qs.prefetch_related('components__product__unit')[:25]
    return JsonResponse({'results': [
        {
            'id': s.pk,
            'name': s.name,
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
    invoice = get_object_or_404(Invoice, pk=pk, status=Invoice.Status.DRAFT)

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

    payment_method = request.POST.get('payment_method', Invoice.PaymentMethod.CASH)
    if payment_method not in Invoice.PaymentMethod.values:
        payment_method = Invoice.PaymentMethod.CASH
    invoice.status = Invoice.Status.PAID
    invoice.payment_method = payment_method
    invoice.save(update_fields=['status', 'payment_method'])

    return redirect('billing:detail', pk=pk)


# ── детальний вигляд (рецепт/чек) ───────────────────────────────────────────

@login_required
def invoice_detail(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    lines = invoice.lines.select_related('service', 'product').all()

    base_nav = Invoice.objects.filter(organization=request.organization)
    if request.user.role == 'doctor':
        base_nav = base_nav.filter(doctor=request.user)
    prev_invoice = base_nav.filter(pk__lt=invoice.pk).order_by('-pk').values_list('pk', flat=True).first()
    next_invoice = base_nav.filter(pk__gt=invoice.pk).order_by('pk').values_list('pk', flat=True).first()

    template = 'billing/detail_mobile.html' if is_mobile(request) else 'billing/detail.html'
    return render(request, template, {
        'invoice': invoice,
        'lines': lines,
        'prev_pk': prev_invoice,
        'next_pk': next_invoice,
    })


# ── скасувати рахунок ────────────────────────────────────────────────────────

@login_required
@require_POST
def cancel_invoice(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk, status=Invoice.Status.DRAFT)
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

    invoice = get_object_or_404(Invoice, pk=pk)

    if invoice.status in (Invoice.Status.DRAFT, Invoice.Status.CANCELLED):
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
    invoice = get_object_or_404(Invoice, pk=pk, status=Invoice.Status.PAID)
    method = request.POST.get('payment_method')
    if method in Invoice.PaymentMethod.values:
        invoice.payment_method = method
        invoice.save(update_fields=['payment_method'])
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
        text = (
            f'💳 Рахунок #{invoice.pk}{patient_str} на суму {invoice.total} грн\n\n'
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
    invoice = get_object_or_404(Invoice, pk=pk)
    if not invoice.fiscal_page_url:
        messages.error(request, 'Немає активного посилання на оплату.')
        return redirect('billing:edit', pk=pk)

    org = request.organization
    sent = _send_payment_link_tg(invoice, org)
    if sent:
        messages.success(request, 'Посилання на оплату надіслано клієнту в Telegram.')
    else:
        messages.warning(request, 'Клієнт не прив\'язаний до Telegram або посилання відсутнє.')
    return redirect('billing:edit', pk=pk)


# ── Фіскалізація через Checkbox ─────────────────────────────────────────────

@login_required
@require_POST
@transaction.atomic
def fiscalize_invoice(request, pk):
    org = request.organization
    if org and not request.user.is_superuser and not org.can_use_checkbox:
        messages.error(request, 'Фіскалізація Checkbox доступна з тарифу «Клініка».')
        return redirect('billing:edit', pk=pk)

    invoice = get_object_or_404(Invoice, pk=pk, status=Invoice.Status.DRAFT)
    payment_type = request.POST.get('payment_type', 'card')

    from .checkbox_service import CheckboxService
    svc = CheckboxService(org)

    try:
        svc.authenticate()

        if payment_type == 'cash':
            # Готівка: фіскалізуємо одразу + закриваємо рахунок (списуємо склад).
            svc.ensure_shift_open()
            receipt = svc.create_cash_receipt(invoice)
            invoice.fiscal_receipt_id = receipt.get('id', '')
            invoice.fiscal_status = Invoice.FiscalStatus.SENT
            invoice.payment_method = Invoice.PaymentMethod.CASH

            try:
                _writeoff_stock(invoice, request.user)
            except InsufficientStockError as exc:
                transaction.set_rollback(True)
                messages.error(
                    request,
                    'Чек пробитий, але не вистачає на складі: ' + '; '.join(exc.items)
                    + '. Поповніть склад і спробуйте знову.'
                )
                return redirect('billing:edit', pk=pk)

            invoice.status = Invoice.Status.PAID
            invoice.save(update_fields=['fiscal_receipt_id', 'fiscal_status', 'payment_method', 'status'])
            messages.success(request, 'Готівковий чек пробито, рахунок закрито.')

        else:
            # Картка: створюємо invoice → QR отримує суму → очікуємо оплату
            svc.ensure_shift_open()
            cb_invoice = svc.create_invoice(invoice)
            invoice.fiscal_receipt_id = cb_invoice.get('id', '')
            invoice.fiscal_page_url = cb_invoice.get('page_url', '') or ''
            invoice.fiscal_status = Invoice.FiscalStatus.PENDING
            invoice.payment_method = Invoice.PaymentMethod.CARD
            invoice.save(update_fields=['fiscal_receipt_id', 'fiscal_page_url', 'fiscal_status', 'payment_method'])

            # Відправляємо посилання на оплату в Telegram якщо клієнт верифікований
            tg_sent = _send_payment_link_tg(invoice, org)
            if tg_sent:
                messages.success(request, 'Сума відправлена на QR термінал. Посилання на оплату надіслано клієнту в Telegram.')
            else:
                messages.success(request, 'Сума відправлена на QR термінал. Очікуємо оплату від клієнта.')

    except Exception as exc:
        logger.error('Checkbox error invoice=%s: %s', pk, exc)
        invoice.fiscal_status = Invoice.FiscalStatus.ERROR
        invoice.save(update_fields=['fiscal_status'])
        messages.error(request, f'Помилка Checkbox: {exc}')

    return redirect('billing:edit', pk=pk)


# ── Підтвердження оплати через Checkbox (картка/QR) ──────────────────────────

@login_required
@require_POST
@transaction.atomic
def confirm_checkbox_payment(request, pk):
    """
    Перевіряє статус Checkbox invoice.
    Якщо DONE — списує товари і закриває рахунок як PAID.
    """
    invoice = get_object_or_404(Invoice, pk=pk, status=Invoice.Status.DRAFT)

    if invoice.fiscal_status != Invoice.FiscalStatus.PENDING or not invoice.fiscal_receipt_id:
        messages.error(request, 'Немає активного очікування оплати.')
        return redirect('billing:edit', pk=pk)

    org = request.organization
    from .checkbox_service import CheckboxService
    svc = CheckboxService(org)

    try:
        svc.authenticate()
        cb_data = svc.get_invoice_status(invoice.fiscal_receipt_id)
        status = cb_data.get('status', '')

        PAID_STATUSES = {'SUCCESS', 'DONE'}
        FAILED_STATUSES = {'EXPIRED', 'CANCELLED', 'FAILED'}

        if status in PAID_STATUSES:
            # Оплата підтверджена — списуємо товари
            try:
                _writeoff_stock(invoice, request.user)
            except InsufficientStockError as exc:
                logger.error('Insufficient stock on checkbox confirm invoice=%s: %s', pk, exc.items)
                messages.error(
                    request,
                    'Оплата прийнята, але не вистачає на складі: ' + '; '.join(exc.items)
                    + '. Поповніть склад і повторіть або скоригуйте рахунок.'
                )
                return redirect('billing:edit', pk=pk)

            # Друга дія: пробиваємо фіскальний чек через /receipts/sell.
            # Без цього кроку Checkbox знає про оплату через термінал, але
            # ДПС-чека не існує — і весь місяць CARD-оплат залишається не фіскалізованим.
            fiscal_warn = None
            try:
                receipt = svc.fiscalize_card_invoice(invoice, cb_data)
                invoice.fiscal_receipt_id = receipt.get('id') or invoice.fiscal_receipt_id
                invoice.fiscal_status = Invoice.FiscalStatus.SENT
            except Exception as exc:
                logger.error('Checkbox card fiscalize failed invoice=%s: %s', pk, exc)
                fiscal_warn = str(exc)
                invoice.fiscal_status = Invoice.FiscalStatus.ERROR

            invoice.status = Invoice.Status.PAID
            invoice.payment_method = Invoice.PaymentMethod.CARD
            invoice.save(update_fields=['fiscal_receipt_id', 'fiscal_status', 'status', 'payment_method'])

            if fiscal_warn:
                messages.warning(request, f'Оплату прийнято, але фіскальний чек не пробився: {fiscal_warn}')
            else:
                messages.success(request, 'Оплату підтверджено, фіскальний чек пробито. Рахунок закрито.')
            return redirect('billing:detail', pk=pk)

        elif status in FAILED_STATUSES:
            invoice.fiscal_status = Invoice.FiscalStatus.ERROR
            invoice.fiscal_receipt_id = ''
            invoice.save(update_fields=['fiscal_status', 'fiscal_receipt_id'])
            messages.error(request, f'Оплата не пройшла (статус: {status}). Спробуйте ще раз.')

        else:
            messages.info(request, f'Оплата ще не надійшла (статус: {status}). Зачекайте і натисніть знову.')

    except Exception as exc:
        logger.error('Checkbox confirm error invoice=%s: %s', pk, exc)
        messages.error(request, f'Помилка перевірки оплати: {exc}')

    return redirect('billing:edit', pk=pk)


# ── Скасування Checkbox invoice (до оплати) ──────────────────────────────────

@login_required
@require_POST
def cancel_fiscal(request, pk):
    org = request.organization
    if org and not request.user.is_superuser and not org.can_use_checkbox:
        messages.error(request, 'Фіскалізація Checkbox доступна з тарифу «Клініка».')
        return redirect('billing:edit', pk=pk)

    invoice = get_object_or_404(Invoice, pk=pk, status=Invoice.Status.DRAFT)
    if not invoice.fiscal_receipt_id:
        messages.error(request, 'Немає активного invoice для скасування.')
        return redirect('billing:edit', pk=pk)

    from .checkbox_service import CheckboxService
    svc = CheckboxService(org)

    try:
        svc.authenticate()
        if invoice.fiscal_status in (Invoice.FiscalStatus.PENDING, Invoice.FiscalStatus.ERROR):
            try:
                svc.cancel_invoice(invoice.fiscal_receipt_id)
            except Exception as cancel_exc:
                # Якщо Checkbox каже invoice не існує/вже завершено — все одно скидаємо state.
                logger.warning('Checkbox cancel returned error (continuing): %s', cancel_exc)
        invoice.fiscal_receipt_id = ''
        invoice.fiscal_status = Invoice.FiscalStatus.NONE
        invoice.payment_method = None
        invoice.save(update_fields=['fiscal_receipt_id', 'fiscal_status', 'payment_method'])
        messages.success(request, 'Платіж скасовано. Можна розрахувати знову.')
    except Exception as exc:
        logger.error('Checkbox cancel error invoice=%s: %s', pk, exc)
        messages.error(request, f'Помилка скасування: {exc}')

    return redirect('billing:edit', pk=pk)


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

    invoice = get_object_or_404(Invoice, pk=pk, organization=request.organization)
    lines = invoice.lines.select_related('service', 'product').all()
    html_string = render_to_string('billing/pdf.html', {
        'invoice': invoice,
        'lines': lines,
        'clinic': request.organization,
        'request': request,
    })
    pdf = HTML(string=html_string, base_url=request.build_absolute_uri('/')).write_pdf()
    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = f'filename="invoice-{invoice.pk}.pdf"'
    return response
