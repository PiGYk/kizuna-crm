import json
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.clients.models import Client, Patient
from apps.inventory.models import Product, StockMovement
from apps.services.models import Service

from .models import Invoice, InvoiceLine


# ── список рахунків ──────────────────────────────────────────────────────────

@login_required
def invoice_list(request):
    invoices = Invoice.objects.select_related('client', 'patient', 'doctor').all()
    return render(request, 'billing/list.html', {'invoices': invoices})


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
            last_name__icontains=q
        ) | Client.objects.filter(
            first_name__icontains=q
        ) | Client.objects.filter(
            phone__icontains=q
        )
        clients = clients[:10]
    return render(request, 'billing/partials/client_results.html', {'clients': clients, 'q': q})


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
    lines = invoice.lines.select_related('service', 'product').all()
    return render(request, 'billing/edit.html', {
        'invoice': invoice,
        'lines': lines,
        'services': services,
        'products': products,
    })


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
    lines = invoice.lines.select_related('service', 'product').all()
    return render(request, 'billing/partials/lines_table.html', {'invoice': invoice, 'lines': lines})


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
    lines = invoice.lines.select_related('service', 'product').all()
    return render(request, 'billing/partials/lines_table.html', {'invoice': invoice, 'lines': lines})


# ── HTMX: видалити рядок ────────────────────────────────────────────────────

@login_required
@require_POST
def remove_line(request, pk, line_id):
    invoice = get_object_or_404(Invoice, pk=pk, status=Invoice.Status.DRAFT)
    line = get_object_or_404(InvoiceLine, pk=line_id, invoice=invoice)
    line.delete()
    invoice.save_total()
    lines = invoice.lines.select_related('service', 'product').all()
    return render(request, 'billing/partials/lines_table.html', {'invoice': invoice, 'lines': lines})


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
    lines = invoice.lines.select_related('service', 'product').all()
    return render(request, 'billing/partials/lines_table.html', {'invoice': invoice, 'lines': lines})


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

    for line in invoice.lines.select_related('service', 'product').all():
        if line.line_type == 'product' and not line.stock_written_off:
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

    invoice.status = Invoice.Status.PAID
    invoice.save(update_fields=['status'])

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
