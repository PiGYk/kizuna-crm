def expiry_alerts(request):
    """Кількість прострочених і тих що скоро простроченні товарів."""
    if not request.user.is_authenticated:
        return {}
    try:
        from datetime import date, timedelta
        from .models import Product
        today = date.today()
        soon = today + timedelta(days=30)
        expired_count = Product.objects.filter(expiry_date__lt=today).count()
        expiring_count = Product.objects.filter(expiry_date__gte=today, expiry_date__lte=soon).count()
        return {
            'inventory_expired_count': expired_count,
            'inventory_expiring_count': expiring_count,
        }
    except Exception:
        return {}
