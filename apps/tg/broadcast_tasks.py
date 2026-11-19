"""Celery tasks для розсилки повідомлень через Telegram."""
import time
import logging
from celery import shared_task

from apps.clinic.tenant import org_context

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=2, default_retry_delay=10)
def notify_staff_new_message_task(self, chat_id, preview_text):
    """Async-варіант _notify_staff_new_message — звільняє webhook handler
    від 500ms+ синхронних TG API calls. Telegram не буде retry-ати webhook.
    """
    from .models import TelegramChat
    from .views import _send_tg, _esc

    try:
        # _base_manager — обхід OrgManager fail-closed (немає org context у Celery).
        chat = TelegramChat._base_manager.select_related('client', 'organization').get(pk=chat_id)
    except TelegramChat.DoesNotExist:
        logger.warning('notify_staff_new_message_task: chat %s not found', chat_id)
        return
    # неробочий час (Олег 19.11.2026): уночі персонал не смикаємо — зранку прийде все разом (deliver_night_messages)
    from . import quiet
    if quiet.is_quiet(chat.organization):
        return

    with org_context(chat.organization):
        try:
            staff_chats = TelegramChat.objects.filter(
                organization=chat.organization,
                is_staff=True,
                receive_messages=True,
            ).exclude(tg_user_id=chat.tg_user_id)

            if not staff_chats.exists():
                return

            if chat.client:
                client_name = str(chat.client)
            else:
                client_name = f'{chat.display_name} (неверифікований)'
            preview = (preview_text or '')[:150]
            # _esc: текст клієнта може містити '<' — без екранування TG відхиляє
            # сповіщення цілком і персонал мовчки не дізнається про повідомлення.
            text = (
                f'💬 <b>Нове повідомлення</b>\n\n'
                f'Від: <b>{_esc(client_name)}</b>\n'
                f'{_esc(preview)}'
            )
            reply_markup = {
                'inline_keyboard': [[
                    {'text': '✍️ Швидка відповідь', 'callback_data': f'quickreply:{chat.pk}'}
                ]]
            }
            for sc in staff_chats:
                try:
                    _send_tg(sc.tg_user_id, text, reply_markup=reply_markup, org=chat.organization)
                except Exception as exc:
                    logger.warning('notify staff %s failed: %s', sc.tg_user_id, exc)
        except Exception as exc:
            logger.exception('notify_staff_new_message_task crashed: %s', exc)


@shared_task(bind=True, max_retries=0)
def send_broadcast(self, broadcast_id):
    from django.utils import timezone
    from datetime import timedelta
    from .models import Broadcast, BroadcastRecipient, TelegramChat, TelegramMessage
    from .views import _send_tg

    try:
        # _base_manager — обхід OrgManager fail-closed у Celery.
        broadcast = Broadcast._base_manager.select_related('organization').get(pk=broadcast_id)
    except Broadcast.DoesNotExist:
        logger.error('Broadcast %s not found', broadcast_id)
        return

    org = broadcast.organization

    with org_context(org):
        _send_broadcast_inner(broadcast, org)


def _send_broadcast_inner(broadcast, org):
    from django.utils import timezone
    from datetime import timedelta
    from .models import Broadcast, BroadcastRecipient, TelegramChat, TelegramMessage
    from .views import _send_tg, _esc

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
    # Explicit cooldown count — клемпимо в 0+ щоб уникнути від'ємних чисел при retry.
    total_chats = len(chats)
    cooled_out = total_chats - len(to_send) - len(already_sent_ids)
    skipped = max(0, cooled_out)

    # broadcast.total встановлюємо ЛИШЕ першого разу (retry не повинен скидати лічильник).
    update_fields = ['status']
    if broadcast.status != Broadcast.Status.SENDING:
        broadcast.status = Broadcast.Status.SENDING
    if broadcast.total == 0:
        broadcast.total = len(to_send)
        broadcast.sent = 0
        broadcast.failed = 0
        update_fields += ['total', 'sent', 'failed']
    broadcast.save(update_fields=update_fields)

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

    sent = broadcast.sent or 0
    failed = broadcast.failed or 0

    for chat in to_send:
        # Atomic dedup: створюємо pending запис ДО send, щоб паралельний retry побачив
        # status='sent' і skip-нув. Гарантує рівно 1 send per (broadcast, chat).
        recipient, recipient_created = BroadcastRecipient.objects.get_or_create(
            broadcast=broadcast,
            chat=chat,
            defaults={'status': BroadcastRecipient.Status.SENT},  # буде переписано після TG
        )
        if not recipient_created and recipient.status == BroadcastRecipient.Status.SENT:
            # Інший воркер уже відправив — skip.
            continue

        status = BroadcastRecipient.Status.SENT
        tg_msg_id = None
        try:
            result = _send_tg(chat.tg_user_id, _esc(broadcast.text), org=org)
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

        recipient.status = status
        recipient.save(update_fields=['status'])

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


@shared_task
def deliver_night_messages():
    """Ранок після неробочого часу (Олег 19.11.2026): персоналу — по сповіщенню на кожен чат, що писав уночі, з кнопкою
    «Швидка відповідь», як удень. Чат, де вже відповіла людина з персоналу, пропускаємо. Раз на ніч — quiet_sent_on."""
    from django.utils import timezone
    from apps.clinic.models import Organization
    from . import quiet
    from .models import TelegramMessage
    from .views import MENU_BUTTONS
    today = timezone.localdate()
    for org in Organization.objects.filter(quiet_from__isnull=False, quiet_until__isnull=False):
        if quiet.is_quiet(org) or org.quiet_sent_on == today:
            continue
        start, end = quiet.last_window(org)
        msgs = (TelegramMessage._base_manager
                .filter(chat__organization=org, chat__is_staff=False, direction=TelegramMessage.Direction.IN,
                        created_at__gte=start, created_at__lt=end)
                .order_by('created_at').values('chat_id', 'text', 'media_type', 'created_at'))
        per_chat = {}
        for m in msgs:
            t = (m['text'] or '').strip()
            if not m['media_type'] and (not t or t in MENU_BUTTONS or t.startswith('/')):
                continue
            n = per_chat.get(m['chat_id'], (0,))[0]
            per_chat[m['chat_id']] = (n + 1, t or '[медіа]', m['created_at'])
        sent = 0
        for chat_id, (n, last_text, last_at) in per_chat.items():
            if TelegramMessage._base_manager.filter(chat_id=chat_id, direction=TelegramMessage.Direction.OUT,
                                                    sent_by__isnull=False, created_at__gt=last_at).exists():
                continue   # уночі вже відповіла людина з персоналу
            when = timezone.localtime(last_at).strftime('%H:%M')
            more = f'{n} повідомл., останнє о {when}' if n > 1 else f'о {when}'
            notify_staff_new_message_task.delay(chat_id, f'🌙 Писали вночі ({more}):\n{last_text}')
            sent += 1
        Organization.objects.filter(pk=org.pk).update(quiet_sent_on=today)
        logger.info('deliver_night_messages org=%s: %s чатів', org.pk, sent)
