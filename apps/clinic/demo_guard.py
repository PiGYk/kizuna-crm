# -*- coding: utf-8 -*-
"""Захист демо-клініки від сміття у полях.

Демо публічне: будь-хто з лендінгу заходить і може писати в картки. Щоб демо
не перетворилось на стіну лайки, у демо-тенанті (slug='demo') POST з матюками
не зберігається — людині показуємо жарт, а не сухе «заборонено».
Реальних клієнтів не стосується взагалі.
"""
import re

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect

_JOKE = 'Лаєтесь? Мама вас лаятись не вчила 🙂 У демо такі слова не зберігаємо.'

# Корені поширеної лайки (укр/рос). Список навмисно короткий: ловимо явне,
# щоб не блокувати нормальні слова (напр. «сукня», «худий» — не чіпаємо).
_ROOTS = [
    r'ху[йяюєеї]\w*', r'п[іи]зд\w*', r'бл[яa]д\w*', r'бля\b',
    r'[єеї]б[аеиуо]\w*', r'\w*[зс]аєб\w*', r'мудак\w*', r'му[дd]ил\w*',
    r'г[ао]ндон\w*', r'залуп\w*', r'п[іи]д[аоя]р\w*', r'сцук\w*',
    r'наху[йя]\w*', r'дуп[ао]?\b', r'ср[аи]к\w*', r'жоп\w*',
    r'st?fu\b', r'fuck\w*', r'shit\w*', r'bitch\w*',
]
_RE = re.compile(r'(?<![\w])(' + '|'.join(_ROOTS) + r')', re.IGNORECASE | re.UNICODE)

# Поля, які не перевіряємо (службові)
_SKIP_FIELDS = {'csrfmiddlewaretoken', 'password', 'password1', 'password2', 'next'}
# Шляхи, де перевірка не потрібна
_SKIP_PATHS = ('/logout/', '/demo/start/', '/static/', '/media/')


def has_profanity(text):
    return bool(text) and bool(_RE.search(str(text)))


class DemoProfanityMiddleware:
    """У демо-клініці не даємо зберегти лайку. Поза демо — нічого не робить."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method != 'POST':
            return self.get_response(request)

        org = getattr(request, 'organization', None)
        if org is None or getattr(org, 'slug', '') != 'demo':
            return self.get_response(request)

        path = request.path
        if any(path.startswith(p) for p in _SKIP_PATHS):
            return self.get_response(request)

        for key, values in request.POST.lists():
            if key in _SKIP_FIELDS:
                continue
            for v in values:
                if has_profanity(v):
                    return self._block(request)

        return self.get_response(request)

    def _block(self, request):
        # htmx / ajax — віддаємо текст, який фронт покаже на місці
        if request.headers.get('HX-Request') or request.headers.get(
                'X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'ok': False, 'error': _JOKE}, status=400)
        messages.error(request, _JOKE)
        return redirect(request.META.get('HTTP_REFERER') or '/dashboard/')
