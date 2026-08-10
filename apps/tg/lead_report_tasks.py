"""Звіт по лідах двічі на день (наказ власника 09.08.2026).

Показує, що автодіалог наробив за зміну: скільки незнайомців написало,
скільки з них записалось само, скільки чекає людини і — головне — хто
завис без відповіді. Останнє і є сенсом звіту: у липні клієнт із «болить
палець» писав двічі й не отримав жодної відповіді, бо ніхто не дивився
у чат.

Розклад — `CELERY_BEAT_SCHEDULE` у config/settings/base.py: 12:00 і 19:00
за Києвом (CELERY_TIMEZONE='Europe/Kyiv').
"""

import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)

# Скільки годин вважати «зміною» — вікно звіту.
_WINDOW_HOURS = 12
# Скільки хвилин без відповіді вже вважається «завис».
_STALE_MINUTES = 60


def _fmt_chat(chat) -> str:
    """Ім'я + @username для рядка звіту."""
    from apps.tg.views import _esc
    name = _esc(chat.display_name or 'без імені')
    if chat.tg_username:
        return f'{name} (@{_esc(chat.tg_username)})'
    return name


def _build_report(org, since) -> str:
    """Текст звіту для однієї організації. Порожній рядок — якщо нічого не сталось."""
    from apps.tg.models import TelegramChat, TelegramMessage
    from apps.appointments.models import Appointment, LeadRequest
    from apps.clinic.tenant import org_context
    from apps.tg import autodialog

    with org_context(org):
        chats = list(
            TelegramChat.objects.filter(
                organization=org,
                is_staff=False,
                last_message_at__gte=since,
            )
        )
        leads = list(LeadRequest.objects.filter(organization=org, created_at__gte=since))
        booked = list(
            Appointment.objects.filter(organization=org, created_at__gte=since)
            .select_related('client', 'patient')
        )

        newcomers = [c for c in chats if c.client is None]

        # Завислі: останнє повідомлення — вхідне, і воно старше за _STALE_MINUTES.
        stale = []
        cutoff = timezone.now() - timedelta(minutes=_STALE_MINUTES)
        for chat in chats:
            last = (
                TelegramMessage.objects.filter(chat=chat)
                .order_by('-id')
                .values('direction', 'created_at', 'text')
                .first()
            )
            if not last:
                continue
            if last['direction'] == 'in' and last['created_at'] < cutoff:
                waited = int((timezone.now() - last['created_at']).total_seconds() // 60)
                stale.append((chat, waited, (last['text'] or '[медіа]')[:60]))

    if not (newcomers or leads or booked or stale):
        return ''

    declined = [c for c in newcomers if autodialog.get_stage(c) == autodialog.STAGE_DECLINED]
    offered = [c for c in newcomers if autodialog.get_stage(c) == autodialog.STAGE_OFFERED]

    lines = [f'📊 <b>Звіт по зверненнях — {org.name}</b>']
    lines.append(f'<i>за останні {_WINDOW_HOURS} год</i>\n')

    lines.append(f'👥 Незнайомців написало: <b>{len(newcomers)}</b>')
    if offered:
        lines.append(f'   ⏳ запропоновано запис, думають: {len(offered)}')
    if declined:
        lines.append(f'   🙋 чекають адміністратора: {len(declined)}')
    lines.append(f'📅 Записів створено: <b>{len(booked)}</b>')
    lines.append(f'📝 Заявок (сайт + бот): <b>{len(leads)}</b>')

    if stale:
        lines.append(f'\n🔴 <b>Без відповіді ({len(stale)}):</b>')
        for chat, waited, preview in sorted(stale, key=lambda x: -x[1])[:10]:
            from apps.tg.views import _esc
            hours = waited // 60
            waited_str = f'{hours} год' if hours else f'{waited} хв'
            lines.append(f'   • {_fmt_chat(chat)} — {waited_str}: «{_esc(preview)}»')

    if booked:
        lines.append('\n✅ <b>Записались:</b>')
        for appt in booked[:10]:
            who = str(appt.client) if appt.client else '?'
            pet = f' / {appt.patient.name}' if appt.patient else ''
            lines.append(f'   • {who}{pet} — {appt.starts_at:%d.%m %H:%M}')

    return '\n'.join(lines)


@shared_task(name='apps.tg.lead_report_tasks.send_lead_report')
def send_lead_report():
    """Розсилає звіт по кожній організації тим, хто підписаний на заявки."""
    from apps.clinic.models import Organization
    from apps.tg.models import TelegramChat
    from apps.tg.views import _send_tg, _get_token
    from apps.clinic.tenant import org_context

    since = timezone.now() - timedelta(hours=_WINDOW_HOURS)
    sent = 0

    for org in Organization.objects.filter(is_active=True):
        try:
            if not _get_token(org):
                continue

            text = _build_report(org, since)
            if not text:
                continue

            # TelegramChat — org-scoped fail-closed менеджер: без org_context
            # вибірка порожня і звіт нікуди не піде.
            with org_context(org):
                receivers = list(
                    TelegramChat.objects.filter(organization=org, receive_leads=True)
                )

            notified = set()
            for chat in receivers:
                if chat.tg_user_id in notified:
                    continue
                _send_tg(chat.tg_user_id, text, org=org)
                notified.add(chat.tg_user_id)
                sent += 1

        except Exception:
            logger.exception('lead report failed for org=%s', getattr(org, 'slug', '?'))

    return f'lead report sent to {sent} chats'
