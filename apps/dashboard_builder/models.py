from django.conf import settings
from django.db import models

from apps.clinic.managers import OrgManager


class Dashboard(models.Model):
    """Редагований дашборд (multi-tenant + per-user).

    layout — список віджетів у форматі:
        [{"type": "widget_key", "x": 0, "y": 0, "w": 3, "h": 2, "config": {}}]

    owner=None означає спільний дашборд організації, доступний усім її юзерам;
    редагувати такий дашборд може тільки admin.
    """

    organization = models.ForeignKey(
        'clinic.Organization',
        on_delete=models.CASCADE,
        related_name='dashboards',
        verbose_name='Організація',
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='dashboards',
        verbose_name='Власник',
        help_text='null = спільний дашборд організації',
    )
    name = models.CharField('Назва', max_length=100)
    layout = models.JSONField(
        'Layout', default=list, blank=True,
        help_text='[{type, x, y, w, h, config}]',
    )
    is_default = models.BooleanField('За замовчуванням', default=False)
    sort_order = models.IntegerField('Порядок', default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Multi-tenant: фільтрація за поточною організацією через thread-local.
    objects = OrgManager()
    # Менеджер без авто-фільтра — для адмінки/міграцій/системних задач.
    all_objects = models.Manager()

    class Meta:
        verbose_name = 'Дашборд'
        verbose_name_plural = 'Дашборди'
        ordering = ('sort_order', 'name')
        constraints = [
            models.UniqueConstraint(
                fields=['organization', 'owner', 'name'],
                name='uniq_dashboard_per_user',
            )
        ]

    def __str__(self):
        owner_part = self.owner.username if self.owner_id else 'shared'
        return f'{self.name} ({owner_part})'

    def can_edit(self, user) -> bool:
        """Чи може юзер редагувати layout/налаштування цього дашборда."""
        if self.owner_id == user.id:
            return True
        if self.owner_id is None and getattr(user, 'role', None) == 'admin':
            return True
        return False

    def can_view(self, user) -> bool:
        """Чи може юзер переглядати цей дашборд."""
        # Має бути в тій же організації
        user_org_id = getattr(user, 'organization_id', None)
        if user_org_id != self.organization_id:
            return False
        # Власні або спільні
        return self.owner_id == user.id or self.owner_id is None
