import secrets

from django.conf import settings
from django.db import models


def _generate_token() -> str:
    """32-char URL-safe token."""
    return secrets.token_urlsafe(24)


class CardDAVToken(models.Model):
    """Токен для CardDAV-доступу. Один на user (1:1).

    Окремий від основного пароля, бо телефон зберігає у plain (Basic Auth).
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='carddav_token',
    )
    token = models.CharField(max_length=64, unique=True, default=_generate_token)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    sync_token = models.PositiveBigIntegerField(default=1)  # +1 при кожній зміні клієнтів

    class Meta:
        verbose_name = 'CardDAV токен'
        verbose_name_plural = 'CardDAV токени'

    def __str__(self):
        return f'{self.user} · {self.token[:8]}…'

    def regenerate(self):
        self.token = _generate_token()
        self.save(update_fields=['token'])

    @classmethod
    def get_or_create_for(cls, user):
        obj, _ = cls.objects.get_or_create(user=user)
        return obj
