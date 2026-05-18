"""
Утиліти для застосунку Telegram-чатів.

is_mobile(request) — швидке детектування мобільного юзер-агента з підтримкою
override-параметрів у query string:
  ?desktop=1 — примусово показати desktop (для дебагу на телефоні)
  ?m=1       — примусово показати mobile (для дебагу на десктопі)

UA-regex покриває основні мобільні платформи: iOS Safari/Chrome, Android Chrome/
Firefox/Samsung Browser, Windows Phone, BlackBerry. Планшети (iPad без "Mobile"
у UA) — навмисно віддаємо desktop, бо там вистачає місця для повної верстки.
"""

import re

_MOBILE_UA_RE = re.compile(
    r'(iPhone|iPod|Android.*Mobile|Mobile.*Safari|Windows Phone|BlackBerry|Opera Mini|IEMobile)',
    re.IGNORECASE,
)


def is_mobile(request) -> bool:
    """Повертає True, якщо запит виглядає як з мобільного браузера."""
    # Явні override з query-string мають пріоритет.
    if request.GET.get('desktop') == '1':
        return False
    if request.GET.get('m') == '1':
        return True
    ua = request.META.get('HTTP_USER_AGENT', '') or ''
    return bool(_MOBILE_UA_RE.search(ua))
