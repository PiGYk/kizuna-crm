"""Автозапис клієнта в Telegram — розмову веде модель, кнопок немає.

Наказ власника 10.09.2026, дослівно: «воно має записувати автоматично, без
участі взагалі людей. Якщо пишуть питання з приводу запису — не треба ніяких
кнопок, не треба навіть казати, що це бот. Це просто так пише адміністратор,
і адміністратор записує».

Що було до цього і чому переписано (розбір чату 652, 10.09):
людина написала «потрібна друга вакцинація від сказу котику», отримала
шаблон «Дякую за звернення! Я помічник клініки…» з двома кнопками і за 7
секунд натиснула «Дочекаюсь адміністратора». Далі — тиша: живого сигналу
персоналу немає, звіт по зверненнях лише о 12:00 і 19:00. Шаблон вона
отримала тому, що розумний шар був вимкнений (`ANTHROPIC_API_KEY` порожній,
ключ клініки лежав під іншим ім'ям) — за весь час жоден із 65 чатів не мав
`llm: true`. Кнопка «дочекаюсь адміністратора» була рівноправним виходом і
її обрали 27 людей.

Тепер:
- жодних кнопок і жодного «я помічник/бот» — пише адміністратор клініки;
- модель веде вільну розмову, сама збирає ім'я, телефон, кличку, вид і час;
- щойно даних вистачає — код САМ створює клієнта, пацієнта і запис у той же
  слот-механізм, що й сайт (`_free_slots`/`_slot_is_free`), без участі людей;
- модель недоступна або розмова зайшла в глухий кут → тихо кличемо персонал
  живим сигналом, а не мовчимо до вечірнього звіту.

Стан живе в `TelegramChat.autodialog_state`, а НЕ в `onboarding_state`:
останній перезаписується цілком у `_onboarding_set_step`.
"""

import json
import logging
import os
import re
from datetime import date as date_type, datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.appointments.day_rules import (
    doctor_on as _doctor_on, doctors_week_text as _doctors_week_text,
    exotic_days as _exotic_days, is_exotic as _is_exotic, surgery_days as _surgery_days,
    surgery_latest as _surgery_latest, surgery_time_ok as _surgery_time_ok,
    SURGERY_STAFF_SHORT as _SURGERY_STAFF_SHORT, SURGERY_STAFF_WARNING as _SURGERY_STAFF_WARNING,
)

logger = logging.getLogger(__name__)

# Стадії (`autodialog_state['stage']`).
STAGE_TALKING = 'talking'  # розмова триває, ведемо до запису
STAGE_DONE = 'done'        # запис створено
STAGE_HUMAN = 'human'      # передано персоналу, модель мовчить

# Старі стадії — лишаються, щоб чати, які застали попередню версію, не падали.
STAGE_OFFERED = 'offered'
STAGE_DECLINED = 'declined'
STAGE_BOOKING = 'booking'
_LEGACY_STAGES = (STAGE_OFFERED, STAGE_DECLINED, STAGE_BOOKING)

_MAX_INPUT_CHARS = 1500   # захист від простирадла
_MAX_TURNS = 40           # стеля витрат на один чат
_HISTORY_MESSAGES = 24    # скільки повідомлень віддаємо моделі як контекст
_SLOT_DAYS = 7            # на скільки робочих днів показуємо вільний час
_SAME_DAY_BUFFER_MIN = 60  # запас на дорогу, щоб не пропонувати запис «через 10 хвилин»
_API_URL = 'https://api.anthropic.com/v1/messages'

_WEEKDAYS = ['понеділок', 'вівторок', 'середа', 'четвер', 'п\'ятниця', 'субота', 'неділя']

_SPECIES_ALIASES = {
    'собака': 'dog', 'пес': 'dog', 'песик': 'dog', 'цуценя': 'dog', 'dog': 'dog',
    'кіт': 'cat', 'кит': 'cat', 'кішка': 'cat', 'кошка': 'cat', 'котик': 'cat',
    'кошеня': 'cat', 'cat': 'cat',
    'кролик': 'rabbit', 'rabbit': 'rabbit',
    'птах': 'bird', 'папуга': 'bird', 'bird': 'bird',
    'хом\'як': 'hamster', 'хомяк': 'hamster', 'hamster': 'hamster',
    'морська свинка': 'guinea_pig', 'guinea_pig': 'guinea_pig',
    'тхір': 'ferret', 'ferret': 'ferret',
    'шиншила': 'chinchilla', 'chinchilla': 'chinchilla',
    'щур': 'rat', 'миша': 'rat', 'rat': 'rat',
    'черепаха': 'turtle', 'turtle': 'turtle',
    'ящірка': 'reptile', 'змія': 'reptile', 'reptile': 'reptile',
    'риба': 'fish', 'fish': 'fish',
    'їжак': 'hedgehog', 'hedgehog': 'hedgehog',
    'собачка': 'dog', 'кицька': 'cat', 'папужка': 'bird',
}

# Екзотів (усе, крім собак і котів) приймає окремий лікар і лише у свої дні —
# правило спільне з формою на сайті: apps/appointments/day_rules.py (там же операції й лікарі).

# Ціни бот НЕ називає (наказ Каті 12.10.2026: бот писав «аналізи коштують
# 300 гривень», а вартість щоразу різна — її пишуть люди). Прайс із промпту
# прибрано; це запобіжник на випадок, якщо модель таки напише суму з голови.
_PRICE_RE = re.compile(r'\d[\d\s.,]*\s*(?:грн|гривн|₴|uah)', re.IGNORECASE)


# ── Стан ──────────────────────────────────────────────────────────────────────

def get_stage(chat) -> str:
    return (chat.autodialog_state or {}).get('stage') or ''


def get_data(chat) -> dict:
    return dict((chat.autodialog_state or {}).get('data') or {})


def set_stage(chat, stage, data_update=None):
    state = dict(chat.autodialog_state or {})
    data = dict(state.get('data') or {})
    if data_update:
        data.update(data_update)
    chat.autodialog_state = {'stage': stage, 'data': data}
    chat.save(update_fields=['autodialog_state'])


# ── Доступ до моделі ──────────────────────────────────────────────────────────

def _api_key() -> str:
    """Ключ шукаємо під обома іменами.

    `KIZUNA_CHAT_API_KEY` уже лежить у клініки з 19.08 (помічник Довідки), а
    автодіалог до 10.09 дивився тільки на `ANTHROPIC_API_KEY` — і мовчки
    відкочувався на шаблон. Саме на цьому місці все й зламалось.
    """
    return (
        os.getenv('KIZUNA_CHAT_API_KEY', '').strip()
        or (getattr(settings, 'ANTHROPIC_API_KEY', '') or '').strip()
    )


def _llm_enabled() -> bool:
    return bool(getattr(settings, 'TG_AUTODIALOG_LLM', True) and _api_key())


# ── Вільний час ───────────────────────────────────────────────────────────────

def _slots_map(org, days=_SLOT_DAYS) -> dict:
    """{'2026-09-11': ['10:00', '10:30', ...]} на найближчі робочі дні, ВКЛЮЧНО З СЬОГОДНІ.

    Народжено збоєм 27.09.2026: цикл робив `day += 1` ДО першої перевірки, тому
    сьогоднішній день у переліку не з'являвся НІКОЛИ. Модель бачила список, що
    починається з завтра, і сама вигадувала причину — «сьогодні неділя, ми не
    працюємо» (клініка працює щодня). Той самий день, побачений із суботи,
    спокійно пропонувався як «завтра» — тобто справа була не в графіку.

    Минулі години сьогоднішнього дня відрізаємо з буфером: пропонувати 10:00,
    коли вже 15:00, гірше за відсутність слота.
    """
    from apps.appointments.public_api import _free_slots

    out = {}
    today = timezone.localdate()
    cutoff = (timezone.localtime() + timedelta(minutes=_SAME_DAY_BUFFER_MIN)).strftime('%H:%M')
    day = today
    looked = 0
    while len(out) < days and looked < 21:
        looked += 1
        try:
            free = _free_slots(org, day)
        except Exception:
            logger.exception('autodialog: _free_slots failed for %s', day)
            break
        if free:
            if day == today:
                free = [t for t in free if t >= cutoff]
            if free:
                out[day.isoformat()] = list(free)
        day += timedelta(days=1)
    return out


def _slots_text(slots: dict, org=None) -> str:
    if not slots:
        return '(вільних місць на найближчі дні немає)'
    ex = _exotic_days(org) if org else None
    su = _surgery_days(org) if org else None
    lines = []
    for iso, times in slots.items():
        d = date_type.fromisoformat(iso)
        shown = ', '.join(times[:16])
        if len(times) > 16:
            shown += ' …'
        notes = []
        doc = _doctor_on(org, d) if org else ''
        if doc:
            notes.append(f'лікар {doc}')
        if ex:
            notes.append('екзоти — так' if d.weekday() in ex else 'екзоти — НІ')
        if su:
            if d.weekday() in su:
                latest = _surgery_latest(org)
                notes.append(f'операції — так, ЛИШЕ з початком до {latest} включно' if latest
                             else 'операції — так')
            else:
                notes.append('операції — НІ')
        mark = f' [{"; ".join(notes)}]' if notes else ''
        lines.append(f'{iso} ({_WEEKDAYS[d.weekday()]} {d.strftime("%d.%m")}){mark}: {shown}')
    return '\n'.join(lines)


def _services_text(org) -> str:
    """Перелік послуг клініки для промпту, згрупований по категоріях, БЕЗ ЦІН.

    Ціни прибрано 12.10.2026 (наказ Каті): модель називала суми з прайсу
    («аналізи 300 грн»), а реальна вартість залежить від випадку.

    Наказ Олега 10.09: «хайку має розуміти нашу клініку, знати які послуги ми
    надаємо. До прикладу ехо серця ми не робимо». Без цього переліку модель
    охоче обіцяла те, чого в клініці немає, і людина приходила б даремно.
    Кеш на 10 хвилин: прайс міняється рідко, а запит іде на кожну репліку.
    """
    from django.core.cache import cache
    from apps.services.models import Service

    # ⚡Ключ змінено разом із форматом: старий текст із цінами живе в Redis ще 10 хв.
    key = f'autodialog:services-noprice:{getattr(org, "pk", 0)}'
    cached = cache.get(key)
    if cached is not None:
        return cached

    rows = (
        Service.objects.filter(organization=org, is_active=True)
        .select_related('category')
        .order_by('category__name', 'name')
    )
    groups = {}
    for s in rows:
        cat = (s.category.name if s.category else 'Інше')
        groups.setdefault(cat, []).append(s.name)

    text = '\n'.join(f'{cat}: ' + '; '.join(items) for cat, items in groups.items())
    cache.set(key, text, 600)
    return text


# ── Нормалізація того, що повернула модель ────────────────────────────────────

def _norm_phone(raw: str) -> str:
    digits = re.sub(r'\D', '', str(raw or ''))
    if not digits:
        return ''
    if digits.startswith('380') and len(digits) == 12:
        return '+' + digits
    if digits.startswith('0') and len(digits) == 10:
        return '+38' + digits
    if len(digits) == 9:
        return '+380' + digits
    return '+' + digits if len(digits) >= 10 else ''


def _norm_species(raw: str) -> str:
    from apps.clients.models import Patient

    val = str(raw or '').strip().lower()
    if not val:
        return ''
    valid = {c for c, _ in Patient.Species.choices}
    if val in valid:
        return val
    return _SPECIES_ALIASES.get(val, '')


def _norm_time(raw: str) -> str:
    m = re.search(r'(\d{1,2})[:.](\d{2})', str(raw or ''))
    if not m:
        return ''
    return f'{int(m.group(1)):02d}:{m.group(2)}'


def _norm_date(raw: str) -> str:
    val = str(raw or '').strip()
    try:
        return date_type.fromisoformat(val[:10]).isoformat()
    except ValueError:
        return ''


# ── Розмова ───────────────────────────────────────────────────────────────────

def _history(chat, limit=_HISTORY_MESSAGES) -> list:
    """Останні репліки у форматі Anthropic, з чергуванням ролей."""
    from .models import TelegramMessage

    rows = list(
        TelegramMessage.objects.filter(chat=chat).order_by('-id')[:limit]
    )
    rows.reverse()

    msgs = []
    for m in rows:
        text = (m.text or '').strip()
        if not text:
            continue
        role = 'user' if m.direction == TelegramMessage.Direction.IN else 'assistant'
        # Anthropic вимагає чергування — сусідні репліки однієї ролі склеюємо.
        if msgs and msgs[-1]['role'] == role:
            msgs[-1]['content'] += '\n' + text[:_MAX_INPUT_CHARS]
        else:
            msgs.append({'role': role, 'content': text[:_MAX_INPUT_CHARS]})
    # Перше повідомлення мусить бути від людини.
    while msgs and msgs[0]['role'] != 'user':
        msgs.pop(0)
    return msgs


def _work_days_line(org) -> str:
    """Рядок «Клініка працює: …» з РЕАЛЬНИХ налаштувань клініки.

    Без нього модель добудовувала графік зі власних уявлень і оголошувала
    неділю вихідним (збій 27.09.2026). CRM багатотенантна: у когось справді
    Пн-Пт, тому джерело — `organization.work_days`, а не константа.
    """
    days = list(org.work_days) if (org and org.work_days) else []
    if not days:
        return ''
    days = sorted(d for d in days if isinstance(d, int) and 0 <= d <= 6)
    if not days:
        return ''
    work = ', '.join(_WEEKDAYS[d] for d in days)
    off = [_WEEKDAYS[d] for d in range(7) if d not in days]
    if off:
        return 'Клініка працює: %s. Вихідні: %s.' % (work, ', '.join(off))
    return 'Клініка працює ЩОДНЯ, без вихідних (%s).' % work


def _is_surgery(collected: dict) -> bool:
    return str(collected.get('surgery') or '').strip().lower() in ('yes', 'true', '1', 'так')


def _exotic_line(org) -> str:
    """Правила днів: екзоти, операції, лікарі за днями (з apps/appointments/day_rules.py)."""
    parts = []
    days = _exotic_days(org)
    if days:
        names = ', '.join(_WEEKDAYS[d] for d in days)
        parts.append(
            'ЕКЗОТИЧНИХ тварин (усіх, крім собак і котів: кроликів, гризунів, птахів, '
            'черепах, рептилій, тхорів, їжаків, риб) приймає окремий лікар ЛИШЕ в такі дні: '
            f'{names}. Екзота записуй ТІЛЬКИ на ці дні; в інші дні лікаря по екзотах '
            'немає — так і скажи і запропонуй найближчий із цих днів. Собак і котів '
            'записуй на будь-який день із переліку.'
        )
    sdays = _surgery_days(org)
    if sdays:
        names = ', '.join(_WEEKDAYS[d] for d in sdays)
        parts.append(
            'ОПЕРАЦІЇ (стерилізація, кастрація, видалення новоутворень, ЧИСТКА ЗУБІВ, '
            'ВИДАЛЕННЯ ЗУБІВ, будь-яке хірургічне втручання чи процедура під наркозом) '
            'проводимо ЛИШЕ в такі дні: '
            f'{names}. Людина записується на операцію — постав у collected surgery="yes" '
            'і пропонуй ТІЛЬКИ ці дні. Огляд, вакцинація, УЗД, аналізи — будь-який день.'
            + (f' Час початку операції — НЕ пізніше {_surgery_latest(org)}: {_surgery_latest(org)} — '
               'останній можливий; будь-який пізніший час (навіть на 30 хвилин пізніше) на '
               'операцію НЕ пропонуй і НЕ називай.' if _surgery_latest(org) else '')
        )
    week = _doctors_week_text(org)
    if week:
        parts.append(f'Лікарі за днями (постійний графік): {week}.')
    return '\n'.join(parts)


def _strip_prices(reply: str):
    """Вирізає з відповіді речення із сумами в гривнях. Повертає (текст, чи_вирізали)."""
    if not reply or not _PRICE_RE.search(reply):
        return reply, False
    parts = re.split(r'(?<=[.!?…])\s+', reply)
    kept = [p for p in parts if not _PRICE_RE.search(p)]
    text = ' '.join(kept).strip()
    note = 'Точну вартість підкажемо окремо — вона залежить від конкретного випадку.'
    return ((text + ' ' + note).strip() if text else note), True


def _system_prompt(chat, slots: dict, collected: dict) -> str:
    # ⚡Час беремо з поясу клініки: контейнер живе в UTC, тому `date.today()`
    # з 21:00 до півночі по Києву віддавав ВЧОРАШНЮ дату (збій 27.09.2026).
    now = timezone.localtime()
    today = timezone.localdate()
    org = chat.organization
    org_name = org.name if org else 'ветеринарна клініка'
    hours = (getattr(org, 'work_hours', '') or '').strip() or 'уточнюйте у клініці'
    days_line = _work_days_line(org)
    phone = (getattr(org, 'phone', '') or '').strip()
    address = (getattr(org, 'address', '') or '').strip()

    exotic_days = _exotic_days(org)
    surgery_days = _surgery_days(org)
    exotic_line = _exotic_line(org)
    if exotic_days and _is_exotic(_norm_species(collected.get('species'))):
        # Вже відомо, що тварина екзотична — інших днів моделі просто не показуємо.
        slots = {iso: t for iso, t in slots.items()
                 if date_type.fromisoformat(iso).weekday() in exotic_days}
    if surgery_days and _is_surgery(collected):
        # Те саме для операції.
        slots = {iso: t for iso, t in slots.items()
                 if date_type.fromisoformat(iso).weekday() in surgery_days}
    if _is_surgery(collected) and _surgery_latest(org):
        # І лише час до останнього дозволеного початку операції.
        slots = {iso: [x for x in t if _surgery_time_ok(org, x)] for iso, t in slots.items()}
        slots = {iso: t for iso, t in slots.items() if t}

    known = {k: v for k, v in collected.items() if v and k in (
        'first_name', 'last_name', 'phone', 'pet_name', 'species', 'date', 'time', 'reason',
        'surgery',
    )}

    return (
        f'Ти — адміністратор ветеринарної клініки "{org_name}". Листуєшся з клієнтом '
        f'у Telegram і сама оформлюєш запис на прийом.\n'
        f'Сьогодні {today.strftime("%d.%m.%Y")}, {_WEEKDAYS[today.weekday()]}, '
        f'зараз {now.strftime("%H:%M")}. '
        f'«Завтра» — це {(today + timedelta(days=1)).strftime("%d.%m")}.\n\n'
        'ЯК ПИСАТИ:\n'
        '- Українською, коротко: 1-3 речення. Живо і по-людськи, як адміністратор, '
        'а не як довідка.\n'
        '- ЗАВЖДИ на «ви», навіть якщо клієнт тикає. Вітання — «Добрий день», не «привіт».\n'
        '- Чиста українська, без русизмів: «дякую» (не «спасибі»), «будь ласка», '
        '«гаразд», «зателефонуйте».\n'
        '- НІКОЛИ не кажи, що ти бот, помічник, програма чи штучний інтелект. '
        'Не пропонуй "дочекатись адміністратора" — адміністратор це ти.\n'
        '- Питай по одному-два питання за раз, не анкетою.\n'
        '- Діагнозів не став і лікування не призначай: "лікар подивиться на прийомі".\n'
        '- ⛔ ЦІН НЕ НАЗИВАЙ НІКОЛИ — ні точних, ні приблизних, ні «від». Вартість '
        'щоразу залежить від конкретного випадку, її пишуть колеги. Спитали ціну — '
        'скажи, що точну вартість підкажемо окремо, бо вона залежить від випадку, '
        'постав price_question=true і спокійно веди далі до запису.\n'
        '- ⚠️ Записуй ТІЛЬКИ на те, що є в переліку послуг. Просять те, чого в '
        'переліку немає (наприклад ехокардіографію чи рентген) — чесно скажи, що '
        'саме цього ми не робимо, і не обіцяй. Якщо доречно — запропонуй те, що в '
        'нас Є (наприклад огляд терапевта чи УЗД черевної порожнини). Нічого не '
        'вигадуй: чого немає в переліку — того клініка не робить.\n'
        '- НЕ кажи "записала", "записано", "чекаємо вас", поки не поставила ready=true: '
        'до цього моменту запису ще не існує.\n'
        '- Адресу, телефон і години роботи наводь ДОСЛІВНО так, як подано нижче. '
        'Нічого не додавай від себе: іншого ти не знаєш.\n'
        '- \u26a0\ufe0f НІКОЛИ не кажи, що клініка в якийсь день не працює, якщо цього дня '
        'немає у списку вихідних нижче. Немає дня в переліку вільного часу — значить '
        'на той день усе ЗАЙНЯТО, а не що клініка закрита. Сьогоднішній день теж '
        'робочий: якщо вільний час на сьогодні є в переліку — пропонуй його.\n'
        '- Питай ПРІЗВИЩЕ ТА ІМ\'Я одним питанням ("як вас звати — прізвище та ім\'я?"). '
        'Ім\'я клади в first_name, прізвище — в last_name. Людина назвала лише ім\'я — '
        'перепитай прізвище ОДИН раз, спокійно і без тиску («і прізвище, будь ласка — '
        'щоб завести картку»). Відмовляється або мовчить про прізвище — не наполягай '
        'і записуй як є, запис важливіший за поле.\n'
        '- Якщо в повідомленні ознаки невідкладного стану (кровотеча, судоми, отруєння, '
        'травма, не дихає, здувся живіт) — попроси телефонувати в клініку негайно'
        + (f' на {phone}' if phone else '') + '.\n\n'
        'ЩО ТРЕБА ЗІБРАТИ ДЛЯ ЗАПИСУ (всі сім):\n'
        '  first_name — ім\'я клієнта\n'
        '  last_name — прізвище клієнта\n'
        '  phone — номер телефону\n'
        '  pet_name — кличка тварини\n'
        '  species — вид: dog, cat, rabbit, bird, hamster, guinea_pig, ferret, '
        'chinchilla, rat, turtle, reptile, fish, hedgehog, other\n'
        '  date — дата у форматі РРРР-ММ-ДД, ТІЛЬКИ з переліку вільних нижче\n'
        '  time — час ГГ:ХХ, ТІЛЬКИ з переліку вільних на ту дату\n\n'
        'ВІЛЬНИЙ ЧАС (іншого не пропонуй і не вигадуй):\n'
        f'{_slots_text(slots, org)}\n\n'
        'ПОСЛУГИ КЛІНІКИ — повний перелік того, що ми робимо (цін тут навмисно немає — '
        'не називай їх). Чого тут немає — ми НЕ робимо:\n'
        f'{_services_text(org)}\n\n'
        f'Вже відомо: {json.dumps(known, ensure_ascii=False) if known else "нічого"}\n'
        f'Години роботи: {hours}\n'
        + (f'{days_line}\n' if days_line else '')
        + (f'{exotic_line}\n' if exotic_line else '')
        + (f'Адреса: {address}\n' if address else '')
        + (f'Телефон клініки: {phone}\n' if phone else '')
        + '\nЯкщо клієнт прямо просить живу людину, скаржиться, або питає те, чого ти не '
        'знаєш (наявність ліків, складне медичне) — не вигадуй: скажи, що зараз '
        'уточниш і повернешся з відповіддю, і постав handoff=true.\n\n'
        'Поверни ЛИШЕ JSON без пояснень і без markdown:\n'
        '{"reply": "текст клієнту", "collected": {"first_name": "", "last_name": "", '
        '"phone": "", "pet_name": "", "species": "", "date": "", "time": "", "reason": "", '
        '"surgery": ""}, '
        '"ready": false, "handoff": false, "price_question": false}\n'
        'У collected клади лише те, що справді відоме (решту лишай порожнім) — раніше '
        'зібране не загубиться. ready=true став ЛИШЕ коли відомі всі сім полів і '
        '(last_name — виняток: якщо людина прізвище так і не назвала після одного '
        'перепитування, став ready=true без нього) і '
        'клієнт підтвердив час; тоді у reply не пиши "записую" — підтвердження допише '
        'система сама.'
    )


def _extract_json(raw: str) -> dict:
    """Витягує перший збалансований JSON-об'єкт із тексту моделі.

    Народжено прогоном 10.09: модель то огортала відповідь у ```json, то
    дописувала фразу перед дужкою — `json.loads` падав на всьому підряд, і
    жива розмова мовчки відкочувалась на шаблон. Тому не довіряємо формі
    відповіді, а шукаємо об'єкт у тексті.
    """
    raw = (raw or '').strip()
    if not raw:
        return {}
    if raw.startswith('```'):
        parts = raw.split('```')
        if len(parts) > 1:
            raw = parts[1]
            if raw.lstrip().startswith('json'):
                raw = raw.lstrip()[4:]
    raw = raw.strip()
    start = raw.find('{')
    if start < 0:
        return {}
    depth, in_str, esc = 0, False, False
    for i in range(start, len(raw)):
        ch = raw[i]
        if in_str:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(raw[start:i + 1])
                except json.JSONDecodeError:
                    return {}
    return {}


def _ask_model(chat, slots: dict, collected: dict) -> dict:
    import requests

    try:
        resp = requests.post(
            _API_URL,
            headers={
                'x-api-key': _api_key(),
                'anthropic-version': '2023-06-01',
                'content-type': 'application/json',
            },
            json={
                'model': getattr(settings, 'TG_AUTODIALOG_MODEL', 'claude-haiku-4-5'),
                'max_tokens': 700,
                'system': _system_prompt(chat, slots, collected),
                # Остання репліка асистента — відкрита дужка: далі моделі нема
                # куди подітись, крім як дописати JSON. Без цього вона час від
                # часу починала з людської фрази і розбір падав.
                'messages': _history(chat) + [{'role': 'assistant', 'content': '{'}],
            },
            timeout=20,
        )
        if resp.status_code != 200:
            logger.warning('autodialog LLM HTTP %s: %s', resp.status_code, resp.text[:300])
            return {}
        raw = '{' + resp.json()['content'][0]['text']
        data = _extract_json(raw)
        if not data:
            logger.warning('autodialog: не розібрав відповідь моделі: %s', raw[:300])
        return data if isinstance(data, dict) else {}
    except Exception:
        logger.exception('autodialog LLM failed')
        return {}


def _within_daily_cap(org, limit=500) -> bool:
    """Груба стеля звернень до моделі на клініку за добу.

    Не економія (один хід коштує близько двох десятих цента), а запобіжник від
    аномалії: зациклений клієнт, спам-хвиля або чужий бот не мають перетворитись
    на несподіваний рахунок.
    """
    from django.core.cache import cache

    key = f'autodialog:cap:{getattr(org, "pk", 0)}:{date_type.today().isoformat()}'
    try:
        used = cache.get_or_set(key, 0, 60 * 60 * 26)
        cache.set(key, (used or 0) + 1, 60 * 60 * 26)
        return (used or 0) < limit
    except Exception:
        logger.warning('autodialog: лічильник стелі недоступний, пропускаємо')
        return True


# ── Створення запису ──────────────────────────────────────────────────────────

def _create_booking(chat, collected: dict):
    """Створює (за потреби) клієнта й пацієнта і ставить запис.

    Повертає (starts_at, None) при успіху або (None, 'причина') при відмові.
    Зайнятість перевіряємо тією ж функцією, що й сайт — один час = один запис.
    """
    from zoneinfo import ZoneInfo
    from apps.appointments.models import Appointment
    from apps.appointments.public_api import _slot_is_free
    from apps.clients.models import Client, Patient

    org = chat.organization
    first_name = (collected.get('first_name') or '').strip()[:100]
    last_name = (collected.get('last_name') or '').strip()[:100]
    phone = _norm_phone(collected.get('phone'))
    pet_name = (collected.get('pet_name') or '').strip()[:100]
    species = _norm_species(collected.get('species')) or 'other'
    iso_date = _norm_date(collected.get('date'))
    at_time = _norm_time(collected.get('time'))

    if not (first_name and phone and pet_name and iso_date and at_time):
        return None, 'not_enough'

    try:
        starts_at = timezone.make_aware(
            datetime.fromisoformat(f'{iso_date}T{at_time}:00'), ZoneInfo('Europe/Kyiv')
        )
    except Exception:
        return None, 'bad_datetime'

    if starts_at <= timezone.now():
        return None, 'past'

    exotic_days = _exotic_days(org)
    if exotic_days and _is_exotic(_norm_species(collected.get('species'))):
        if starts_at.astimezone(ZoneInfo('Europe/Kyiv')).weekday() not in exotic_days:
            return None, 'exotic_day'

    surgery_days = _surgery_days(org)
    if surgery_days and _is_surgery(collected):
        if starts_at.astimezone(ZoneInfo('Europe/Kyiv')).weekday() not in surgery_days:
            return None, 'surgery_day'
    if _is_surgery(collected) and not _surgery_time_ok(org, at_time):
        return None, 'surgery_time'

    slot_min = (org.slot_duration if org and org.slot_duration else 30)
    if not _slot_is_free(org, starts_at, slot_min):
        return None, 'busy'

    reason = (collected.get('reason') or '').strip()[:400]
    with transaction.atomic():
        client = Client.objects.filter(organization=org, phone=phone).first()
        if client is None:
            client = Client.objects.create(
                organization=org,
                first_name=first_name,
                last_name=last_name,
                phone=phone,
            )
        patient = Patient.objects.filter(client=client, name__iexact=pet_name).first()
        if patient is None:
            patient = Patient.objects.create(client=client, name=pet_name, species=species)

        notes = 'Записано в Telegram (автозапис)'
        if _is_surgery(collected):
            notes = _SURGERY_STAFF_WARNING + '\n' + notes
        if reason:
            notes += f'\nЗвернення: {reason}'
        appointment = Appointment.objects.create(
            client=client,
            patient=patient,
            doctor=org.get_default_doctor() if org else None,
            starts_at=starts_at,
            duration=slot_min,
            status='scheduled',
            organization=org,
            notes=notes,
        )
        chat.client = client
        chat.last_message_at = timezone.now()
        chat.save(update_fields=['client', 'last_message_at'])

    _notify_staff(
        chat,
        (_SURGERY_STAFF_SHORT + ' ' if _is_surgery(collected) else '')
        + f'✅ Клієнт записався сам: {last_name} {first_name} ({phone}), '
        f'🐾 {pet_name} — {starts_at.strftime("%d.%m о %H:%M")}'
        + (f'. Звернення: {reason}' if reason else ''),
    )
    logger.info('autodialog: booked appointment %s for chat %s', appointment.pk, chat.pk)
    return starts_at, None


def _notify_staff(chat, text: str):
    """Живий сигнал персоналу. До 10.09 його не було зовсім: звернення чекало
    звіту о 12:00 або 19:00 — людина, що написала о 12:12, висіла до вечора."""
    try:
        from .broadcast_tasks import notify_staff_new_message_task
        notify_staff_new_message_task.delay(chat.pk, text)
    except Exception as exc:
        logger.warning('autodialog notify_staff dispatch failed: %s', exc)


# ── Головний вхід ─────────────────────────────────────────────────────────────

def should_engage(chat, text: str) -> bool:
    """Чи ведемо цю розмову ми.

    Не чіпаємо своїх (verified), персонал і тих, хто вже в анкеті онбордингу.
    Не чіпаємо чат, переданий людині: там уже відповідає персонал.
    """
    if chat.client is not None or chat.is_staff:
        return False
    if (chat.onboarding_state or {}).get('step'):
        return False
    if get_stage(chat) == STAGE_HUMAN:
        return False
    return bool((text or '').strip())


def handle_message(chat, text: str):
    """Відповідь на повідомлення незнайомця. Повертає (reply, markup=None).

    Кнопок не повертаємо ніколи — наказ власника 10.09: розмова і тільки розмова.
    """
    from .views import _esc

    data = get_data(chat)
    turns = int(data.get('turns') or 0) + 1

    if turns > _MAX_TURNS:
        set_stage(chat, STAGE_HUMAN, {'turns': turns})
        _notify_staff(chat, f'⚠️ Довга розмова без запису — гляньте, будь ласка: {text[:120]}')
        return (
            'Секунду, уточню це з колегою і повернуся до вас. 🐾',
            None,
        )

    if not _llm_enabled():
        # Запасний варіант: без моделі, але й без кнопок і без «я бот».
        set_stage(chat, STAGE_TALKING, {'turns': turns})
        _notify_staff(chat, f'🆕 Нове звернення: {text[:150]}')
        return (
            'Добрий день! Підкажіть, будь ласка, ваше ім\'я, кличку і вид улюбленця '
            'та номер телефону — підберу зручний час і запишу вас. 🐾',
            None,
        )

    if not _within_daily_cap(chat.organization):
        set_stage(chat, STAGE_HUMAN, {'turns': turns})
        _notify_staff(chat, f'⚠️ Денна стеля автозапису вичерпана. Звернення: {text[:120]}')
        return ('Хвилинку, зараз відповім. 🐾', None)

    slots = _slots_map(chat.organization)
    answer = _ask_model(chat, slots, data)

    if not answer:
        set_stage(chat, STAGE_TALKING, {'turns': turns})
        _notify_staff(chat, f'🆕 Нове звернення: {text[:150]}')
        return (
            'Добрий день! Зараз гляну розклад і підберу вам час. Підкажіть, будь ласка, '
            'ваше ім\'я, кличку і вид улюбленця та номер телефону. 🐾',
            None,
        )

    reply = (answer.get('reply') or '').strip()
    reply, price_cut = _strip_prices(reply)
    if price_cut:
        logger.warning('autodialog: модель назвала ціну, речення вирізано (chat %s)', chat.pk)
    if price_cut or answer.get('price_question'):
        _notify_staff(chat, f'💰 Клієнт питає ціну — напишіть йому, будь ласка: {text[:150]}')
    fresh = answer.get('collected') or {}
    if isinstance(fresh, dict):
        for key, value in fresh.items():
            if value and str(value).strip():
                data[key] = str(value).strip()
    data['turns'] = turns
    data['llm'] = True

    if answer.get('handoff'):
        set_stage(chat, STAGE_HUMAN, data)
        _notify_staff(chat, f'🙋 Клієнт просить людину: {text[:150]}')
        return (_esc(reply or 'Хвилинку, уточню і відповім вам тут.'), None)

    if answer.get('ready'):
        starts_at, err = _create_booking(chat, data)
        if starts_at:
            set_stage(chat, STAGE_DONE, data)
            from apps.tg.views import route_hint
            confirm = (
                f'✅ Записала вас на <b>{starts_at.strftime("%d.%m")}</b> о '
                f'<b>{starts_at.strftime("%H:%M")}</b>. Чекаємо! 🐾'
                + route_hint(chat.organization)
            )
            return ((_esc(reply) + '\n\n' + confirm).strip() if reply else confirm), None
        if err == 'exotic_day':
            data.pop('date', None)
            data.pop('time', None)
            set_stage(chat, STAGE_TALKING, data)
            names = ', '.join(_WEEKDAYS[d] for d in (_exotic_days(chat.organization) or ()))
            return (
                f'Екзотичних улюбленців у нас приймає окремий лікар — {names}. '
                'Підкажіть, який із цих днів вам зручніший, і я покажу вільний час. 🐾',
                None,
            )
        if err == 'surgery_time':
            data.pop('time', None)
            set_stage(chat, STAGE_TALKING, data)
            return (
                f'На операції записуємо не пізніше {_surgery_latest(chat.organization)}. '
                'Підкажіть, будь ласка, раніший зручний час — покажу, що вільно. 🐾',
                None,
            )
        if err == 'surgery_day':
            data.pop('date', None)
            data.pop('time', None)
            set_stage(chat, STAGE_TALKING, data)
            names = ', '.join(_WEEKDAYS[d] for d in (_surgery_days(chat.organization) or ()))
            return (
                f'Операції у нас проводять лише: {names}. '
                'Підкажіть, який із цих днів вам зручніший, і я покажу вільний час. 🐾',
                None,
            )
        if err == 'busy':
            data.pop('time', None)
            set_stage(chat, STAGE_TALKING, data)
            return (
                'Ой, цей час щойно зайняли. Підкажіть інший зручний — покажу, що вільно. 🐾',
                None,
            )
        # Даних не вистачило або дата крива — просто продовжуємо розмову.
        logger.warning('autodialog: booking refused (%s) for chat %s', err, chat.pk)

    set_stage(chat, STAGE_TALKING, data)
    return (_esc(reply) if reply else None), None


# ── Сумісність зі старою версією ──────────────────────────────────────────────

def engage(chat, text: str):
    """Старе ім'я — лишається, щоб нічого не впало під час викочування."""
    return handle_message(chat, text)


def handle_callback(chat, action: str):
    """Старі кнопки ще висять у чатах людей. Обидві тепер ведуть в розмову:
    «дочекаюсь адміністратора» більше не глухий кут."""
    if action in ('ad_book', 'ad_wait'):
        set_stage(chat, STAGE_TALKING, get_data(chat))
        return (
            'Підкажіть, будь ласка, ваше ім\'я, кличку і вид улюбленця та номер '
            'телефону — підберу час і запишу вас. 🐾',
            None,
        )
    return None


def wants_booking(text: str) -> bool:
    low = (text or '').lower()
    return any(w in low for w in ('записат', 'записа', 'на прийом', 'запис'))
