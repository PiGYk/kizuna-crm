from django.db import models
from django.conf import settings


class TelegramChat(models.Model):
    tg_user_id = models.BigIntegerField(unique=True)
    tg_username = models.CharField(max_length=100, blank=True)
    tg_first_name = models.CharField(max_length=100, blank=True)
    tg_last_name = models.CharField(max_length=100, blank=True)
    client = models.OneToOneField(
        'clients.Client', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='tg_chat'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_message_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-last_message_at']
        verbose_name = 'Telegram чат'
        verbose_name_plural = 'Telegram чати'

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
    text = models.TextField()
    tg_message_id = models.BigIntegerField(null=True, blank=True)
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='tg_messages'
    )
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = 'Повідомлення'
