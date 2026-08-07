from decimal import Decimal
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count, Q, Max
from django.shortcuts import get_object_or_404, redirect, render

from apps.finance.models import Supplier
from apps.finance.forms import SupplierForm
from apps.inventory.models import StockMovement
from apps.tg.utils import is_mobile


@login_required
def supplier_list(request):
    org = request.organization
    suppliers = Supplier.objects.filter(organization=org).annotate(
        total_purchases=Count('stock_movements', filter=Q(stock_movements__type='in')),
        total_sum=Sum('stock_movements__price', filter=Q(stock_movements__type='in')),
        last_purchase=Max('stock_movements__created_at', filter=Q(stock_movements__type='in')),
        total_expenses=Sum('expenses__amount'),
        expense_count=Count('expenses'),
    ).order_by('name')
    template = 'inventory/suppliers/list_mobile.html' if is_mobile(request) else 'inventory/suppliers/list.html'
    return render(request, template, {'suppliers': suppliers})


@login_required
def supplier_create(request):
    org = request.organization
    if request.method == 'POST':
        form = SupplierForm(request.POST)
        if form.is_valid():
            supplier = form.save(commit=False)
            supplier.organization = org
            supplier.save()
            messages.success(request, f'Постачальника \xab{supplier.name}\xbb додано.')
            return redirect('inventory:supplier_list')
    else:
        form = SupplierForm()
    template = 'inventory/suppliers/form_mobile.html' if is_mobile(request) else 'inventory/suppliers/form.html'
    return render(request, template, {'form': form, 'is_new': True})


@login_required
def supplier_edit(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk, organization=request.organization)
    if request.method == 'POST':
        form = SupplierForm(request.POST, instance=supplier)
        if form.is_valid():
            form.save()
            messages.success(request, 'Збережено.')
            return redirect('inventory:supplier_detail', pk=pk)
    else:
        form = SupplierForm(instance=supplier)
    template = 'inventory/suppliers/form_mobile.html' if is_mobile(request) else 'inventory/suppliers/form.html'
    return render(request, template, {'form': form, 'supplier': supplier, 'is_new': False})


@login_required
def supplier_detail(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk, organization=request.organization)
    movements = StockMovement.objects.filter(
        supplier=supplier, type='in'
    ).select_related('product', 'product__unit', 'created_by').order_by('-created_at')[:50]

    stats = movements.aggregate(
        total_sum=Sum('price'),
        total_count=Count('id'),
    )

    # Витрати з модуля фінансів
    expenses = supplier.expenses.select_related('category').order_by('-date')[:50]
    expense_total = supplier.expenses.aggregate(t=Sum('amount'))['t'] or 0

    template = 'inventory/suppliers/detail_mobile.html' if is_mobile(request) else 'inventory/suppliers/detail.html'
    return render(request, template, {
        'supplier': supplier,
        'movements': movements,
        'stats': stats,
        'expenses': expenses,
        'expense_total': expense_total,
    })


@login_required
def supplier_delete(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk, organization=request.organization)
    if request.method == 'POST':
        count = StockMovement.objects.filter(supplier=supplier).count()
        if count:
            messages.error(request, f'Не можна видалити \u2014 {count} записів руху складу пов\u02bcязані з цим постачальником.')
            return redirect('inventory:supplier_detail', pk=pk)
        supplier.delete()
        messages.success(request, f'Постачальника \xab{supplier.name}\xbb видалено.')
        return redirect('inventory:supplier_list')
    return redirect('inventory:supplier_detail', pk=pk)
