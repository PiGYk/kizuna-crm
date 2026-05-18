"""Celery tasks для розсилки повідомлень через Telegram."""
import time
import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=0)
def send_broadcast(self, broadcast_id):
    from django.utils import timezone
    from datetime import timedelta
    from .models import Broadcast, BroadcastRecipient, TelegramChat, TelegramMessage
    from .views import _send_tg

    try:
        broadcast = Broadcast.objects.select_related('organization').get(pk=broadcast_id)
    except Broadcast.DoesNotExist:
        logger.error('Broadcast %s not found', broadcast_id)
        return

    org = broadcast.organization

    # Всі чати організації
    chats = list(TelegramChat.objects.filter(organization=org))

    # Чати що вже отримали ЦЮ розсилку (захист від дублів при retry)
    already_sent_ids = set(
        BroadcastRecipient.objects.filter(
            broadcast=broadcast,
            status=BroadcastRecipient.Status.SENT,
        ).values_list('chat_id', flat=True)
    )

    # Cooldown — чати що отримували БУДЬ-ЯКУ розсилку протягом N днів
    cooldown_excluded_ids = set()
    if broadcast.cooldown_days > 0:
        since = timezone.now() - timedelta(days=broadcast.cooldown_days)
        cooldown_excluded_ids = set(
            BroadcastRecipient.objects.filter(
                chat__organization=org,
                status=BroadcastRecipient.Status.SENT,
                sent_at__gte=since,
            ).exclude(broadcast=broadcast)
            .values_list('chat_id', flat=True)
        )

    # Фільтруємо отримувачів
    to_send = [
        c for c in chats
        if c.pk not in already_sent_ids and c.pk not in cooldown_excluded_ids
    ]
    skipped = len(chats) - len(already_sent_ids) - len(to_send)

    broadcast.status = Broadcast.Status.SENDING
    broadcast.total = len(to_send)
    broadcast.sent = 0
    broadcast.failed = 0
    broadcast.save(update_fields=['status', 'total', 'sent', 'failed'])

    # Записуємо пропущених (cooldown)
    if cooldown_excluded_ids:
        BroadcastRecipient.objects.bulk_create([
            BroadcastRecipient(
                broadcast=broadcast,
                chat_id=chat_id,
                status=BroadcastRecipient.Status.SKIPPED,
            )
            for chat_id in cooldown_excluded_ids
            if chat_id not in already_sent_ids
        ], ignore_conflicts=True)

    sent = 0
    failed = 0

    for chat in to_send:
        status = BroadcastRecipient.Status.SENT
        tg_msg_id = None
        try:
            result = _send_tg(chat.tg_user_id, broadcast.text, org=org)
            if result.get('ok'):
                sent += 1
                tg_msg_id = result.get('result', {}).get('message_id')
            else:
                logger.warning('TG error for chat %s: %s', chat.tg_user_id, result)
                status = BroadcastRecipient.Status.FAILED
                failed += 1
        except Exception as exc:
            logger.error('Exception sending to %s: %s', chat.tg_user_id, exc)
            status = BroadcastRecipient.Status.FAILED
            failed += 1

        BroadcastRecipient.objects.get_or_create(
            broadcast=broadcast,
            chat=chat,
            defaults={'status': status},
        )

        # Зберігаємо в історії чату (щоб було видно в розділі Telegram)
        if status == BroadcastRecipient.Status.SENT:
            TelegramMessage.objects.create(
                chat=chat,
                direction=TelegramMessage.Direction.OUT,
                text=broadcast.text,
                tg_message_id=tg_msg_id,
                is_read=True,
            )

        # Telegram дозволяє ~30 повідомлень/сек — беремо запас
        time.sleep(0.05)

    broadcast.status = Broadcast.Status.DONE
    broadcast.sent = sent
    broadcast.failed = failed
    broadcast.save(update_fields=['status', 'sent', 'failed'])

    logger.info(
        'Broadcast %s done: %s sent, %s failed, %s skipped (cooldown)',
        broadcast_id, sent, failed, skipped,
    )
