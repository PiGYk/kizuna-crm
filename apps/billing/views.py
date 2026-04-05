import json
import logging
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

logger = logging.getLogger(__name__)

from django.db.models import Q
from apps.clients.models import Client, Patient
from apps.inventory.models import Product, StockMovement
from apps.services.models import Service

from .models import Invoice, InvoiceLine


def _lines_context(invoice):
    """Спільний контекст для partial lines_table — з вакцинами."""
    lines = list(invoice.lines.select_related('service', 'product').all())
    has_vaccination = any(
        l.line_type == 'service' and l.service and 'вакцинац' in l.service.name.lower()
        for l in lines
    )
    vaccine_products = []
    vaccine_in_invoice = set()
    if has_vaccination:
        vaccine_products = list(
            Product.objects.filter(category__name='Вакцини', is_active=True).order_by('name')
        )
        vaccine_in_invoice = set(
            invoice.lines.filter(
                product__category__name='Вакцини', unit_price=0
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
    invoices = Invoice.objects.select_related('client', 'patient', 'doctor').all()
    payment = request.GET.get('payment', '')
    if payment in Invoice.PaymentMethod.values:
        invoices = invoices.filter(payment_method=payment)
    return render(request, 'billing/list.html', {
        'invoices': invoices,
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
        invoice = Invoice.objects.create(
            client=client,
            patient=patient,
            doctor=request.user,
            created_by=request.user,
            organization=request.organization,
        )
        return redirect('billing:edit', pk=invoice.pk)

    return render(request, 'billing/create.html')


# ── HTMX: пошук клієнтів при створенні рахунку ──────────────────────────────

@login_required
def client_search(request):
    q = request.GET.get('q', '').strip()
    clients = []
    if q:
        clients = Client.objects.filter(
            Q(last_name__icontains=q) |
            Q(first_name__icontains=q) |
            Q(phone__icontains=q)
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
            Q(breed__icontains=q)
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

    services = Service.objects.filter(is_active=True).order_by('name')
    products = Product.objects.filter(is_active=True).order_by('name')
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
        qty = Decimal(request.POST.get('quantity', '1'))
        discount = Decimal(request.POST.get('discount', '0'))
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

    elif line_type == 'product':
        product_id = request.POST.get('product_id')
        if not product_id:
            return HttpResponse(status=400)
        product = get_object_or_404(Product, pk=product_id)
        qty = Decimal(request.POST.get('quantity', '1'))
        discount = Decimal(request.POST.get('discount', '0'))
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


# ── HTMX: оновити ціну / кількість рядка ────────────────────────────────────

@login_required
@require_POST
def update_line(request, pk, line_id):
    invoice = get_object_or_404(Invoice, pk=pk, status=Invoice.Status.DRAFT)
    line = get_object_or_404(InvoiceLine, pk=line_id, invoice=invoice)
    try:
        line.unit_price = Decimal(request.POST.get('unit_price', line.unit_price))
        line.quantity = Decimal(request.POST.get('quantity', line.quantity))
    except Exception:
        pass
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
    invoice.discount = Decimal(request.POST.get('discount', '0'))
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
    qs = Service.objects.filter(is_active=True).order_by('name')
    if q:
        qs = qs.filter(name__icontains=q)
    qs = qs[:25]
    return JsonResponse({'results': [
        {'id': s.pk, 'name': s.name, 'price': str(s.price)} for s in qs
    ]})


@login_required
def product_search_json(request):
    q = request.GET.get('q', '').strip()
    qs = Product.objects.filter(is_active=True).order_by('name')
    if q:
        qs = qs.filter(name__icontains=q)
    qs = qs[:25]
    return JsonResponse({'results': [
        {'id': p.pk, 'name': p.name, 'price': str(p.sell_price),
         'qty': str(p.quantity), 'unit': p.unit.name if p.unit else ''} for p in qs
    ]})


# ── HTMX: компоненти послуги (для попапу підтвердження) ─────────────────────

@login_required
def service_components(request, service_id):
    service = get_object_or_404(Service, pk=service_id)
    components = service.components.select_related('product', 'product__unit').all()
    return render(request, 'billing/partials/service_components.html', {
        'service': service,
        'components': components,
    })


# ── Оплатити (фіналізувати) ──────────────────────────────────────────────────

@login_required
@require_POST
def pay_invoice(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk, status=Invoice.Status.DRAFT)

    # які сервіси списувати
    writeoff_ids = set(request.POST.getlist('writeoff_service'))

    insufficient = []
    for line in invoice.lines.select_related('service', 'product').all():
        if line.line_type == 'product' and line.product and not line.stock_written_off:
            if line.product.quantity < line.quantity:
                insufficient.append(
                    f'{line.product.name}: є {line.product.quantity}, потрібно {line.quantity}'
                )

    if insufficient:
        messages.warning(
            request,
            'Недостатній залишок — списання все одно проведено: ' + '; '.join(insufficient),
        )

    for line in invoice.lines.select_related('service', 'product').all():
        if line.line_type == 'product' and line.product and not line.stock_written_off:
            # автоматично списуємо товари
            StockMovement.objects.create(
                product=line.product,
                type=StockMovement.Type.OUT,
                quantity=line.quantity,
                price=line.unit_price,
                reason=f'Рахунок #{invoice.pk}',
                created_by=request.user,
            )
            line.stock_written_off = True
            line.save(update_fields=['stock_written_off'])

        elif line.line_type == 'service' and str(line.service_id) in writeoff_ids and not line.stock_written_off:
            # списуємо компоненти послуги
            for comp in line.service.components.select_related('product').all():
                custom_key = f'comp_qty_{line.pk}_{comp.pk}'
                custom_val = request.POST.get(custom_key)
                try:
                    qty_to_write = Decimal(custom_val) if custom_val else comp.quantity * line.quantity
                except Exception:
                    qty_to_write = comp.quantity * line.quantity
                StockMovement.objects.create(
                    product=comp.product,
                    type=StockMovement.Type.OUT,
                    quantity=qty_to_write,
                    price=comp.product.sell_price,
                    reason=f'Послуга «{line.service.name}», рахунок #{invoice.pk}',
                    created_by=request.user,
                )
            line.stock_written_off = True
            line.save(update_fields=['stock_written_off'])

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


# ── видалити рахунок (тільки чернетки і скасовані) ───────────────────────────

@login_required
@require_POST
def delete_invoice(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)
    if invoice.status in (Invoice.Status.DRAFT, Invoice.Status.CANCELLED):
        invoice.delete()
    return redirect('billing:list')


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
            invoice.fiscal_status = Invoice.FiscalStatus.PENDING
            invoice.payment_method = Invoice.PaymentMethod.CARD
            invoice.save(update_fields=['fiscal_receipt_id', 'fiscal_status', 'payment_method'])
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
            _writeoff_stock(invoice, request.user)

            # receipt_id може ще не з'явитись (Checkbox async) — зберігаємо що є
            receipt_id = cb_data.get('receipt_id') or invoice.fiscal_receipt_id
            invoice.fiscal_receipt_id = receipt_id
            invoice.fiscal_status = Invoice.FiscalStatus.SENT
            invoice.status = Invoice.Status.PAID
            invoice.payment_method = Invoice.PaymentMethod.CARD
            invoice.save(update_fields=['fiscal_receipt_id', 'fiscal_status', 'status', 'payment_method'])
            messages.success(request, 'Оплату підтверджено! Рахунок закрито.')
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

def _writeoff_stock(invoice, user):
    for line in invoice.lines.select_related('service', 'product').all():
        if line.line_type == 'product' and line.product and not line.stock_written_off:
            StockMovement.objects.create(
                product=line.product,
                type=StockMovement.Type.OUT,
                quantity=line.quantity,
                price=line.unit_price,
                reason=f'Рахунок #{invoice.pk}',
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

    invoice = get_object_or_404(Invoice, pk=pk)
    lines = invoice.lines.select_related('service', 'product').all()
    html_string = render_to_string('billing/pdf.html', {
        'invoice': invoice,
        'lines': lines,
        'request': request,
    })
    pdf = HTML(string=html_string, base_url=request.build_absolute_uri('/')).write_pdf()
    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = f'filename="invoice-{invoice.pk}.pdf"'
    return response
