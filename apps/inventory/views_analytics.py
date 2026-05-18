import json
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count, F, Q, DecimalField
from django.db.models.functions import TruncMonth, TruncWeek
from django.shortcuts import render

from .models import Product, StockMovement


@login_required
def inventory_analytics(request):
    """Аналітика складу: вартість, оборот, топ товарів, закупки по місяцях."""
    org = request.organization

    # -- Загальна вартість складу --
    products = Product.objects.filter(organization=org, is_active=True)
    total_buy = products.aggregate(
        val=Sum(F('quantity') * F('buy_price'), output_field=DecimalField())
    )['val'] or 0
    total_sell = products.aggregate(
        val=Sum(F('quantity') * F('sell_price'), output_field=DecimalField())
    )['val'] or 0
    total_items = products.count()
    low_stock = products.filter(quantity__lte=F('min_quantity'), min_quantity__gt=0).count()
    out_of_stock = products.filter(quantity__lte=0).count()

    # -- Топ-10 товарів по списанню (за 30 днів) --
    month_ago = date.today() - timedelta(days=30)
    top_consumed = (
        StockMovement.objects
        .filter(product__organization=org, type='out', created_at__date__gte=month_ago)
        .values('product__name', 'product__pk')
        .annotate(total_qty=Sum('quantity'), total_sum=Sum('price'))
        .order_by('-total_qty')[:10]
    )

    # -- Топ-10 товарів по закупках (за 30 днів) --
    top_purchased = (
        StockMovement.objects
        .filter(product__organization=org, type='in', created_at__date__gte=month_ago)
        .values('product__name', 'product__pk')
        .annotate(total_qty=Sum('quantity'), total_sum=Sum('price'))
        .order_by('-total_sum')[:10]
    )

    # -- Закупки по місяцях (останні 6 місяців) --
    six_months_ago = date.today() - timedelta(days=180)
    purchases_by_month = list(
        StockMovement.objects
        .filter(product__organization=org, type='in', created_at__date__gte=six_months_ago)
        .annotate(month=TruncMonth('created_at'))
        .values('month')
        .annotate(total=Sum('price'), count=Count('id'))
        .order_by('month')
    )

    # Дані для графіка (JSON)
    chart_labels = [m['month'].strftime('%b %Y') for m in purchases_by_month]
    chart_data = [float(m['total'] or 0) for m in purchases_by_month]

    # -- Списання по місяцях --
    writeoffs_by_month = list(
        StockMovement.objects
        .filter(product__organization=org, type='out', created_at__date__gte=six_months_ago)
        .annotate(month=TruncMonth('created_at'))
        .values('month')
        .annotate(total=Sum('price'), count=Count('id'))
        .order_by('month')
    )
    writeoff_data = [float(m['total'] or 0) for m in writeoffs_by_month]

    return render(request, 'inventory/analytics.html', {
        'total_buy': total_buy,
        'total_sell': total_sell,
        'total_items': total_items,
        'low_stock': low_stock,
        'out_of_stock': out_of_stock,
        'top_consumed': top_consumed,
        'top_purchased': top_purchased,
        'chart_labels': json.dumps(chart_labels),
        'chart_purchases': json.dumps(chart_data),
        'chart_writeoffs': json.dumps(writeoff_data),
        'purchases_by_month': purchases_by_month,
    })
