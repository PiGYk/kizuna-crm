from django.shortcuts import redirect
from apps.clinic.tenant import set_current_org, clear_current_org

# URL-префікси що не потребують перевірки тріалу
_TRIAL_EXEMPT_PREFIXES = (
    '/login/', '/logout/', '/register/', '/trial-expired/',
    '/health/', '/static/', '/media/', '/admin/', '/superadmin/',
    '/subscribe/', '/offer/', '/terms/', '/privacy/', '/verify/',
)
# Точні шляхи що також exempt (не prefix-match)
_TRIAL_EXEMPT_EXACT = ('/',)


def _is_trial_exempt(path):
    if path in _TRIAL_EXEMPT_EXACT:
        return True
    for prefix in _TRIAL_EXEMPT_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


def _org_from_subdomain(request):
    """Повертає Organization якщо Host містить субдомен тенанта, інакше None.

    Логіка: якщо MAIN_DOMAIN='crm.example.com' і Host='kizuna.crm.example.com',
    то витягуємо slug='kizuna' і шукаємо організацію.
    Порт у Host ігнорується.
    """
    from django.conf import settings
    main_domain = getattr(settings, 'MAIN_DOMAIN', '').strip().lower()
    if not main_domain:
        return None

    host = request.get_host().lower().split(':')[0]  # без порту

    # Субдомен є якщо host закінчується на .{main_domain}
    suffix = f'.{main_domain}'
    if not host.endswith(suffix):
        return None

    subdomain = host[: -len(suffix)]
    # Один рівень субдомену, тільки slug-сумісні символи
    if not subdomain or '.' in subdomain:
        return None

    from apps.clinic.models import Organization
    try:
        return Organization.objects.get(slug=subdomain, is_active=True)
    except Organization.DoesNotExist:
        return None


class TenantMiddleware:
    """Визначає поточну організацію (тенанта) для кожного запиту.

    Пріоритет:
    1. Субдомен у Host-заголовку (напр. kizuna.crm.example.com → slug=kizuna)
    2. organization автентифікованого користувача

    Встановлює:
    - request.organization — для прямого доступу у view/template
    - thread-local set_current_org() — для OrgManager у QuerySet

    Повинен стояти ПІСЛЯ AuthenticationMiddleware у MIDDLEWARE.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # 1. Спробуємо субдомен
        org = _org_from_subdomain(request)

        # 2. Fallback — org автентифікованого юзера
        if org is None and hasattr(request, 'user') and request.user.is_authenticated:
            org = getattr(request.user, 'organization', None)

        request.organization = org
        set_current_org(org)

        try:
            response = self._check_trial(request, org)
            if response is None:
                response = self.get_response(request)
        finally:
            clear_current_org()

        return response

    def _check_trial(self, request, org):
        """Якщо тріал прострочений — редирект на сторінку блокування."""
        if _is_trial_exempt(request.path):
            return None
        if org is None:
            return None
        # Суперюзери не блокуються
        if hasattr(request, 'user') and request.user.is_authenticated and request.user.is_superuser:
            return None
        if org.is_trial_expired:
            return redirect('trial_expired')
        return None
