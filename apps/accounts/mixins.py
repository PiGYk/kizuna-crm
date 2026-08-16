from functools import wraps

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


class AdminRequiredMixin(LoginRequiredMixin):
    """Тільки адміністратор."""
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not request.user.is_admin():
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class StaffRequiredMixin(LoginRequiredMixin):
    """Будь-який авторизований користувач (doctor / assistant / admin)."""
    pass


def menu_required(item):
    """Доступ до розділу за тим самим конфігом, що керує видимістю пункту меню.

    Прибрати пункт із меню — не те саме, що закрити розділ: адреса лишається
    робочою для будь-кого, хто її знає. Тому розділ, який адмін може вимкнути
    ролі в налаштуваннях клініки, перевіряє право ще й на вході у view.
    """
    def _decorator(view_func):
        @wraps(view_func)
        @login_required
        def _wrapped(request, *args, **kwargs):
            org = getattr(request, 'organization', None)
            role = getattr(request.user, 'role', None)
            if org is not None and role and not request.user.is_superuser:
                if not org.can_see_menu(role, item):
                    raise PermissionDenied
            return view_func(request, *args, **kwargs)
        return _wrapped
    return _decorator


def admin_required(view_func):
    """Декоратор для функційних view: тільки is_authenticated + is_admin()."""
    @wraps(view_func)
    @login_required
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_admin():
            raise PermissionDenied
        return view_func(request, *args, **kwargs)
    return _wrapped
