from datetime import time as dt_time

from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from .uploads import org_logo_path


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
        # Стара сітка — лише щоб старі записи читались. Не продається
        # (у PLANS її нема); жодна клініка на ній не стоїть (31.10.2026).
        ('base',    'База (стара сітка)'),
        ('support', 'Підтримка (стара сітка)'),
        ('custom',  'Індивідуальний (стара сітка)'),
    ]
    # Що продаємо зараз — вкладка «Підписка» показує лише їх.
    CURRENT_PLANS = ('start', 'clinic', 'network')
    plan = models.CharField(
        'Тариф', max_length=20, choices=PLAN_CHOICES, blank=True, default='',
    )

    # Тарифи РІЗНЯТЬСЯ РІВНЕМ СУПРОВОДУ, а не обрізаним функціоналом: клініка на
    # найдешевшому тарифі отримує систему цілком. Різати телеграм і фіскалізацію
    # у малої клініки — найшвидший спосіб її втратити.
    # plan='' (тріал) — теж повний доступ.
    _FULL = {'max_doctors': None, 'telegram': True, 'checkbox': True}
    _PLAN_LIMITS = {
        '':        _FULL,
        'base':    _FULL,
        'support': _FULL,
        'custom':  _FULL,
        # Легасі-ключі старої сітки — лишені, щоб уже заведені організації
        # не втратили доступ до модулів після переходу на нові тарифи.
        'start':   _FULL,
        'clinic':  _FULL,
        'network': _FULL,
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
    # Логотип — у теці своєї клініки (org_<pk>/logo.*), як і решта файлів: роздача
    # /media/ пускає до org_<pk>/ лише працівників цієї клініки. Спільна тека
    # org_logos/ не проходила цю перевірку — логотип завжди віддавав 404 (31.10.2026).
    logo = models.ImageField(
        'Логотип', upload_to=org_logo_path, null=True, blank=True,
        help_text='PNG, JPG або WEBP, рекомендований розмір 200×60 px',
    )
    primary_color = models.CharField(
        'Акцентний колір', max_length=7, default='#DEAA01',
        help_text='Кнопки, активні елементи. HEX, наприклад #DEAA01',
    )
    sidebar_color = models.CharField(
        'Колір бічної панелі', max_length=7, default='#12100F',
        help_text='Фон меню. HEX, наприклад #12100F',
    )
    # ANVAR 02.11: «серый — глаза не так устают, как от белого»
    PAGE_BACKGROUNDS = [('light', 'Світлий'), ('gray', 'Сірий — мʼякший для очей')]
    page_background = models.CharField('Фон сторінок', max_length=10, choices=PAGE_BACKGROUNDS, default='light')

    # --- Контакти ---
    address = models.CharField('Адреса', max_length=300, blank=True, default='')
    phone = models.CharField('Телефон', max_length=50, blank=True, default='')
    email = models.EmailField('Email', blank=True, default='')
    work_hours = models.CharField('Години роботи', max_length=100, blank=True, default='')
    website = models.CharField('Веб-сайт / домен', max_length=200, blank=True, default='')
    # Посилання на відео «як нас знайти» — бот чіпляє його до підтвердження
    # запису (запит Каті 29.09.2026). Поле клінічне, не константа: CRM
    # багатотенантна, у кожної клініки свій маршрут.
    route_video_url = models.CharField(
        'Відео «як нас знайти»', max_length=300, blank=True, default='',
        help_text='Посилання на відео або карту з дорогою до клініки. '
                  'Бот додасть його до підтвердження запису.')

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
    # Структура: {"doctor": {"telegram": false, ...}, "assistant": {...}, "reception": {...}}
    # З 01.11.2026 кожен пункт діє і на вході в розділ (apps/accounts/menu_access.py), а «Рахунки (всі)» —
    # чи бачить роль усі рахунки, чи лише свої (до того лікар завжди бачив лише свої, решта — всі).
    MENU_ITEMS = [
        ('telegram',   'Telegram чати'),
        ('broadcast',  'Розсилки'),
        ('analytics',  'Аналітика'),
        ('debtors',    'Боржники'),
        ('revenue',    'Доходність'),
        ('finance',    'Фінанси'),
        ('billing',    'Рахунки (всі)'),
        ('deposits',   'Депозити'),
        ('shifts',     'Графік роботи'),
    ]
    ROLES_WITH_MENU = [
        ('doctor',    'Лікар'),
        ('assistant', 'Асистент'),
        ('reception', 'Адміністратор рецепції'),
    ]
    DEFAULT_MENU_CONFIG = {
        'doctor':    {'telegram': False, 'broadcast': False, 'analytics': False, 'debtors': False, 'revenue': False, 'finance': False, 'billing': False, 'deposits': False, 'shifts': True},
        'assistant': {'telegram': True,  'broadcast': False, 'analytics': False, 'debtors': False, 'revenue': False, 'finance': True,  'billing': True,  'deposits': True,  'shifts': True},
        'reception': {'telegram': True,  'broadcast': False, 'analytics': False, 'debtors': True,  'revenue': False, 'finance': True,  'billing': True,  'deposits': True,  'shifts': True},
    }
    role_menu_config = models.JSONField(
        'Доступ до меню по ролях',
        default=dict,
        blank=True,
    )
    # Норми бланків аналізів, які клініка змінила під свій аналізатор: {вид: {код: [від, до]}}.
    # Порожньо — типові (apps/clients/lab_panels.py). Запам'ятовуються з бланку самі.
    lab_norms = models.JSONField('Свої норми аналізів', default=dict, blank=True)
    # Свій перелік показників бланку (ANVAR 02.11: «у різних аналізаторів різні показники»):
    # {панель: {вид: [{code, name, unit, low, high}, …]}}; зберігається галочкою на бланку.
    lab_templates = models.JSONField('Свої бланки аналізів', default=dict, blank=True)
    visit_labels = models.JSONField(
        'Свої назви розділів прийому', default=dict, blank=True,
        help_text='Напр. {"complaint": "Анамнез"}. Порожньо — стандартні назви.',
    )

    def get_menu_config(self):
        """Повертає конфіг з fallback на дефолти.

        Копія має бути глибокою: .copy() віддає ті самі вкладені словники, і
        нижній update() правив би DEFAULT_MENU_CONFIG самого класу — тобто
        налаштування однієї клініки протікали б у дефолти всіх інших до
        перезапуску процесу.
        """
        cfg = {role: items.copy() for role, items in self.DEFAULT_MENU_CONFIG.items()}
        saved = self.role_menu_config or {}
        for role in cfg:
            if role in saved:
                cfg[role].update(saved[role])
        return cfg

    # ── Свої назви розділів прийому (31.10.2026, ANVAR) ──
    # Порожньо — як у всіх. Ключі: complaint, diagnosis, treatment, notes (поля
    # прийому), documents і documents_hint (блок файлів у формі прийому);
    # suggest_diagnosis / suggest_drugs — у яке поле чіпляти підказки минулих
    # діагнозів і препаратів зі складу, якщо клініка пише діагноз не в «Діагноз».
    VISIT_TEXT_FIELDS = ('complaint', 'exam', 'diagnosis', 'treatment', 'notes')

    def _visit_suggest(self, kind, default):
        value = (self.visit_labels or {}).get(f'suggest_{kind}', default)
        return value if value in self.VISIT_TEXT_FIELDS else default

    @property
    def visit_suggest_diagnosis(self):
        return self._visit_suggest('diagnosis', 'diagnosis')

    @property
    def visit_suggest_drugs(self):
        drugs = self._visit_suggest('drugs', 'treatment')
        return 'treatment' if drugs == self.visit_suggest_diagnosis else drugs

    @property
    def uses_visit_exam(self):
        """Окремий розділ «Клінічний огляд» у прийомі — лише якщо клініка дала йому назву."""
        return bool((self.visit_labels or {}).get('exam'))

    def can_see_menu(self, role, item):
        """Чи може роль бачити пункт меню. Головний адміністратор бачить усе; кожна роль із
        ROLES_WITH_MENU — за налаштуваннями клініки (нова роль без цього бачила б усе, як адмін)."""
        if role not in self.DEFAULT_MENU_CONFIG:
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
        # Публічне API тримає CORS-whitelist сайтів клінік у кеші. Скидаємо тут,
        # а не у формі, щоб зміна поля «Веб-сайт» діяла одразу незалежно від того,
        # звідки її зберегли (налаштування, адмінка, скрипт).
        try:
            from django.core.cache import cache
            cache.delete('public_api:org_site_origins')
        except Exception:
            pass


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


class DemoLead(models.Model):
    """Заявка на демо з лендінгу: людина лишила номер -> потрапила в демо.
    Скіф забирає нові (notified=False), шле Олегу і ставить задачу в планьорку."""
    phone = models.CharField(max_length=20, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, default='')
    utm_source = models.CharField(max_length=120, blank=True, default='')
    utm_medium = models.CharField(max_length=120, blank=True, default='')
    utm_campaign = models.CharField(max_length=120, blank=True, default='')
    referer = models.CharField(max_length=500, blank=True, default='')
    visit_count = models.PositiveIntegerField(default=1)
    notified = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['-created_at'])]

    def __str__(self):
        return f'{self.phone} ({self.created_at:%Y-%m-%d %H:%M})'


class DemoTenant(models.Model):
    """Пул готових гостьових демо-клінік.

    Генерація клініки триває ~8 с — тримати людину стільки на попапі не можна,
    тому клініки готуються заздалегідь у фоні. Гість забирає вільну миттєво,
    вночі зайняті видаляються разом з усіма даними.
    """
    organization = models.OneToOneField(
        'clinic.Organization', on_delete=models.CASCADE, related_name='demo_tenant')
    username = models.CharField(max_length=150)
    created_at = models.DateTimeField(auto_now_add=True)
    taken_at = models.DateTimeField(null=True, blank=True, db_index=True)
    lead = models.ForeignKey(
        'clinic.DemoLead', null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        state = 'зайнята' if self.taken_at else 'вільна'
        return f'{self.organization.slug} ({state})'


class ContactLead(models.Model):
    """Заявка «зв'яжіться зі мною» з лендінгу: людина лишила ім'я, телефон і пошту.
    На відміну від DemoLead — це прямий запит на контакт, а не вхід у демо.
    Скіф забирає нові (notified=False), шле Олегу і ставить задачу в планьорку."""
    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=20, db_index=True)
    email = models.EmailField(max_length=254)
    message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, default="")
    utm_source = models.CharField(max_length=120, blank=True, default="")
    utm_medium = models.CharField(max_length=120, blank=True, default="")
    utm_campaign = models.CharField(max_length=120, blank=True, default="")
    referer = models.CharField(max_length=500, blank=True, default="")
    notified = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["-created_at"])]

    def __str__(self):
        return f"{self.name} · {self.phone} ({self.created_at:%Y-%m-%d %H:%M})"


class TrialEmail(models.Model):
    """Облік листів супроводу тріалу: один вид листа — один раз на клініку."""
    from apps.clinic.trial_emails import KINDS as _KINDS

    organization = models.ForeignKey(
        'clinic.Organization', on_delete=models.CASCADE,
        related_name='trial_emails', verbose_name='Клініка',
    )
    kind = models.CharField('Вид листа', max_length=20, choices=_KINDS)
    to_email = models.EmailField('Кому')
    sent_at = models.DateTimeField('Надіслано', auto_now_add=True)
    ok = models.BooleanField('Успішно', default=True)
    error = models.TextField('Помилка', blank=True)

    class Meta:
        verbose_name = 'Лист супроводу тріалу'
        verbose_name_plural = 'Листи супроводу тріалу'
        ordering = ('-sent_at',)
        constraints = [
            models.UniqueConstraint(
                fields=('organization', 'kind'),
                condition=models.Q(ok=True),
                name='uniq_trial_email_per_org_kind',
            ),
        ]

    def __str__(self):
        return f'{self.organization} — {self.get_kind_display()}'


class InboxReply(models.Model):
    """Опрацьована відповідь клініки: щоб на той самий лист не готувати чернетку двічі."""
    organization = models.ForeignKey(
        'clinic.Organization', on_delete=models.CASCADE,
        related_name='inbox_replies', verbose_name='Клініка',
    )
    message_id = models.CharField('Id листа', max_length=255, unique=True)
    from_email = models.EmailField('Від кого')
    question = models.TextField('Що написали', blank=True)
    draft = models.TextField('Чернетка відповіді', blank=True)
    auto_sent = models.BooleanField('Відповіли автоматично', default=False)
    hold_reason = models.CharField('Чому чекає людину', max_length=200, blank=True)
    escalated = models.BooleanField('Передано Славі', default=False)
    created_at = models.DateTimeField('Опрацьовано', auto_now_add=True)

    class Meta:
        verbose_name = 'Відповідь клініки'
        verbose_name_plural = 'Відповіді клінік'
        ordering = ('-created_at',)

    def __str__(self):
        return f'{self.from_email} — {self.created_at:%d.%m.%Y}'
