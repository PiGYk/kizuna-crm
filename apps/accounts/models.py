import secrets
from datetime import timedelta

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = 'admin', 'Адміністратор'
        DOCTOR = 'doctor', 'Лікар'
        ASSISTANT = 'assistant', 'Асистент'

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.DOCTOR,
    )
    organization = models.ForeignKey(
        'clinic.Organization',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='users',
        verbose_name='Організація',
    )

    def is_admin(self):
        return self.role == self.Role.ADMIN

    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.get_role_display()})"


class EmailVerification(models.Model):
    """Токен підтвердження email при реєстрації."""
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name='email_verification',
    )
    token = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    TOKEN_TTL_HOURS = 48

    @classmethod
    def create_for(cls, user: User) -> 'EmailVerification':
        cls.objects.filter(user=user).delete()
        return cls.objects.create(
            user=user,
            token=secrets.token_urlsafe(40),
        )

    def is_expired(self) -> bool:
        return timezone.now() > self.created_at + timedelta(hours=self.TOKEN_TTL_HOURS)

    def __str__(self):
        return f"Verification({self.user.username})"
