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
        # рецепція: доступ до розділів налаштовує головний адміністратор (ANVAR 01.11)
        RECEPTION = 'reception', 'Адміністратор рецепції'

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.DOCTOR,
    )

    class SalaryType(models.TextChoices):
        FIXED = 'fixed', 'Фіксована (грн/міс)'
        PERCENT = 'percent', 'Відсоток від виручки'
        FIXED_PLUS_PERCENT = 'fixed_percent', 'Фікс + відсоток'
        PER_SHIFT = 'per_shift', 'Ставка за зміну'
        HOURLY = 'hourly', 'Погодинна'

    salary_type = models.CharField(
        'Тип нарахування', max_length=20,
        choices=SalaryType.choices, default=SalaryType.PERCENT
    )
    salary_fixed = models.DecimalField(
        'Фіксована ставка, ₴/міс', max_digits=10, decimal_places=2, default=0
    )
    salary_percent = models.DecimalField(
        'Відсоток від виручки, %', max_digits=5, decimal_places=2, default=0
    )
    salary_per_shift = models.DecimalField(
        'Ставка за зміну, ₴', max_digits=8, decimal_places=2, default=0,
    )
    salary_hourly = models.DecimalField(
        'Ставка за годину, ₴', max_digits=8, decimal_places=2, default=0,
    )

    organization = models.ForeignKey(
        'clinic.Organization',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='users',
        verbose_name='Організація',
    )

    # Постійний колір людини в графіку роботи — ключ палітри з
    # apps/accounts/staff_colors.py. Видається сам при першому показі графіка
    # і далі не змінюється: людину впізнають за кольором, не читаючи імені.
    shift_color = models.CharField('Колір у графіку', max_length=16, blank=True, default='')

    # ANVAR 01.11: власник — адміністратор, не лікар, а його пропонувало лікарем у прийомах.
    takes_visits = models.BooleanField(
        'Веде прийоми', default=True,
        help_text='Показувати серед лікарів і виконавців у прийомах, розкладі й стаціонарі',
    )

    def is_admin(self):
        return self.role == self.Role.ADMIN

    @classmethod
    def practitioners(cls, org, keep=None, roles=('admin', 'doctor')):
        """Хто веде прийоми в клініці: потрібні ролі з галочкою «Веде прийоми». keep — id
        людини, яку лишити в списку без галочки (вона вже стоїть у записі, що редагують);
        roles=None — усі ролі (виконавець у розкладі)."""
        from django.db.models import Q
        q = Q(organization=org, takes_visits=True, is_active=True)   # звільнених не пропонуємо
        if roles:
            q &= Q(role__in=roles)
        if keep:
            q |= Q(organization=org, pk=keep)
        return cls.objects.filter(q)

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


from .models_payroll import Shift, PayrollPeriod  # noqa: E402, F401
