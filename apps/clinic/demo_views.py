# -*- coding: utf-8 -*-
"""Вхід у демо з лендінгу без логіна/пароля.

Людина лишає номер у попапі -> валідуємо -> пишемо DemoLead ->
автоматично логінимо в демо-клініку (org slug='demo') -> кидаємо в кабінет.
"""
import re

from django.contrib.auth import get_user_model, login as auth_login
from django.core.cache import cache
from django.http import JsonResponse, HttpResponseNotAllowed
from django.views.decorators.http import require_POST

# Приймаємо тільки український мобільний: +380XXXXXXXXX або 0XXXXXXXXX
_PHONE_RE = re.compile(r'^(\+380\d{9}|0\d{9})$')


def _client_ip(request):
    return (
        request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip()
        or request.META.get('REMOTE_ADDR', '0.0.0.0')
    )


@require_POST
def demo_start(request):
    ip = _client_ip(request)

    # Захист від сміття: не більше 5 заявок з IP за годину.
    rl_key = f'demo-rl:{ip}'
    count = cache.get(rl_key, 0)
    if count >= 5:
        return JsonResponse(
            {'ok': False, 'error': 'Забагато спроб. Спробуйте трохи згодом.'},
            status=429,
        )

    phone = (request.POST.get('phone') or '').strip()
    phone = phone.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
    if not _PHONE_RE.match(phone):
        return JsonResponse(
            {'ok': False, 'error': 'Вкажіть номер у форматі +380XXXXXXXXX або 0XXXXXXXXX'},
            status=400,
        )

    cache.set(rl_key, count + 1, timeout=3600)

    from apps.clinic.models import DemoLead
    DemoLead.objects.create(
        phone=phone,
        ip=ip,
        user_agent=request.META.get('HTTP_USER_AGENT', '')[:2000],
        utm_source=request.GET.get('utm_source', '')[:120],
        utm_medium=request.GET.get('utm_medium', '')[:120],
        utm_campaign=request.GET.get('utm_campaign', '')[:120],
        referer=request.META.get('HTTP_REFERER', '')[:500],
    )

    User = get_user_model()
    demo = (
        User.objects.filter(username='demo', organization__slug='demo', is_active=True)
        .first()
    )
    if demo is None:
        return JsonResponse(
            {'ok': False, 'error': 'Демо тимчасово недоступне, спробуйте пізніше.'},
            status=503,
        )

    auth_login(request, demo, backend='django.contrib.auth.backends.ModelBackend')
    return JsonResponse({'ok': True, 'redirect': '/dashboard/'})
