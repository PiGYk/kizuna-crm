"""HTTP Basic Auth для CardDAV endpoints.

Не використовуємо session-auth бо телефон не має cookies.
Password = CardDAVToken.token (не основний пароль).
"""
import base64
from functools import wraps

from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.utils import timezone


def _unauthorized():
    resp = HttpResponse(status=401)
    resp['WWW-Authenticate'] = 'Basic realm="Kizuna CardDAV"'
    return resp


def carddav_auth(view_func):
    """Декоратор: парсить Basic Auth header → знаходить CardDAVToken.

    Зберігає request.carddav_user і request.organization.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        from .models import CardDAVToken

        auth_hdr = request.META.get('HTTP_AUTHORIZATION', '')
        if not auth_hdr.startswith('Basic '):
            return _unauthorized()

        try:
            decoded = base64.b64decode(auth_hdr[6:]).decode('utf-8')
            username, _, token = decoded.partition(':')
        except Exception:
            return _unauthorized()

        if not username or not token:
            return _unauthorized()

        User = get_user_model()
        try:
            user = User.objects.get(username=username, is_active=True)
        except User.DoesNotExist:
            return _unauthorized()

        try:
            cdt = user.carddav_token
        except CardDAVToken.DoesNotExist:
            return _unauthorized()

        # Constant-time compare щоб не light timing-attacks
        import hmac
        if not hmac.compare_digest(cdt.token, token):
            return _unauthorized()

        # Перевірка username у URL (захист від cross-user)
        url_user = kwargs.get('username')
        if url_user and url_user != username:
            return _unauthorized()

        # Touch last_used_at (батчимо — раз на годину)
        now = timezone.now()
        if not cdt.last_used_at or (now - cdt.last_used_at).total_seconds() > 3600:
            cdt.last_used_at = now
            cdt.save(update_fields=['last_used_at'])

        request.carddav_user = user
        request.organization = user.organization

        # Встановити thread-local org, бо моделі (Client, Patient) використовують
        # OrgManager що читає org з threading.local() — без цього всі queryset порожні.
        from apps.clinic.tenant import set_current_org, clear_current_org
        set_current_org(user.organization)
        try:
            return view_func(request, *args, **kwargs)
        finally:
            clear_current_org()

    return wrapper
