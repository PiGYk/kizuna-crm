import json
import logging
from datetime import timedelta

logger = logging.getLogger(__name__)

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from apps.accounts.mixins import AdminRequiredMixin
from .forms import OrganizationSettingsForm
from .models import Organization
from .wayforpay import PLANS, WAYFORPAY_URL, accept_response, build_payment_fields, verify_callback


class ClinicSettingsView(AdminRequiredMixin, View):
    def get(self, request):
        form = OrganizationSettingsForm(instance=request.organization)
        return render(request, 'clinic/settings.html', {'form': form})

    def post(self, request):
        form = OrganizationSettingsForm(request.POST, instance=request.organization)
        if form.is_valid():
            form.save()
            messages.success(request, 'Налаштування збережено.')
            return redirect('clinic:settings')
        return render(request, 'clinic/settings.html', {'form': form})


# ---------------------------------------------------------------------------
# Суперадмін: тільки is_superuser
# ---------------------------------------------------------------------------

def _superuser_required(view_fn):
    """Декоратор: тільки суперюзер."""
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            from django.conf import settings
            return redirect(settings.LOGIN_URL)
        if not request.user.is_superuser:
            raise PermissionDenied
        return view_fn(request, *args, **kwargs)
    wrapper.__name__ = view_fn.__name__
    return login_required(wrapper)


@_superuser_required
def superadmin_dashboard(request):
    orgs = (
        Organization.objects
        .annotate(user_count=Count('users'))
        .order_by('-created_at')
    )
    now = timezone.now()
    stats = {
        'total': orgs.count(),
        'active': orgs.filter(is_active=True).count(),
        'inactive': orgs.filter(is_active=False).count(),
        'trial_active': sum(1 for o in orgs if o.trial_expires_at and not o.is_trial_expired and o.is_active),
        'trial_expired': sum(1 for o in orgs if o.is_trial_expired),
        'paid': orgs.filter(is_active=True, trial_expires_at__isnull=True).count(),
    }
    return render(request, 'superadmin/dashboard.html', {'orgs': orgs, 'stats': stats})


@_superuser_required
def superadmin_toggle_active(request, pk):
    if request.method != 'POST':
        return redirect('superadmin:dashboard')
    org = get_object_or_404(Organization, pk=pk)
    org.is_active = not org.is_active
    org.save(update_fields=['is_active'])
    status = 'активовано' if org.is_active else 'деактивовано'
    messages.success(request, f'Клініку «{org.name}» {status}.')
    return redirect('superadmin:dashboard')


@_superuser_required
def superadmin_extend_trial(request, pk):
    if request.method != 'POST':
        return redirect('superadmin:dashboard')
    org = get_object_or_404(Organization, pk=pk)
    days = int(request.POST.get('days', 14))
    days = max(1, min(days, 365))
    base = max(org.trial_expires_at or timezone.now(), timezone.now())
    org.trial_expires_at = base + timedelta(days=days)
    org.is_active = True
    org.save(update_fields=['trial_expires_at', 'is_active'])
    messages.success(request, f'Тріал для «{org.name}» продовжено на {days} днів.')
    return redirect('superadmin:dashboard')


@_superuser_required
def superadmin_remove_trial(request, pk):
    """Зняти обмеження тріалу — платний акаунт."""
    if request.method != 'POST':
        return redirect('superadmin:dashboard')
    org = get_object_or_404(Organization, pk=pk)
    org.trial_expires_at = None
    org.is_active = True
    org.save(update_fields=['trial_expires_at', 'is_active'])
    messages.success(request, f'«{org.name}» переведено на платний акаунт.')
    return redirect('superadmin:dashboard')


# ---------------------------------------------------------------------------
# WayForPay — оплата підписки
# ---------------------------------------------------------------------------

@login_required
def subscribe_checkout(request, plan_key):
    if plan_key not in PLANS:
        return redirect('trial_expired')

    org = request.organization
    if org is None:
        return redirect('trial_expired')

    return_url = request.build_absolute_uri('/subscribe/success/')
    callback_url = 'https://crm.kizuna.com.ua/subscribe/callback/'

    fields = build_payment_fields(plan_key, org.pk, return_url, callback_url)
    return render(request, 'clinic/subscribe_checkout.html', {
        'fields': fields,
        'wayforpay_url': WAYFORPAY_URL,
        'plan': PLANS[plan_key],
    })


@login_required
def subscribe_success(request):
    org = request.organization
    plan_key = org.plan if org else ''
    plan_info = PLANS.get(plan_key, {})
    return render(request, 'clinic/subscribe_success.html', {
        'plan_name': plan_info.get('name', 'Тариф'),
        'amount': plan_info.get('amount', 0),
        'order_ref': request.GET.get('order_ref', ''),
    })


@csrf_exempt
def subscribe_callback(request):
    """WayForPay IPN — підтвердження оплати."""
    if request.method != 'POST':
        return JsonResponse({'error': 'method not allowed'}, status=405)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        data = request.POST.dict()

    logger.info('WayForPay callback: ref=%s status=%s amount=%s',
                data.get('orderReference'), data.get('transactionStatus'), data.get('amount'))

    if not verify_callback(data):
        logger.warning('WayForPay callback: invalid signature for ref=%s', data.get('orderReference'))
        return JsonResponse({'error': 'invalid signature'}, status=400)

    if data.get('transactionStatus') == 'Approved':
        order_ref = data.get('orderReference', '')
        # order_ref format: kizuna-{org_id}-{plan_key}-{timestamp}
        parts = order_ref.split('-')
        if len(parts) >= 3:
            try:
                org_id = int(parts[1])
                plan_key = parts[2]
                org = Organization.objects.get(pk=org_id)
                # Подовжуємо доступ на 30 днів від сьогодні (або від поточної дати закінчення)
                base = max(timezone.now(), org.trial_expires_at or timezone.now())
                org.trial_expires_at = base + timedelta(days=30)
                org.plan = plan_key
                org.is_active = True
                org.save(update_fields=['trial_expires_at', 'plan', 'is_active'])
            except (ValueError, Organization.DoesNotExist):
                pass

    return JsonResponse(accept_response(data.get('orderReference', '')))
