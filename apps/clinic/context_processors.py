from .models import Organization


def clinic(request):
    """Inject current organization into every template as {{ clinic }}."""
    org = getattr(request, 'organization', None)
    if org is None:
        # Fallback for unauthenticated pages (login, register)
        org = Organization.objects.filter(is_active=True).first()

    # Видимість меню для поточного користувача
    menu = {}
    user = getattr(request, 'user', None)
    if user and user.is_authenticated and org:
        role = getattr(user, 'role', 'admin')
        menu = org.get_menu_config().get(role, {})
        # Адмін і суперюзер бачать все
        if role == 'admin' or getattr(user, 'is_superuser', False):
            menu = {item: True for item, _ in Organization.MENU_ITEMS}

    return {'clinic': org, 'user_menu': menu}
