import functools
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
    def _ctx(self, request, form):
        from apps.accounts.models import User
        from apps.finance.models import FinanceSettings, calculate_balances
        from apps.finance.forms import FinanceSettingsForm
        from apps.clients.tasks import REMIND_DAYS_BEFORE

        users = User.objects.filter(
            organization=request.organization
        ).order_by('role', 'last_name', 'first_name')

        fs = FinanceSettings.get_for_org(request.organization)
        balances = calculate_balances(request.organization)

        from apps.clinic.models import Organization
        sections = [
            ('clinic',    'Клініка',       '🏥'),
            ('design',    'Дизайн',        '🎨'),
            ('staff',     'Команда',       '👥'),
            ('finance',   'Фінанси',       '💰'),
            ('telegram',  'Telegram',      '✈️'),
            ('reminders', 'Нагадування',   '🔔'),
            ('inventory', 'Склад',         '📦'),
            ('fiscal',    'Фіскалізація',  '🧾'),
            ('menu_access', 'Доступ до меню', '🔐'),
            ('billing',   'Підписка',      '💳'),
        ]

        org = request.organization
        from apps.tg.models import TelegramChat
        tg_chats = TelegramChat.objects.filter(
            organization=org, receive_leads=True
        ).select_related('client').order_by('-last_message_at')

        return {
            'form': form,
            'users': users,
            'fs': fs,
            'finance_form': FinanceSettingsForm(instance=fs),
            'balances': balances,
            'org': org,
            'tg_chats': tg_chats,
            'vaccine_remind_days': REMIND_DAYS_BEFORE,
            'sections': sections,
            'menu_items': Organization.MENU_ITEMS,
            'menu_roles': Organization.ROLES_WITH_MENU,
            'menu_config': org.get_menu_config() if org else {},
            'menu_config_json': json.dumps(org.get_menu_config() if org else {}),
        }

    def _limit_doctor_queryset(self, form, org):
        from apps.accounts.models import User
        form.fields['default_doctor'].queryset = User.objects.filter(
            organization=org,
            role__in=['admin', 'doctor'],
        ).order_by('last_name', 'first_name')
        form.fields['default_doctor'].empty_label = '— не вибрано —'

    def get(self, request):
        form = OrganizationSettingsForm(instance=request.organization)
        self._limit_doctor_queryset(form, request.organization)
        return render(request, 'clinic/settings.html', self._ctx(request, form))

    def post(self, request):
        # Збереження отримувачів заявок з сайту
        if request.POST.get('action') == 'save_lead_recipients':
            from apps.tg.models import TelegramChat
            org = request.organization
            selected_ids = set(request.POST.getlist('lead_chat_ids'))
            chats = TelegramChat.objects.filter(organization=org)
            for chat in chats:
                chat.receive_leads = str(chat.pk) in selected_ids
            TelegramChat.objects.bulk_update(chats, ['receive_leads'])
            messages.success(request, 'Отримувачів заявок збережено.')
            return redirect('clinic:settings')

        # Збереження графіку роботи
        if request.POST.get('action') == 'save_schedule':
            org = request.organization
            work_days = [d for d in range(7) if request.POST.get(f'work_day_{d}')]
            form = OrganizationSettingsForm(request.POST, request.FILES, instance=org)
            self._limit_doctor_queryset(form, org)
            if form.is_valid():
                org.work_days = work_days
                form.save()
                messages.success(request, 'Графік роботи збережено.')
            else:
                messages.error(request, 'Перевірте правильність даних.')
            return redirect(request.path + '#schedule')

        # Збереження нотифікацій
        if request.POST.get('action') == 'save_notifications':
            org = request.organization
            org.notify_appointment_24h = request.POST.get('notify_appointment_24h') == 'on'
            org.notify_appointment_2h = request.POST.get('notify_appointment_2h') == 'on'
            org.notify_vaccines = request.POST.get('notify_vaccines') == 'on'
            org.save(update_fields=['notify_appointment_24h', 'notify_appointment_2h', 'notify_vaccines'])
            messages.success(request, 'Налаштування нотифікацій збережено.')
            return redirect(request.path + '#notifications')

        # Збереження конфігу меню по ролях
        if request.POST.get('action') == 'save_menu_config':
            org = request.organization
            from apps.clinic.models import Organization
            cfg = {}
            for role, _ in Organization.ROLES_WITH_MENU:
                cfg[role] = {}
                for item, _ in Organization.MENU_ITEMS:
                    cfg[role][item] = request.POST.get(f'menu_{role}_{item}') == 'on'
            org.role_menu_config = cfg
            org.save(update_fields=['role_menu_config'])
            messages.success(request, 'Права доступу до меню збережено.')
            return redirect('clinic:settings')

        form = OrganizationSettingsForm(request.POST, request.FILES, instance=request.organization)
        self._limit_doctor_queryset(form, request.organization)
        if form.is_valid():
            org = form.save(commit=False)
            if request.POST.get('logo-clear') and org.logo:
                org.logo.delete(save=False)
                org.logo = None
            org.save()
            messages.success(request, 'Налаштування збережено.')
            return redirect('clinic:settings')
        return render(request, 'clinic/settings.html', self._ctx(request, form))


# ---------------------------------------------------------------------------
# Суперадмін: тільки is_superuser
# ---------------------------------------------------------------------------

def _superuser_required(view_fn):
    """Декоратор: тільки суперюзер."""
    @functools.wraps(view_fn)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            from django.conf import settings
            return redirect(settings.LOGIN_URL)
        if not request.user.is_superuser:
            raise PermissionDenied
        return view_fn(request, *args, **kwargs)
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
    # Жорстко відмовляємо для невалідних планів — інакше зловмисник може
    # підтасувати orderReference з custom plan і отримати network за start.
    if plan_key not in PLANS:
        from django.http import Http404
        raise Http404('Unknown plan')

    org = request.organization
    if org is None:
        return redirect('trial_expired')

    return_url = request.build_absolute_uri('/subscribe/success/')
    callback_url = request.build_absolute_uri('/subscribe/callback/')

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
        'plan_name': plan_info.get('label', 'Тариф'),
        'amount': plan_info.get('price', 0),
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
                if plan_key not in dict(Organization.PLAN_CHOICES):
                    return JsonResponse({'error': 'Invalid plan'}, status=400)

                # Перевірка узгодженості суми платежу з ціною плану. Без цього
                # юзер може купити «Мережу» за ціною «Старту» якщо підмінить
                # orderReference на checkout-кроці.
                expected_price = PLANS.get(plan_key, {}).get('price')
                paid_amount = 0.0
                if expected_price is not None:
                    try:
                        paid_amount = float(data.get('amount', 0))
                    except (TypeError, ValueError):
                        paid_amount = 0.0
                    if abs(paid_amount - float(expected_price)) > 0.01:
                        logger.warning(
                            'WayForPay amount mismatch: ref=%s plan=%s expected=%s got=%s',
                            order_ref, plan_key, expected_price, paid_amount,
                        )
                        return JsonResponse(
                            {'error': 'amount mismatch'}, status=400
                        )

                # Idempotency: get_or_create на order_ref. Якщо запис уже існує —
                # пропускаємо подовження тріалу (WayForPay retry'ить callback при
                # slow ack і без цього ловила б +30 днів за кожен дубль).
                from apps.clinic.models import PaymentTransaction
                from decimal import Decimal
                _, tx_created = PaymentTransaction.objects.get_or_create(
                    order_ref=order_ref,
                    defaults={
                        'organization_id': org_id,
                        'plan_key': plan_key,
                        'amount': Decimal(str(paid_amount)),
                        'status': 'Approved',
                        'raw_payload': data,
                    },
                )
                if not tx_created:
                    logger.info('WayForPay duplicate callback: ref=%s (skip)', order_ref)
                    return JsonResponse(accept_response(order_ref))

                org = Organization.objects.get(pk=org_id)
                # Подовжуємо доступ на 30 днів від сьогодні (або від поточної дати закінчення)
                base = max(timezone.now(), org.trial_expires_at or timezone.now())
                org.trial_expires_at = base + timedelta(days=30)
                org.plan = plan_key
                org.is_active = True
                org.save(update_fields=['trial_expires_at', 'plan', 'is_active'])
            except (ValueError, Organization.DoesNotExist) as exc:
                logger.warning('WayForPay callback parse/lookup failed: %s', exc)
                return JsonResponse({'error': 'org not found'}, status=500)

    return JsonResponse(accept_response(data.get('orderReference', '')))
