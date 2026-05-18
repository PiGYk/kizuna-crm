from django.db import models


class OrgManager(models.Manager):
    """Filters by current organization via direct `organization` FK.

    Fail-closed: коли org is None — повертаємо qs.none() щоб уникнути
    cross-tenant витоків даних у фонових тасках, management commands
    або в anonymous endpoints які забули виставити org контекст.
    Для адмінських/системних запитів, що мусять читати дані всіх тенантів,
    використовуй `Model._base_manager` або явний `.objects.all()` після
    тимчасового виставлення org.
    """

    def get_queryset(self):
        from apps.clinic.tenant import get_current_org
        qs = super().get_queryset()
        org = get_current_org()
        if org is None:
            return qs.none()
        return qs.filter(organization=org)


class RelatedOrgManager(models.Manager):
    """Filters by current organization through a related field path.

    Use when the model has no direct `organization` FK but is scoped
    through a parent model that does.

    Example:
        # Patient → Client → organization
        objects = RelatedOrgManager('client__organization')

        # Visit → Patient → Client → organization
        objects = RelatedOrgManager('patient__client__organization')
    """

    def __init__(self, org_path='client__organization'):
        super().__init__()
        self._org_path = org_path

    def get_queryset(self):
        from apps.clinic.tenant import get_current_org
        qs = super().get_queryset()
        org = get_current_org()
        if org is None:
            # Fail-closed: без org-контексту нічого не показуємо.
            return qs.none()
        # When Django creates a related manager it calls __init__() without
        # arguments, losing the configured org_path. Fall back to the model's
        # own default manager which was instantiated with the correct path.
        default_mgr = self.model._default_manager
        org_path = getattr(default_mgr, '_org_path', self._org_path)
        return qs.filter(**{org_path: org})
