from django.db import models
from django.utils import timezone
from django.utils.text import slugify


class Organization(models.Model):
    """Тенант — одна клініка або організація на платформі."""

    # --- Ідентифікація ---
    name = models.CharField('Назва', max_length=200)
    short_name = models.CharField('Коротка назва', max_length=100, blank=True, default='')
    slug = models.SlugField(
        'Ідентифікатор', unique=True,
        help_text='Латинські літери/цифри. Використовується для субдомену.'
    )
    is_active = models.BooleanField('Активна', default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # --- Тріал / Підписка ---
    PLAN_CHOICES = [
        ('start',   'Старт — ₴990/міс'),
        ('clinic',  'Клініка — ₴1 990/міс'),
        ('network', 'Мережа — ₴3 990/міс'),
    ]
    plan = models.CharField(
        'Тариф', max_length=20, choices=PLAN_CHOICES, blank=True, default='',
    )

    # Ліміти по плану. plan='' (тріал) — повний доступ для оцінки.
    _PLAN_LIMITS = {
        '':        {'max_doctors': None, 'telegram': True,  'checkbox': True},
        'start':   {'max_doctors': 2,    'telegram': False, 'checkbox': False},
        'clinic':  {'max_doctors': 10,   'telegram': True,  'checkbox': True},
        'network': {'max_doctors': None, 'telegram': True,  'checkbox': True},
    }

    def _limits(self):
        return self._PLAN_LIMITS.get(self.plan, self._PLAN_LIMITS[''])

    @property
    def max_doctors(self):
        """None = без обмежень."""
        return self._limits()['max_doctors']

    @property
    def can_use_telegram(self):
        return self._limits()['telegram']

    @property
    def can_use_checkbox(self):
        return self._limits()['checkbox']
    trial_expires_at = models.DateTimeField(
        'Доступ до', null=True, blank=True,
        help_text='Якщо вказано — акаунт заблокується після цієї дати.',
    )

    @property
    def is_trial_expired(self):
        if self.trial_expires_at is None:
            return False
        return timezone.now() > self.trial_expires_at

    @property
    def trial_days_left(self):
        if self.trial_expires_at is None:
            return None
        delta = self.trial_expires_at - timezone.now()
        return max(0, delta.days)

    # --- Контакти ---
    address = models.CharField('Адреса', max_length=300, blank=True, default='')
    phone = models.CharField('Телефон', max_length=50, blank=True, default='')
    email = models.EmailField('Email', blank=True, default='')
    work_hours = models.CharField('Години роботи', max_length=100, blank=True, default='')
    website = models.CharField('Веб-сайт / домен', max_length=200, blank=True, default='')

    # --- Налаштування ---
    currency_symbol = models.CharField('Символ валюти', max_length=5, default='₴')
    bot_base_url = models.CharField(
        'Адреса сайту (для PDF через Telegram)',
        max_length=200, blank=True, default='',
        help_text='Наприклад: https://crm.kizuna.com.ua',
    )

    # --- Інтеграції ---
    telegram_bot_token = models.CharField(
        'Telegram Bot Token', max_length=200, blank=True, default='',
        help_text='Отримати у @BotFather. Наприклад: 123456:ABC-DEF...',
    )
    checkbox_license_key = models.CharField(
        'Checkbox License Key', max_length=100, blank=True, default='',
    )
    checkbox_pin = models.CharField(
        'Checkbox PIN', max_length=20, blank=True, default='',
    )
    webhook_secret = models.CharField(
        'Telegram Webhook Secret', max_length=256, blank=True, default='',
        help_text='Автоматично генерується при реєстрації webhook. Не змінювати вручну.',
    )

    class Meta:
        verbose_name = 'Організація'
        verbose_name_plural = 'Організації'

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)
