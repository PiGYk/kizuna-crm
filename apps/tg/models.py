from django.db import models
from django.conf import settings
from apps.clinic.managers import OrgManager
from apps.clinic.uploads import tg_media_path


class TelegramChat(models.Model):
    tg_user_id = models.BigIntegerField()
    tg_username = models.CharField(max_length=100, blank=True)
    tg_first_name = models.CharField(max_length=100, blank=True)
    tg_last_name = models.CharField(max_length=100, blank=True)
    client = models.ForeignKey(
        'clients.Client', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='tg_chats'
    )
    organization = models.ForeignKey(
        'clinic.Organization',
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='tg_chats',
        verbose_name='Організація',
    )
    is_staff = models.BooleanField(
        'Співробітник',
        default=False,
        help_text='Позначити як співробітника — отримуватиме системні сповіщення.',
    )
    receive_leads = models.BooleanField(
        'Заявки з сайту',
        default=False,
        help_text='Отримує повідомлення про нові заявки з сайту.',
    )
    receive_messages = models.BooleanField(
        'Нові повідомлення',
        default=False,
        help_text='Отримує сповіщення коли клієнт пише в бота.',
    )
    avatar_file_id = models.CharField(max_length=200, blank=True, default='')
    onboarding_state = models.JSONField(
        'Стан онбордингу',
        default=dict, blank=True,
        help_text='Тимчасовий state-machine для реєстрації через бота: {"step": "...", "data": {...}}',
    )
    autodialog_state = models.JSONField(
        'Стан автодіалогу',
        default=dict, blank=True,
        help_text=(
            'Автодіалог з незареєстрованими: {"stage": "offered|declined|booking|done", '
            '"data": {...}}. Окремо від onboarding_state, бо той перезаписується цілком.'
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_message_at = models.DateTimeField(null=True, blank=True)

    objects = OrgManager()

    class Meta:
        ordering = ['-last_message_at']
        unique_together = ('tg_user_id', 'organization')
        verbose_name = 'Telegram чат'
        verbose_name_plural = 'Telegram чати'
        indexes = [
            models.Index(fields=['organization', '-last_message_at'], name='tgchat_org_last_idx'),
        ]

    def __str__(self):
        return self.display_name

    @property
    def display_name(self):
        if self.client:
            return str(self.client)
        name = f"{self.tg_first_name} {self.tg_last_name}".strip()
        return name or self.tg_username or f"id{self.tg_user_id}"

    @property
    def unread_count(self):
        return self.messages.filter(direction='in', is_read=False).count()


class TelegramMessage(models.Model):
    class Direction(models.TextChoices):
        IN = 'in', 'Від клієнта'
        OUT = 'out', 'Від нас'

    chat = models.ForeignKey(TelegramChat, on_delete=models.CASCADE, related_name='messages')
    direction = models.CharField(max_length=3, choices=Direction.choices)
    text = models.TextField(blank=True)
    media_type = models.CharField(max_length=20, blank=True)  # 'photo','image','pdf','document','voice','video','animation','audio','video_note','sticker','contact','location'
    media_file = models.FileField(upload_to=tg_media_path, blank=True)
    media_filename = models.CharField(max_length=255, blank=True)  # оригінальне ім'я файлу
    tg_message_id = models.BigIntegerField(null=True, blank=True)
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='tg_messages'
    )
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    # Відповідь на конкретне повідомлення (Олег 25.11.2026): нашу CRM шле з reply_parameters,
    # клієнтську бачимо з reply_to_message вебхука. reply_quote — знімок цитати
    # {"ours": bool, "text": "…"}: автовідповіді бота лежать у CRM без tg_message_id,
    # а оригінал можуть видалити — цитата лишається.
    reply_to = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    reply_quote = models.JSONField(null=True, blank=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = 'Повідомлення'
        constraints = [
            models.UniqueConstraint(
                fields=['chat', 'tg_message_id'],
                condition=models.Q(tg_message_id__isnull=False),
                name='tgmsg_chat_tgmsgid_unique',
            ),
        ]
        indexes = [
            models.Index(fields=['chat', '-id'], name='tgmsg_chat_id_idx'),
            models.Index(fields=['chat', 'direction', 'is_read'], name='tgmsg_chat_dir_read_idx'),
        ]

    def __str__(self):
        preview = (self.text[:40] + '...') if len(self.text) > 40 else self.text
        return f'{self.get_direction_display()}: {preview}'

    @property
    def quote_text(self):
        """Короткий текст цитати, коли на це повідомлення відповідають: текст або що за медіа."""
        label = MEDIA_QUOTE_LABELS.get(self.media_type, '')
        if self.media_type in ('voice', 'location'):
            return label
        text = ' '.join((self.text or '').split())
        if self.media_type == 'sticker':  # text = емодзі стікера або «[анім стікер]»
            return f'{label} {text}' if text and not text.startswith('[') else label
        if not text and self.media_type in ('pdf', 'document'):
            text = self.media_filename
        text = text[:QUOTE_MAX]
        if label and text:
            return f'{label} · {text}'
        return text or label or '…'

    @property
    def reply_info(self):
        """Цитата над бульбашкою-відповіддю: {'id', 'ours', 'text'} або None.
        id — оригінал у CRM (None, якщо його тут нема): клік по цитаті веде до нього."""
        q = self.reply_quote
        if not q:
            return None
        return {'id': self.reply_to_id, 'ours': bool(q.get('ours')), 'text': q.get('text') or '…'}

    @property
    def can_reply(self):
        """Відповісти через Telegram можна лише на повідомлення, яке Telegram підтвердив (є tg_message_id)."""
        return bool(self.tg_message_id)


QUOTE_MAX = 200
MEDIA_QUOTE_LABELS = {
    'photo': 'Фото', 'image': 'Фото', 'pdf': 'PDF', 'document': 'Файл', 'video': 'Відео',
    'voice': 'Голосове', 'sticker': 'Стікер', 'contact': 'Контакт', 'location': 'Геолокація',
}


class QuickReplyPrompt(models.Model):
    """Зберігає стан 'staff натиснув Швидку відповідь' — mapping
    staff-повідомлення з ForceReply → цільовий чат клієнта.

    Коли staff пише reply на це повідомлення, webhook знаходить запис
    і пересилає текст target_chat. Після використання used_at ставиться.
    """
    staff_chat = models.ForeignKey(
        TelegramChat,
        on_delete=models.CASCADE,
        related_name='quick_reply_prompts',
    )
    target_chat = models.ForeignKey(
        TelegramChat,
        on_delete=models.CASCADE,
        related_name='quick_reply_inbound',
    )
    prompt_message_id = models.BigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=['staff_chat', 'prompt_message_id'])]
        verbose_name = 'Запит швидкої відповіді'
        verbose_name_plural = 'Запити швидкої відповіді'


class Broadcast(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Чернетка'
        SENDING = 'sending', 'Відправляється'
        DONE = 'done', 'Завершено'

    text = models.TextField('Текст повідомлення')
    status = models.CharField('Статус', max_length=10, choices=Status.choices, default=Status.DRAFT)
    total = models.PositiveIntegerField('Всього', default=0)
    sent = models.PositiveIntegerField('Відправлено', default=0)
    failed = models.PositiveIntegerField('Помилок', default=0)
    organization = models.ForeignKey(
        'clinic.Organization',
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='broadcasts',
        verbose_name='Організація',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        verbose_name='Автор',
    )
    cooldown_days = models.PositiveSmallIntegerField(
        'Не надсилати тим, хто отримував розсилку (днів)',
        default=0,
        help_text='0 — без обмежень',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = OrgManager()

    class Meta:
        verbose_name = 'Розсилка'
        verbose_name_plural = 'Розсилки'
        ordering = ['-created_at']

    def __str__(self):
        return f"Розсилка #{self.pk} ({self.get_status_display()})"


class BroadcastRecipient(models.Model):
    class Status(models.TextChoices):
        SENT = 'sent', 'Відправлено'
        FAILED = 'failed', 'Помилка'
        SKIPPED = 'skipped', 'Пропущено'

    broadcast = models.ForeignKey(
        Broadcast,
        on_delete=models.CASCADE,
        related_name='recipients',
        verbose_name='Розсилка',
    )
    chat = models.ForeignKey(
        TelegramChat,
        on_delete=models.CASCADE,
        related_name='broadcast_receipts',
        verbose_name='Чат',
    )
    status = models.CharField('Статус', max_length=10, choices=Status.choices, default=Status.SENT)
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Отримувач розсилки'
        verbose_name_plural = 'Отримувачі розсилки'
        unique_together = ('broadcast', 'chat')
        ordering = ['-sent_at']

    def __str__(self):
        return f'{self.chat} — {self.get_status_display()}'
