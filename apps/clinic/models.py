from datetime import time as dt_time

from django.db import models
from django.utils import timezone
from django.utils.text import slugify


def _default_work_days():
    """Пн–Пт для щойно створеної клініки. Кожна організація змінює графік під себе
    в налаштуваннях — тут має бути нейтральний дефолт, а не графік однієї клініки."""
    return [0, 1, 2, 3, 4]


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

    # --- Персонал ---
    default_doctor = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='+',
        verbose_name='Лікар за замовчуванням',
        help_text='Підставляється у нові візити, вакцини, записи та рахунки',
    )

    # --- Дизайн ---
    logo = models.ImageField(
        'Логотип', upload_to='org_logos/', null=True, blank=True,
        help_text='PNG або SVG, рекомендований розмір 200×60 px',
    )
    primary_color = models.CharField(
        'Акцентний колір', max_length=7, default='#DEAA01',
        help_text='Кнопки, активні елементи. HEX, наприклад #DEAA01',
    )
    sidebar_color = models.CharField(
        'Колір бічної панелі', max_length=7, default='#12100F',
        help_text='Фон меню. HEX, наприклад #12100F',
    )

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

    # ── Графік роботи ──
    work_days = models.JSONField(
        'Робочі дні', default=_default_work_days,
        help_text='Список робочих днів: 0=Пн, 1=Вт, 2=Ср, 3=Чт, 4=Пт, 5=Сб, 6=Нд'
    )
    work_start = models.TimeField('Початок роботи', default=dt_time(10, 0))
    work_end = models.TimeField('Кінець роботи', default=dt_time(18, 0))
    slot_duration = models.PositiveIntegerField('Тривалість слоту (хв)', default=30)

    # ── Нотифікації ──
    notify_appointment_24h = models.BooleanField('Нагадування за 24 год', default=True)
    notify_appointment_2h = models.BooleanField('Нагадування за 2 год', default=True)
    notify_vaccines = models.BooleanField('Нагадування про вакцини', default=True)

    # Конфігурація видимості меню по ролях
    # Структура: {"doctor": {"telegram": false, ...}, "assistant": {...}}
    MENU_ITEMS = [
        ('telegram',   'Telegram чати'),
        ('broadcast',  'Розсилки'),
        ('analytics',  'Аналітика'),
        ('debtors',    'Боржники'),
        ('revenue',    'Доходність'),
        ('finance',    'Фінанси'),
        ('billing',    'Рахунки (всі)'),
    ]
    ROLES_WITH_MENU = [
        ('doctor',    'Лікар'),
        ('assistant', 'Асистент'),
    ]
    DEFAULT_MENU_CONFIG = {
        'doctor':    {'telegram': False, 'broadcast': False, 'analytics': False, 'debtors': False, 'revenue': False, 'finance': False, 'billing': True},
        'assistant': {'telegram': True,  'broadcast': False, 'analytics': False, 'debtors': False, 'revenue': False, 'finance': True,  'billing': True},
    }
    role_menu_config = models.JSONField(
        'Доступ до меню по ролях',
        default=dict,
        blank=True,
    )

    def get_menu_config(self):
        """Повертає конфіг з fallback на дефолти."""
        cfg = self.DEFAULT_MENU_CONFIG.copy()
        saved = self.role_menu_config or {}
        for role in cfg:
            if role in saved:
                cfg[role].update(saved[role])
        return cfg

    def can_see_menu(self, role, item):
        """Чи може роль бачити пункт меню."""
        if role not in ('doctor', 'assistant'):
            return True  # admin бачить все
        return self.get_menu_config().get(role, {}).get(item, True)

    class Meta:
        verbose_name = 'Організація'
        verbose_name_plural = 'Організації'

    def __str__(self):
        return self.name

    def get_default_doctor(self, fallback=None):
        """Повертає дефолтного лікаря або fallback (зазвичай request.user)."""
        return self.default_doctor or fallback

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class PaymentTransaction(models.Model):
    """Лог WayForPay транзакцій для idempotency. Дубль callback з тим самим
    order_ref не повинен повторно подовжувати тріал."""

    order_ref = models.CharField('Order reference', max_length=200, unique=True)
    organization = models.ForeignKey(
        'clinic.Organization',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='payment_transactions',
    )
    plan_key = models.CharField('Тариф', max_length=50, blank=True)
    amount = models.DecimalField('Сума', max_digits=10, decimal_places=2, default=0)
    status = models.CharField('Статус', max_length=50)
    raw_payload = models.JSONField('Сирий payload', default=dict, blank=True)
    processed_at = models.DateTimeField('Оброблено', auto_now_add=True)

    class Meta:
        verbose_name = 'Платіжна транзакція'
        verbose_name_plural = 'Платіжні транзакції'
        indexes = [
            models.Index(fields=['organization', '-processed_at']),
        ]

    def __str__(self):
        return f'{self.order_ref} ({self.status})'
