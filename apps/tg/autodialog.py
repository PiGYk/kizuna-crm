"""Автодіалог з незареєстрованими клієнтами в Telegram.

Задача (наказ власника 09.08.2026): людина, якої немає в базі, пише боту —
бот САМ веде розмову, збирає дані і записує на вільний слот, не чекаючи
адміністратора. До цього незнайомець отримував лише «адміністратор
відповість» і далі тиша: у липні так загубився клієнт із «болить палець»,
який писав двічі й не дочекався відповіді жодного разу.

Архітектура — два шари:

1. ДЕТЕРМІНОВАНИЙ (працює завжди, без зовнішніх сервісів). М'яка пропозиція
   записатись → наявна анкета онбордингу → наявний booking flow. Нічого
   нового не винаходить: перевикористовує `_onboarding_begin` і
   `_cmd_book_appointment` з views.py.

2. РОЗУМНИЙ (LLM, вмикається `TG_AUTODIALOG_LLM=1` + ключ). Читає вільний
   текст людини, витягує кличку/вид/причину звернення і відповідає живою
   мовою замість шаблону. Якщо шар вимкнений або впав — тихо відкочується
   на детермінований, клієнт різниці не помічає.

Стан автодіалогу живе в окремому полі `TelegramChat.autodialog_state`, а НЕ
в `onboarding_state`: останній перезаписується цілком у `_onboarding_set_step`
(`{'step': ..., 'data': ...}`), тож будь-який чужий ключ там загинув би
на першому ж кроці анкети.
"""

import json
import logging

from django.conf import settings

logger = logging.getLogger(__name__)

# Стадії автодіалогу (значення `autodialog_state['stage']`).
STAGE_OFFERED = 'offered'    # запропонували запис, чекаємо реакції
STAGE_DECLINED = 'declined'  # людина обрала дочекатись адміністратора
STAGE_BOOKING = 'booking'    # веде анкету/вибір часу
STAGE_DONE = 'done'          # записалась

# Скільки символів вхідного тексту віддаємо моделі — захист від простирадла.
_MAX_INPUT_CHARS = 1500


# ── Стан ──────────────────────────────────────────────────────────────────────

def get_stage(chat) -> str:
    return (chat.autodialog_state or {}).get('stage') or ''


def set_stage(chat, stage, data_update=None):
    state = dict(chat.autodialog_state or {})
    data = dict(state.get('data') or {})
    if data_update:
        data.update(data_update)
    chat.autodialog_state = {'stage': stage, 'data': data}
    chat.save(update_fields=['autodialog_state'])


# ── LLM-шар (опційний) ────────────────────────────────────────────────────────

def _llm_enabled() -> bool:
    return bool(
        getattr(settings, 'TG_AUTODIALOG_LLM', False)
        and getattr(settings, 'ANTHROPIC_API_KEY', '')
    )


def _llm_understand(text: str, org_name: str) -> dict:
    """Витягує з вільного тексту суть звернення.

    Повертає dict: {greeting, pet_name, species, reason, urgent}. Будь-яка
    помилка (немає ключа, таймаут, кривий JSON) → порожній dict, і виклик
    вище йде детермінованою гілкою. Мовчазних винятків назовні не пускаємо:
    автодіалог не має права зронити webhook.
    """
    if not _llm_enabled():
        return {}

    import requests

    prompt = (
        f'Ти — помічник ветеринарної клініки "{org_name}". Клієнт написав у Telegram.\n'
        f'Повідомлення: "{text[:_MAX_INPUT_CHARS]}"\n\n'
        'Витягни з нього дані і поверни ЛИШЕ JSON без пояснень:\n'
        '{"greeting": "одне тепле речення-відповідь українською на те, що людина '
        'написала, без обіцянок діагнозу і без порад щодо лікування", '
        '"pet_name": "кличка або порожньо", '
        '"species": "dog|cat|rabbit|bird|hamster|ferret|turtle|other або порожньо", '
        '"reason": "коротко причина звернення", '
        '"urgent": true/false}\n'
        'Якщо у тексті ознаки невідкладного стану (кровотеча, судоми, отруєння, '
        'травма, не дихає, здувся живіт) — urgent=true.'
    )

    try:
        resp = requests.post(
            'https://api.anthropic.com/v1/messages',
            headers={
                'x-api-key': settings.ANTHROPIC_API_KEY,
                'anthropic-version': '2023-06-01',
                'content-type': 'application/json',
            },
            json={
                'model': getattr(settings, 'TG_AUTODIALOG_MODEL', 'claude-haiku-4-5'),
                'max_tokens': 400,
                'messages': [{'role': 'user', 'content': prompt}],
            },
            timeout=12,
        )
        if resp.status_code != 200:
            logger.warning('autodialog LLM HTTP %s: %s', resp.status_code, resp.text[:200])
            return {}
        raw = resp.json()['content'][0]['text'].strip()
        # Модель іноді загортає JSON у ```json ... ``` — зрізаємо.
        if raw.startswith('```'):
            raw = raw.split('```')[1]
            if raw.startswith('json'):
                raw = raw[4:]
        return json.loads(raw)
    except Exception:
        logger.exception('autodialog LLM failed')
        return {}


# ── Чи вмикатись ──────────────────────────────────────────────────────────────

def should_engage(chat, text: str) -> bool:
    """True, якщо на це повідомлення варто відповісти автодіалогом.

    Не чіпаємо: своїх (verified), персонал, тих, хто вже у анкеті онбордингу,
    тих, кому вже пропонували, і тих, хто відмовився. Команди й кнопки меню
    сюди не доходять — їх розбирає `_handle_command` вище.
    """
    if chat.client is not None or chat.is_staff:
        return False
    if (chat.onboarding_state or {}).get('step'):
        return False
    if get_stage(chat):
        return False
    return bool((text or '').strip())


# ── Головний вхід ─────────────────────────────────────────────────────────────

def engage(chat, text: str):
    """Перша реакція на звернення незнайомця. Повертає (reply, markup) або None."""
    from .views import _inline_keyboard, _esc

    org_name = chat.organization.name if chat.organization else 'нашій клініці'
    understood = _llm_understand(text, org_name)

    greeting = (understood.get('greeting') or '').strip()
    if not greeting:
        greeting = (
            'Дякую за звернення! Я помічник клініки і можу записати вас '
            'на прийом просто зараз.'
        )

    lines = [_esc(greeting)]

    if understood.get('urgent'):
        lines.append(
            '\n⚠️ <b>Якщо стан гострий — не чекайте запису, телефонуйте '
            'у клініку негайно.</b>'
        )

    lines.append(
        '\nЗаписати вас на прийом? Це швидше, ніж чекати адміністратора — '
        'я покажу вільний час і одразу оформлю запис. 🐾'
    )

    markup = _inline_keyboard([
        ('📅 Так, записати', 'ad_book'),
        ('Дочекаюсь адміністратора', 'ad_wait'),
    ])

    set_stage(chat, STAGE_OFFERED, {
        'reason': (understood.get('reason') or text or '')[:255],
        'pet_name': understood.get('pet_name') or '',
        'species': understood.get('species') or '',
        'urgent': bool(understood.get('urgent')),
        'llm': bool(understood),
    })

    return '\n'.join(lines), markup


def handle_callback(chat, action: str):
    """Обробляє натискання кнопок автодіалогу. Повертає (reply, markup) або None."""
    from .views import _onboarding_begin, _remove_keyboard

    if action == 'ad_book':
        set_stage(chat, STAGE_BOOKING)
        return _onboarding_begin(chat)

    if action == 'ad_wait':
        set_stage(chat, STAGE_DECLINED)
        return (
            'Добре, передав адміністратору — він відповість вам тут у чаті. 🐾\n\n'
            'Якщо передумаєте — просто напишіть «записатись», і я оформлю запис.',
            _remove_keyboard(),
        )

    return None


def wants_booking(text: str) -> bool:
    """Людина сама просить запис словами — тоді пропозицію повторюємо навіть
    після відмови (інакше «передумав» не спрацює)."""
    low = (text or '').lower()
    return any(w in low for w in ('записат', 'записа', 'на прийом', 'запис'))
