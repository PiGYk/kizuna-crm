"""Сповіщення про події оплати підписки в Telegram.

Навіщо: сторінки історії платежів у CRM немає, таблиця транзакцій нікому не
показується. Поки її нема — власник має дізнаватись про гроші одразу в телефон.

Три події:
  paid      — оплата пройшла;
  failed    — платіжна система відмовила (є причина);
  abandoned — людина натиснула «оплатити» і не дійшла (див. tasks.py).

Кому слати — `PAYMENT_ALERT_CHAT_IDS` у .env (через кому). Токен —
`PAYMENT_ALERT_BOT_TOKEN`. Порожньо → мовчимо, помилки не піднімаємо:
сповіщення НЕ МОЖЕ ламати обробку платежу.
"""
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

_API = 'https://api.telegram.org/bot{token}/sendMessage'
_TIMEOUT = 8


def _recipients():
    raw = getattr(settings, 'PAYMENT_ALERT_CHAT_IDS', '') or ''
    return [c.strip() for c in raw.split(',') if c.strip()]


def _send(text: str) -> None:
    token = getattr(settings, 'PAYMENT_ALERT_BOT_TOKEN', '') or ''
    chats = _recipients()
    if not token or not chats:
        logger.info('payment alert skipped: token/chats not configured')
        return
    for chat_id in chats:
        try:
            resp = requests.post(
                _API.format(token=token),
                json={'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML',
                      'disable_web_page_preview': True},
                timeout=_TIMEOUT,
            )
            if not resp.ok:
                logger.warning('payment alert to %s failed: %s %s',
                               chat_id, resp.status_code, resp.text[:200])
        except Exception as exc:                      # noqa: BLE001
            # Сповіщення не має права зламати обробку платежу.
            logger.warning('payment alert to %s raised: %s', chat_id, exc)


def _org_line(org) -> str:
    if org is None:
        return 'клініка невідома'
    return f'{org.name} (id {org.pk})'


def notify_paid(org, plan_label: str, amount, order_ref: str) -> None:
    _send(
        '💰 <b>ОПЛАТА ПРОЙШЛА</b>\n'
        f'Клініка: {_org_line(org)}\n'
        f'Тариф: {plan_label}\n'
        f'Сума: {amount} грн\n'
        f'Замовлення: <code>{order_ref}</code>'
    )


def notify_failed(org, plan_label: str, amount, order_ref: str,
                  status: str, reason: str) -> None:
    _send(
        '❌ <b>ОПЛАТА НЕ ПРОЙШЛА</b>\n'
        f'Клініка: {_org_line(org)}\n'
        f'Тариф: {plan_label}\n'
        f'Сума: {amount} грн\n'
        f'Статус: {status}\n'
        f'Причина: {reason or "не вказана"}\n'
        f'Замовлення: <code>{order_ref}</code>'
    )


def notify_abandoned(org, plan_label: str, amount, order_ref: str,
                     minutes: int) -> None:
    _send(
        '⚠️ <b>ОБІРВАЛИСЬ НА ОПЛАТІ</b>\n'
        f'Клініка: {_org_line(org)}\n'
        f'Тариф: {plan_label}\n'
        f'Сума: {amount} грн\n'
        f'Натиснули «оплатити» {minutes} хв тому і не завершили.\n'
        f'Замовлення: <code>{order_ref}</code>\n'
        'Схоже, варто передзвонити.'
    )
