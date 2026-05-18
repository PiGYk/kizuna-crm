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

from .models import Invoice, InvoiceLine


def _lines_context(invoice):
    """Контекст для partial lines_table — top-level рядки з prefetch дітей."""
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
        'has_vaccination': has_vaccination,
        'vaccine_products': vaccine_products,
        'vaccine_in_invoice': vaccine_in_invoice,
    }


# ── список рахунків ──────────────────────────────────────────────────────────

@login_required
def invoice_list(request):
    invoices = Invoice.objects.select_related('client', 'patient', 'doctor').filter(
        organization=request.organization
    ).order_by('-created_at')
    # Лікар бачить тільки свої рахунки
    if request.user.role == 'doctor':
        invoices = invoices.filter(doctor=request.user)
    payment = request.GET.get('payment', '')
    if payment in Invoice.PaymentMethod.values:
        invoices = invoices.filter(payment_method=payment)
    from django.core.paginator import Paginator
    paginator = Paginator(invoices, 50)
    page = paginator.get_page(request.GET.get('page', 1))
    return render(request, 'billing/list.html', {
        'invoices': page,
        'payment_filter': payment,
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

    return render(request, 'billing/create.html')


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
    return render(request, 'billing/partials/client_results.html', {'clients': clients, 'q': q})


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
        )[:10]
    return render(request, 'billing/partials/patient_search_results.html', {'patients': patients, 'q': q})


# ── HTMX: пацієнти клієнта ──────────────────────────────────────────────────

@login_required
def patient_list(request, client_id):
    client = get_object_or_404(Client, pk=client_id)
    patients = client.patients.all()
    return render(request, 'billing/partials/patient_list.html', {'client': client, 'patients': patients})


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
    return render(request, 'billing/edit.html', ctx)


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
    return render(request, 'billing/partials/lines_table.html', _lines_context(invoice))


# ── HTMX: додати компонент (препарат) до послуги в чеку ─────────────────────

@login_required
@require_POST
def add_component(request, pk, line_id):
    """Додає препарат зі складу як дочірній рядок до послуги (ціна 0)."""
    invoice = get_object_or_404(Invoice, pk=pk, status=Invoice.Status.DRAFT)
    parent = get_object_or_404(InvoiceLine, pk=line_id, invoice=invoice, line_type='service')

    product_id = request.POST.get('product_id')
    if not product_id:
        return render(request, 'billing/partials/lines_table.html', _lines_context(invoice))

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
    return render(request, 'billing/partials/lines_table.html', _lines_context(invoice))


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
    return render(request, 'billing/partials/lines_table.html', _lines_context(invoice))


# ── HTMX: видалити рядок ────────────────────────────────────────────────────

@login_required
@require_POST
def remove_line(request, pk, line_id):
    invoice = get_object_or_404(Invoice, pk=pk, status=Invoice.Status.DRAFT)
    line = get_object_or_404(InvoiceLine, pk=line_id, invoice=invoice)
    line.delete()
    invoice.save_total()
    return render(request, 'billing/partials/lines_table.html', _lines_context(invoice))


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
    return render(request, 'billing/partials/lines_table.html', _lines_context(invoice))


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
    return render(request, 'billing/partials/lines_table.html', _lines_context(invoice))


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
    return render(request, 'billing/detail.html', {'invoice': invoice, 'lines': lines})


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
# PAID — тільки admin, з автоматичним поверненням товарів на склад

@login_required
@require_POST
def delete_invoice(request, pk):
    from django.db import transaction
    from django.contrib import messages
    from apps.inventory.models import StockMovement

    invoice = get_object_or_404(Invoice, pk=pk)

    # DRAFT / CANCELLED — як було
    if invoice.status in (Invoice.Status.DRAFT, Invoice.Status.CANCELLED):
        invoice.delete()
        return redirect('billing:list')

    # PAID — тільки admin з поверненням товарів на склад
    if invoice.status == Invoice.Status.PAID:
        if not request.user.is_admin():
            messages.error(request, 'Тільки адміністратор може видаляти оплачені рахунки')
            return redirect('billing:detail', pk=pk)

        with transaction.atomic():
            returned = 0
            # Компенсаційний StockMovement IN на кожен товар який списали при оплаті
            for line in invoice.lines.filter(line_type='product', stock_written_off=True):
                if line.product:
                    StockMovement.objects.create(
                        product=line.product,
                        type=StockMovement.Type.IN,
                        quantity=line.quantity,
                        price=line.product.buy_price,
                        reason=f'Повернення товару з видаленого рахунку #{invoice.pk}',
                        created_by=request.user,
                    )
                    returned += 1
            invoice.delete()
            messages.success(
                request,
                f'Рахунок #{pk} видалено. На склад повернуто {returned} позицій.'
            )
        return redirect('billing:list')

    return redirect('billing:detail', pk=pk)


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
            # Готівка: фіскалізуємо одразу (чек без QR)
            svc.ensure_shift_open()
            receipt = svc.create_cash_receipt(invoice)
            invoice.fiscal_receipt_id = receipt.get('id', '')
            invoice.fiscal_status = Invoice.FiscalStatus.SENT
            invoice.payment_method = Invoice.PaymentMethod.CASH
            invoice.save(update_fields=['fiscal_receipt_id', 'fiscal_status', 'payment_method'])
            messages.success(request, 'Готівковий чек відправлено в Checkbox.')

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
        if invoice.fiscal_status == Invoice.FiscalStatus.PENDING:
            svc.cancel_invoice(invoice.fiscal_receipt_id)
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

    insufficient = []
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

    # Беремо row-level lock одним запитом, щоб уникнути race з паралельними
    # оплатами/списаннями. select_for_update тримає блокування до кінця
    # @transaction.atomic блоку. organization filter — multi-tenant guard.
    locked_products = {
        p.pk: p
        for p in Product.objects.select_for_update().filter(
            pk__in=product_pks,
            organization=invoice.organization,
        )
    }

    for line in lines:
        if line.line_type == 'product' and line.product and not line.stock_written_off:
            product = locked_products.get(line.product_id)
            if product is None:
                # Продукту немає у списку залоченого — найімовірніше cross-tenant
                # або видалений. Не списуємо, повідомляємо.
                insufficient.append(f'{line.product.name}: товар недоступний')
                continue
            if product.quantity < line.quantity:
                insufficient.append(
                    f'{product.name}: є {product.quantity}, потрібно {line.quantity}'
                )
    if insufficient:
        raise InsufficientStockError(insufficient)

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
