from .models import Organization


def clinic(request):
    """Inject current organization into every template as {{ clinic }}."""
    org = getattr(request, 'organization', None)
    if org is None:
        # Fallback for unauthenticated pages (login, register)
        org = Organization.objects.filter(is_active=True).first()
    return {'clinic': org}
