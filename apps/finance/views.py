from datetime import timedelta, date
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count, Q
from django.db.models.functions import TruncDate
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.billing.models import Invoice, InvoiceLine
from apps.tg.utils import is_mobile
from .models import ExpenseCategory, Supplier, Expense, CashOperation, FinanceSettings, calculate_balances
from .forms import ExpenseCategoryForm, SupplierForm, ExpenseForm, CashOperationForm, FinanceSettingsForm


# ── Витрати ──────────────────────────────────────────────

@login_required
def expense_list(request):
    qs = Expense.objects.select_related('category', 'supplier', 'created_by')

    # фільтри
    cat_id = request.GET.get('category')
    supplier_id = request.GET.get('supplier')
    method = request.GET.get('method')
    date_from = request.GET.get('from')
    date_to = request.GET.get('to')

    if cat_id:
        qs = qs.filter(category_id=cat_id)
    if supplier_id:
        qs = qs.filter(supplier_id=supplier_id)
    if method:
        qs = qs.filter(payment_method=method)
    if date_from:
        qs = qs.filter(date__gte=date_from)
    if date_to:
        qs = qs.filter(date__lte=date_to)

    total = qs.aggregate(t=Sum('amount'))['t'] or 0
    expenses = list(qs[:100])
    ctx = {
        'expenses': expenses,
        'total': total,
        'categories': ExpenseCategory.objects.filter(organization=request.organization),
        'suppliers': Supplier.objects.filter(organization=request.organization),
        'filter': {
            'category': cat_id or '',
            'supplier': supplier_id or '',
            'method': method or '',
            'from': date_from or '',
            'to': date_to or '',
        },
    }
    template = 'finance/expense_list_mobile.html' if is_mobile(request) else 'finance/expense_list.html'
    return render(request, template, ctx)


@login_required
def expense_create(request):
    org = request.organization
    if request.method == 'POST':
        form = ExpenseForm(request.POST, request.FILES, org=org)
        if form.is_valid():
            exp = form.save(commit=False)
            exp.created_by = request.user
            exp.organization = org
            exp.save()
            messages.success(request, f'Витрату {exp.amount} ₴ додано.')
            return redirect('finance:expenses')
    else:
        form = ExpenseForm(initial={'date': timezone.localdate()}, org=org)
    template = 'finance/expense_form_mobile.html' if is_mobile(request) else 'finance/expense_form.html'
    return render(request, template, {'form': form, 'title': 'Нова витрата'})


@login_required
def expense_edit(request, pk):
    exp = get_object_or_404(Expense, pk=pk)
    org = request.organization
    if request.method == 'POST':
        form = ExpenseForm(request.POST, request.FILES, instance=exp, org=org)
        if form.is_valid():
            form.save()
            messages.success(request, 'Витрату оновлено.')
            return redirect('finance:expenses')
    else:
        form = ExpenseForm(instance=exp, org=org)
    template = 'finance/expense_form_mobile.html' if is_mobile(request) else 'finance/expense_form.html'
    return render(request, template, {'form': form, 'title': 'Редагувати витрату', 'expense': exp})


@login_required
@require_POST
def expense_delete(request, pk):
    exp = get_object_or_404(Expense, pk=pk)
    exp.delete()
    messages.success(request, 'Витрату видалено.')
    return redirect('finance:expenses')


# ── Постачальники (redirect на inventory) ────────────────

@login_required
def supplier_list(request):
    return redirect('inventory:supplier_list')


@login_required
def supplier_create(request):
    return redirect('inventory:supplier_create')


@login_required
def supplier_edit(request, pk):
    return redirect('inventory:supplier_edit', pk=pk)


@login_required
def supplier_detail(request, pk):
    return redirect('inventory:supplier_detail', pk=pk)


@login_required
def supplier_delete(request, pk):
    return redirect('inventory:supplier_detail', pk=pk)


# ── Касові операції ──────────────────────────────────────

@login_required
def cash_operations(request):
    ops = CashOperation.objects.select_related('created_by')

    date_from = request.GET.get('from')
    date_to = request.GET.get('to')
    if date_from:
        ops = ops.filter(date__gte=date_from)
    if date_to:
        ops = ops.filter(date__lte=date_to)

    balances = calculate_balances(request.organization)

    template = 'finance/cash_operations_mobile.html' if is_mobile(request) else 'finance/cash_operations.html'
    return render(request, template, {
        'operations': list(ops[:100]),
        'filter': {'from': date_from or '', 'to': date_to or ''},
        'cash_balance': balances['cash'],
        'card_balance': balances['card'],
    })


@login_required
def cash_operation_create(request):
    if request.method == 'POST':
        form = CashOperationForm(request.POST)
        if form.is_valid():
            op = form.save(commit=False)
            op.created_by = request.user
            op.organization = request.organization
            op.save()
            messages.success(request, f'Операцію "{op.get_type_display()}" на {op.amount} ₴ додано.')
            return redirect('finance:cash_operations')
    else:
        form = CashOperationForm(initial={'date': timezone.localdate()})
    template = 'finance/cash_operation_form_mobile.html' if is_mobile(request) else 'finance/cash_operation_form.html'
    return render(request, template, {'form': form})


@login_required
@require_POST
def cash_operation_delete(request, pk):
    op = get_object_or_404(CashOperation, pk=pk)
    op.delete()
    messages.success(request, 'Операцію видалено.')
    return redirect('finance:cash_operations')


# ── Налаштування (категорії витрат) ──────────────────────

@login_required
def settings_view(request):
    categories = ExpenseCategory.objects.annotate(
        total=Sum('expenses__amount'),
        cnt=Count('expenses'),
    )
    template = 'finance/settings_mobile.html' if is_mobile(request) else 'finance/settings.html'
    return render(request, template, {
        'categories': categories,
        'form': ExpenseCategoryForm(),
        'balance_form': FinanceSettingsForm(instance=FinanceSettings.get_for_org(request.organization)),
    })


@login_required
def settings_balance_update(request):
    if request.method == 'POST':
        form = FinanceSettingsForm(request.POST, instance=FinanceSettings.get_for_org(request.organization))
        if form.is_valid():
            form.save()
            messages.success(request, 'Початкові залишки збережено.')
        else:
            messages.error(request, 'Помилка збереження.')
    return redirect('finance:settings')


@login_required
def category_create(request):
    if request.method == 'POST':
        form = ExpenseCategoryForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.organization = request.organization
            obj.save()
            messages.success(request, 'Категорію додано.')
    return redirect('finance:settings')


@login_required
def category_delete(request, pk):
    cat = get_object_or_404(ExpenseCategory, pk=pk)
    if request.method == 'POST':
        if cat.expenses.exists():
            messages.error(request, 'Неможливо видалити — є привʼязані витрати.')
        else:
            cat.delete()
            messages.success(request, 'Категорію видалено.')
    return redirect('finance:settings')


# ── Зведений звіт (P&L) ─────────────────────────────────

@login_required
def report_view(request):
    template = 'finance/report_mobile.html' if is_mobile(request) else 'finance/report.html'
    return render(request, template)


@login_required
def report_data(request):
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
    else:
        start, end = today.replace(day=1), today

    # Доходи (з оплачених чеків)
    invoices = Invoice.objects.filter(
        status='paid',
        created_at__date__gte=start,
        created_at__date__lte=end,
    )
    income_total = invoices.aggregate(t=Sum('total'))['t'] or Decimal('0')
    income_cash = invoices.filter(payment_method='cash').aggregate(t=Sum('total'))['t'] or Decimal('0')
    income_card = invoices.filter(payment_method='card').aggregate(t=Sum('total'))['t'] or Decimal('0')

    # Витрати
    expenses = Expense.objects.filter(date__gte=start, date__lte=end)
    expense_total = expenses.aggregate(t=Sum('amount'))['t'] or Decimal('0')
    expense_cash = expenses.filter(payment_method='cash').aggregate(t=Sum('amount'))['t'] or Decimal('0')
    expense_card = expenses.filter(payment_method='card').aggregate(t=Sum('amount'))['t'] or Decimal('0')
    expense_transfer = expenses.filter(payment_method='transfer').aggregate(t=Sum('amount'))['t'] or Decimal('0')

    # По категоріях витрат
    by_category = list(
        expenses.values('category__name', 'category__icon')
        .annotate(total=Sum('amount'), cnt=Count('id'))
        .order_by('-total')
    )

    # По постачальниках
    by_supplier = list(
        expenses.filter(supplier__isnull=False)
        .values('supplier__name')
        .annotate(total=Sum('amount'), cnt=Count('id'))
        .order_by('-total')[:10]
    )

    # Касові операції за період
    cash_ops = CashOperation.objects.filter(date__gte=start, date__lte=end)
    card_to_cash = cash_ops.filter(type='card_to_cash').aggregate(t=Sum('amount'))['t'] or Decimal('0')
    cash_to_card = cash_ops.filter(type='cash_to_card').aggregate(t=Sum('amount'))['t'] or Decimal('0')
    deposits = cash_ops.filter(type='deposit').aggregate(t=Sum('amount'))['t'] or Decimal('0')
    withdrawals = cash_ops.filter(type='withdrawal').aggregate(t=Sum('amount'))['t'] or Decimal('0')

    # Графік: доходи vs витрати по днях
    delta = (end - start).days + 1
    income_daily = dict(
        invoices.annotate(day=TruncDate('created_at'))
        .values('day').annotate(total=Sum('total'))
        .values_list('day', 'total')
    )
    expense_daily = dict(
        expenses.annotate(day=TruncDate('date'))
        .values('day').annotate(total=Sum('amount'))
        .values_list('day', 'total')
    )
    labels, inc_data, exp_data = [], [], []
    for i in range(delta):
        d = start + timedelta(days=i)
        labels.append(d.strftime('%d.%m'))
        inc_data.append(float(income_daily.get(d, 0)))
        exp_data.append(float(expense_daily.get(d, 0)))

    profit = income_total - expense_total

    # ── Собівартість реалізованих товарів і послуг (COGS) ─────────────
    # +10% поверх — поправка на розхідники, які не обліковуються
    # (рукавички, шприци, серветки, дрібні розхідники тощо)
    paid_lines = InvoiceLine.objects.filter(invoice__in=invoices)

    cogs_products = Decimal('0')
    for ln in paid_lines.filter(line_type='product', product__isnull=False).select_related('product'):
        cogs_products += ln.quantity * (ln.product.buy_price or Decimal('0'))

    cogs_services = Decimal('0')
    service_lines = paid_lines.filter(line_type='service', service__isnull=False)\
        .select_related('service')\
        .prefetch_related('service__components__product')
    for ln in service_lines:
        comp_cost = sum(
            (comp.quantity * (comp.product.buy_price or Decimal('0'))
             for comp in ln.service.components.all()),
            Decimal('0'),
        )
        cogs_services += ln.quantity * comp_cost

    cogs_total = cogs_products + cogs_services
    cogs_overhead = income_total * Decimal('0.05')        # −5% від виручки розхідники
    cogs_adjusted = cogs_total + cogs_overhead
    gross_profit = income_total - cogs_adjusted

    return JsonResponse({
        'income': {
            'total': float(income_total),
            'cash': float(income_cash),
            'card': float(income_card),
        },
        'expenses': {
            'total': float(expense_total),
            'cash': float(expense_cash),
            'card': float(expense_card),
            'transfer': float(expense_transfer),
        },
        'profit': float(profit),
        'cogs': {
            'products': float(cogs_products),
            'services': float(cogs_services),
            'total': float(cogs_total),
            'overhead': float(cogs_overhead),
            'adjusted': float(cogs_adjusted),
        },
        'gross_profit': float(gross_profit),
        'cash_register': {
            'card_to_cash': float(card_to_cash),
            'cash_to_card': float(cash_to_card),
            'deposits': float(deposits),
            'withdrawals': float(withdrawals),
        },
        'by_category': [
            {'name': f"{c['category__icon'] or ''} {c['category__name']}".strip(),
             'total': float(c['total']), 'cnt': c['cnt']}
            for c in by_category
        ],
        'by_supplier': [
            {'name': s['supplier__name'], 'total': float(s['total']), 'cnt': s['cnt']}
            for s in by_supplier
        ],
        'daily': {
            'labels': labels,
            'income': inc_data,
            'expenses': exp_data,
        },
        'meta': {'start': start.isoformat(), 'end': end.isoformat(), 'preset': preset},
    })
