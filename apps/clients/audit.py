import json
import logging
import threading

from django.db import models
from django.conf import settings
from django.db.models.signals import pre_save, post_save, post_delete

logger = logging.getLogger(__name__)


class AuditLog(models.Model):
    """Журнал змін медичних даних."""

    class Action(models.TextChoices):
        CREATE = 'create', 'Створено'
        UPDATE = 'update', 'Змінено'
        DELETE = 'delete', 'Видалено'

    content_type = models.CharField('Тип об\'єкта', max_length=50)
    object_id = models.PositiveIntegerField('ID об\'єкта')
    object_repr = models.CharField('Об\'єкт', max_length=255)
    action = models.CharField('Дія', max_length=10, choices=Action.choices)
    changes = models.JSONField('Зміни', default=dict, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, verbose_name='Користувач',
    )
    organization = models.ForeignKey(
        'clinic.Organization', on_delete=models.CASCADE,
        null=True, blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Запис аудиту'
        verbose_name_plural = 'Журнал аудиту'
        indexes = [
            models.Index(fields=['content_type', 'object_id']),
            models.Index(fields=['organization', '-created_at']),
        ]

    def __str__(self):
        return f'{self.get_action_display()} {self.content_type} #{self.object_id}'

    @property
    def changes_display(self):
        """Людиночитабельний список змін."""
        if not self.changes:
            return []
        result = []
        for field, vals in self.changes.items():
            old = vals.get('old', '--')
            new = vals.get('new', '--')
            result.append({'field': field, 'old': old, 'new': new})
        return result


# -- Middleware для отримання поточного юзера ---------------------------------

_thread_local = threading.local()


def get_current_user():
    return getattr(_thread_local, 'user', None)


class AuditMiddleware:
    """Зберігає поточного юзера в thread-local для signals."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _thread_local.user = getattr(request, 'user', None)
        response = self.get_response(request)
        _thread_local.user = None
        return response


# -- Signal handlers ----------------------------------------------------------

def _get_org(instance):
    """Отримати organization з інстансу."""
    if hasattr(instance, 'organization_id') and instance.organization_id:
        return instance.organization
    if hasattr(instance, 'client') and hasattr(instance.client, 'organization'):
        return instance.client.organization
    if hasattr(instance, 'patient') and hasattr(instance.patient, 'client'):
        return instance.patient.client.organization
    return None


def _track_changes(instance):
    """Порівнює поточні значення з БД і повертає dict змін."""
    if not instance.pk:
        return {}
    try:
        old = type(instance).objects.get(pk=instance.pk)
    except type(instance).DoesNotExist:
        return {}

    changes = {}
    skip = {'created_at', 'updated_at', 'photo', 'image', 'file'}
    for field in instance._meta.fields:
        if field.name in skip or field.name.endswith('_id'):
            continue
        if field.primary_key:
            continue
        old_val = getattr(old, field.name)
        new_val = getattr(instance, field.name)
        if old_val != new_val:
            changes[field.verbose_name or field.name] = {
                'old': str(old_val) if old_val is not None else '--',
                'new': str(new_val) if new_val is not None else '--',
            }
    return changes


def audit_pre_save(sender, instance, **kwargs):
    """Зберігає зміни перед save для подальшого запису."""
    if instance.pk:
        instance._audit_changes = _track_changes(instance)
    else:
        instance._audit_changes = None  # create


def audit_post_save(sender, instance, created, **kwargs):
    """Записує в аудит після save."""
    user = get_current_user()
    if user and not getattr(user, 'is_authenticated', False):
        user = None

    if created:
        AuditLog.objects.create(
            content_type=sender.__name__,
            object_id=instance.pk,
            object_repr=str(instance)[:255],
            action=AuditLog.Action.CREATE,
            changes={},
            user=user,
            organization=_get_org(instance),
        )
    elif hasattr(instance, '_audit_changes') and instance._audit_changes:
        AuditLog.objects.create(
            content_type=sender.__name__,
            object_id=instance.pk,
            object_repr=str(instance)[:255],
            action=AuditLog.Action.UPDATE,
            changes=instance._audit_changes,
            user=user,
            organization=_get_org(instance),
        )


def audit_post_delete(sender, instance, **kwargs):
    """Записує видалення в аудит."""
    user = get_current_user()
    if user and not getattr(user, 'is_authenticated', False):
        user = None

    AuditLog.objects.create(
        content_type=sender.__name__,
        object_id=instance.pk,
        object_repr=str(instance)[:255],
        action=AuditLog.Action.DELETE,
        changes={},
        user=user,
        organization=_get_org(instance),
    )


# -- Реєстрація signals ------------------------------------------------------

AUDITED_MODELS = []


def register_audit(model):
    """Підключає audit signals до моделі."""
    pre_save.connect(audit_pre_save, sender=model)
    post_save.connect(audit_post_save, sender=model)
    post_delete.connect(audit_post_delete, sender=model)
    AUDITED_MODELS.append(model)
