from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone
from django.db.models import Sum, Count, ExpressionWrapper, DecimalField, F
from datetime import timedelta


@login_required
def dashboard(request):
    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=now.weekday())
    month_start = today_start.replace(day=1)

    from apps.billing.models import Invoice, InvoiceLine
    from apps.clients.models import Client, Patient
    from apps.inventory.models import Product

    paid = Invoice.objects.filter(status='paid')

    def revenue(qs):
        return qs.aggregate(t=Sum('total'))['t'] or 0

    ctx = {
        # лічильники
        'clients_total': Client.objects.count(),
        'patients_total': Patient.objects.count(),

        # виручка
        'revenue_today':   revenue(paid.filter(created_at__gte=today_start)),
        'revenue_week':    revenue(paid.filter(created_at__gte=week_start)),
        'revenue_month':   revenue(paid.filter(created_at__gte=month_start)),

        # чеки сьогодні
        'invoices_today': paid.filter(created_at__gte=today_start).count(),

        # топ-5 послуг за місяць
        'top_services': (
            InvoiceLine.objects
            .filter(invoice__status='paid', invoice__created_at__gte=month_start, line_type='service')
            .values('name')
            .annotate(cnt=Count('id'), total=Sum('total'))
            .order_by('-cnt')[:5]
        ),

        # топ-5 товарів за місяць
        'top_products': (
            InvoiceLine.objects
            .filter(invoice__status='paid', invoice__created_at__gte=month_start, line_type='product')
            .values('name')
            .annotate(cnt=Count('id'), total=Sum('total'))
            .order_by('-cnt')[:5]
        ),

        # малий залишок
        'low_stock': Product.objects.filter(
            is_active=True, min_quantity__gt=0
        ).filter(quantity__lte=F('min_quantity')).order_by('quantity')[:10],

        # нульовий залишок
        'out_of_stock': Product.objects.filter(is_active=True, quantity__lte=0).count(),

        # останні 8 рахунків
        'recent_invoices': (
            paid.select_related('client', 'patient', 'doctor')
            .order_by('-created_at')[:8]
        ),
    }
    return render(request, 'dashboard.html', ctx)


urlpatterns = [
    path('admin/', admin.site.urls),
    path('', dashboard, name='dashboard'),
    path('', include('apps.accounts.urls')),
    path('clients/', include('apps.clients.urls')),
    path('inventory/', include('apps.inventory.urls')),
    path('services/', include('apps.services.urls')),
    path('appointments/', include('apps.appointments.urls')),
    path('billing/', include('apps.billing.urls')),
    path('tg/', include('apps.tg.urls')),
    path('health/', lambda r: HttpResponse('ok')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
