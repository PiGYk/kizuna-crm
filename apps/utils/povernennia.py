"""Безпечне «повернутися, звідки прийшов» (Ревізор, №870, 27.11.2026).

Referer пише браузер, а підставити його може будь-хто: redirect(request.META['HTTP_REFERER']) відправляв людину на чужий
сайт від імені CRM.
"""
from django.utils.http import url_has_allowed_host_and_scheme


def nazad(request, zapasna):
    """Referer — лише якщо веде на цей самий сайт; інакше запасна адреса (ім'я маршруту чи шлях)."""
    ref = request.META.get('HTTP_REFERER') or ''
    if ref and url_has_allowed_host_and_scheme(ref, allowed_hosts={request.get_host()},
                                               require_https=request.is_secure()):
        return ref
    return zapasna
