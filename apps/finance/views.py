from datetime import timedelta, date
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count, Q
from django.db.models.functions import TruncDate
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.utils import timezone

from apps.billing.models import Invoice
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
    ctx = {
        'expenses': qs[:100],
        'total': total,
        'categories': ExpenseCategory.objects.all(),
        'suppliers': Supplier.objects.all(),
        'filter': {
            'category': cat_id or '',
            'supplier': supplier_id or '',
            'method': method or '',
            'from': date_from or '',
            'to': date_to or '',
        },
    }
    return render(request, 'finance/expense_list.html', ctx)


@login_required
def expense_create(request):
    if request.method == 'POST':
        form = ExpenseForm(request.POST, request.FILES)
        if form.is_valid():
            exp = form.save(commit=False)
            exp.created_by = request.user
            exp.organization = request.organization
            exp.save()
            messages.success(request, f'Витрату {exp.amount} ₴ додано.')
            return redirect('finance:expenses')
    else:
        form = ExpenseForm(initial={'date': timezone.localdate()})
    return render(request, 'finance/expense_form.html', {'form': form, 'title': 'Нова витрата'})


@login_required
def expense_edit(request, pk):
    exp = get_object_or_404(Expense, pk=pk)
    if request.method == 'POST':
        form = ExpenseForm(request.POST, request.FILES, instance=exp)
        if form.is_valid():
            form.save()
            messages.success(request, 'Витрату оновлено.')
            return redirect('finance:expenses')
    else:
        form = ExpenseForm(instance=exp)
    return render(request, 'finance/expense_form.html', {'form': form, 'title': 'Редагувати витрату', 'expense': exp})


@login_required
def expense_delete(request, pk):
    exp = get_object_or_404(Expense, pk=pk)
    if request.method == 'POST':
        exp.delete()
        messages.success(request, 'Витрату видалено.')
    return redirect('finance:expenses')


# ── Постачальники ────────────────────────────────────────

@login_required
def supplier_list(request):
    suppliers = Supplier.objects.annotate(
        total_expenses=Sum('expenses__amount'),
        expense_count=Count('expenses'),
    )
    return render(request, 'finance/supplier_list.html', {'suppliers': suppliers})


@login_required
def supplier_create(request):
    if request.method == 'POST':
        form = SupplierForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.organization = request.organization
            obj.save()
            messages.success(request, 'Постачальника додано.')
            return redirect('finance:suppliers')
    else:
        form = SupplierForm()
    return render(request, 'finance/supplier_form.html', {'form': form, 'title': 'Новий постачальник'})


@login_required
def supplier_edit(request, pk):
    sup = get_object_or_404(Supplier, pk=pk)
    if request.method == 'POST':
        form = SupplierForm(request.POST, instance=sup)
        if form.is_valid():
            form.save()
            messages.success(request, 'Постачальника оновлено.')
            return redirect('finance:suppliers')
    else:
        form = SupplierForm(instance=sup)
    return render(request, 'finance/supplier_form.html', {'form': form, 'title': 'Редагувати постачальника', 'supplier': sup})


@login_required
def supplier_detail(request, pk):
    sup = get_object_or_404(Supplier, pk=pk)
    expenses = sup.expenses.select_related('category').order_by('-date')[:50]
    total = sup.expenses.aggregate(t=Sum('amount'))['t'] or 0
    return render(request, 'finance/supplier_detail.html', {
        'supplier': sup, 'expenses': expenses, 'total': total,
    })


@login_required
def supplier_delete(request, pk):
    sup = get_object_or_404(Supplier, pk=pk)
    if request.method == 'POST':
        if sup.expenses.exists():
            messages.error(request, 'Неможливо видалити — є привʼязані витрати.')
        else:
            sup.delete()
            messages.success(request, 'Постачальника видалено.')
    return redirect('finance:suppliers')


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

    balances = calculate_balances()

    return render(request, 'finance/cash_operations.html', {
        'operations': ops[:100],
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
    return render(request, 'finance/cash_operation_form.html', {'form': form})


@login_required
def cash_operation_delete(request, pk):
    op = get_object_or_404(CashOperation, pk=pk)
    if request.method == 'POST':
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
    return render(request, 'finance/settings.html', {
        'categories': categories,
        'form': ExpenseCategoryForm(),
        'balance_form': FinanceSettingsForm(instance=FinanceSettings.get()),
    })


@login_required
def settings_balance_update(request):
    if request.method == 'POST':
        form = FinanceSettingsForm(request.POST, instance=FinanceSettings.get())
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
    return render(request, 'finance/report.html')


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
