from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import HttpResponse
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.utils import timezone
from django.db.models import Sum, Count, ExpressionWrapper, DecimalField, F
from datetime import timedelta

from apps.clinic.views import (
    superadmin_dashboard,
    superadmin_toggle_active,
    superadmin_extend_trial,
    superadmin_remove_trial,
    subscribe_checkout,
    subscribe_success,
    subscribe_callback,
)
from apps.clinic.wayforpay import WAYFORPAY_URL, _sign, MERCHANT_DOMAIN
import time as _time


@login_required
def subscribe_test_payment(request):
    """Тестова оплата 1 UAH для перевірки WayForPay інтеграції."""
    from django.conf import settings
    order_ref = f'kizuna-test-{request.user.pk}-{int(_time.time())}'
    order_date = int(_time.time())
    amount = '1'
    currency = 'UAH'
    product_name = 'Kizuna CRM — Тестовий платіж'
    sig_parts = ';'.join([
        settings.WAYFORPAY_MERCHANT, MERCHANT_DOMAIN, order_ref,
        str(order_date), amount, currency, product_name, '1', amount,
    ])
    fields = {
        'merchantAccount': settings.WAYFORPAY_MERCHANT,
        'merchantDomainName': MERCHANT_DOMAIN,
        'merchantSignature': _sign(sig_parts),
        'orderReference': order_ref,
        'orderDate': str(order_date),
        'amount': amount,
        'currency': currency,
        'productName[]': product_name,
        'productCount[]': '1',
        'productPrice[]': amount,
        'returnUrl': request.build_absolute_uri('/subscribe/success/'),
        'serviceUrl': 'https://crm.kizuna.com.ua/subscribe/callback/',
        'language': 'UA',
    }
    return render(request, 'clinic/subscribe_checkout.html', {
        'fields': fields,
        'wayforpay_url': WAYFORPAY_URL,
        'plan': {'label': 'Тестовий платіж', 'price': 1},
        'is_test': True,
    })


def robots_txt(request):
    content = """User-agent: *
Allow: /
Disallow: /dashboard/
Disallow: /admin/
Disallow: /superadmin/
Disallow: /subscribe/callback/
Disallow: /clinic/
Disallow: /clients/
Disallow: /inventory/
Disallow: /services/
Disallow: /appointments/
Disallow: /billing/
Disallow: /analytics/
Disallow: /finance/
Disallow: /tg/

Sitemap: https://crm.kizuna.com.ua/sitemap.xml
"""
    return HttpResponse(content, content_type='text/plain; charset=utf-8')


def sitemap_xml(request):
    now = timezone.now().strftime('%Y-%m-%d')
    content = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://crm.kizuna.com.ua/</loc>
    <lastmod>{now}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>
  <url>
    <loc>https://crm.kizuna.com.ua/register/</loc>
    <lastmod>{now}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.8</priority>
  </url>
  <url>
    <loc>https://crm.kizuna.com.ua/terms/</loc>
    <lastmod>{now}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.4</priority>
  </url>
  <url>
    <loc>https://crm.kizuna.com.ua/offer/</loc>
    <lastmod>{now}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.4</priority>
  </url>
</urlset>"""
    return HttpResponse(content, content_type='application/xml; charset=utf-8')


def trial_expired(request):
    return render(request, 'trial_expired.html', status=402)


def legal_offer(request):
    return render(request, 'legal/offer.html')


def legal_terms(request):
    return render(request, 'legal/terms.html')


def landing(request):
    if request.user.is_authenticated:
        org = getattr(request.user, 'organization', None)
        # Якщо тріал прострочений — показуємо лендінг (щоб юзер міг переглянути тарифи)
        if org is not None and org.is_trial_expired:
            return render(request, 'landing.html')
        return redirect('dashboard')
    return render(request, 'landing.html')


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


superadmin_urls = ([
    path('', superadmin_dashboard, name='dashboard'),
    path('<int:pk>/toggle/', superadmin_toggle_active, name='toggle_active'),
    path('<int:pk>/extend/', superadmin_extend_trial, name='extend_trial'),
    path('<int:pk>/remove-trial/', superadmin_remove_trial, name='remove_trial'),
], 'superadmin')

urlpatterns = [
    path('admin/', admin.site.urls),
    path('superadmin/', include(superadmin_urls)),
    path('trial-expired/', trial_expired, name='trial_expired'),
    path('subscribe/callback/', subscribe_callback, name='subscribe_callback'),
    path('subscribe/success/', subscribe_success, name='subscribe_success'),
    path('subscribe/test/', subscribe_test_payment, name='subscribe_test'),
    path('subscribe/<str:plan_key>/', subscribe_checkout, name='subscribe_checkout'),
    path('offer/', legal_offer, name='legal_offer'),
    path('terms/', legal_terms, name='legal_terms'),
    path('', landing, name='landing'),
    path('dashboard/', dashboard, name='dashboard'),
    path('', include('apps.accounts.urls')),
    path('clients/', include('apps.clients.urls')),
    path('inventory/', include('apps.inventory.urls')),
    path('services/', include('apps.services.urls')),
    path('appointments/', include('apps.appointments.urls')),
    path('billing/', include('apps.billing.urls')),
    path('tg/', include('apps.tg.urls')),
    path('analytics/', include('apps.analytics.urls')),
    path('finance/', include('apps.finance.urls')),
    path('clinic/', include('apps.clinic.urls')),
    path('health/', lambda r: HttpResponse('ok')),
    path('robots.txt', robots_txt),
    path('sitemap.xml', sitemap_xml),
    path('manifest.json', lambda r: HttpResponse(
        '{"name":"Kizuna CRM","short_name":"Kizuna CRM","icons":[{"src":"/static/img/favicon-192.png","sizes":"192x192","type":"image/png"},{"src":"/static/img/favicon-512.png","sizes":"512x512","type":"image/png"}],"start_url":"/","display":"standalone","background_color":"#12100F","theme_color":"#DEAA01"}',
        content_type='application/json'
    )),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
