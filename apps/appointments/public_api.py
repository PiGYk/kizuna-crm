"""
Публічне API для форми запису на сайті.

Endpoints:
  GET  /api/public/slots/?date=YYYY-MM-DD&org=<slug>  — вільні часові слоти
  POST /api/public/lead/?org=<slug>                   — прийом заявки з сайту

Контракт безпеки:
  * Параметр `org` (slug організації) — ОБОВ'ЯЗКОВИЙ. Без нього 400.
    Анонімні ендпоінти не повинні «вгадувати» першу-ліпшу активну org —
    це призводило до cross-tenant витоків і записів не в ту клініку.
  * CORS — whitelist: settings.PUBLIC_API_ALLOWED_ORIGINS + сайти клінік із
    поля «Веб-сайт» їхніх профілів (щоб кожна клініка вішала форму на свій
    домен без правки конфігу). Origin не з whitelist → відсутні CORS headers,
    браузер заблокує крос-доменний fetch.
  * Rate limit на lead: 5 запитів/хв з IP через Django cache.
"""
import json
import logging
import re
from datetime import date, datetime, time as dt_time, timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .models import Appointment, LeadRequest

logger = logging.getLogger(__name__)


# ── CORS whitelist ───────────────────────────────────────────────────────────

_ORIGINS_CACHE_KEY = 'public_api:org_site_origins'
_ORIGINS_CACHE_TTL = 300  # 5 хв — поле «Веб-сайт» міняють рідко


def _website_to_origins(raw):
    """'kizuna.com.ua' / 'https://kizuna.com.ua/' / 'www.kizuna.com.ua' →
    {'https://kizuna.com.ua', 'https://www.kizuna.com.ua'}.

    Клініка вписує домен як їй зручно, а браузер шле рівно той origin, з якого
    відкрита сторінка — тому дозволяємо обидва варіанти (з www і без).
    Тільки https: форма збирає персональні дані, по http її пускати не можна.
    """
    value = (raw or '').strip()
    if not value:
        return set()
    value = re.sub(r'^https?://', '', value, flags=re.IGNORECASE).strip().strip('/')
    host = value.split('/')[0].split('?')[0].split(':')[0].strip().lower()
    # Проста валідація домену — щоб сміття з поля не потрапило у whitelist.
    if not re.fullmatch(r'[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9-]+)*\.[a-z]{2,}', host or ''):
        return set()
    bare = host[4:] if host.startswith('www.') else host
    return {f'https://{bare}', f'https://www.{bare}'}


def _org_site_origins():
    """Сайти самих клінік із поля «Веб-сайт» в налаштуваннях організації.

    Завдяки цьому нова клініка вішає форму запису на СВІЙ сайт самостійно —
    без правки конфігу сервера. Результат кешуємо: ендпоінт публічний і
    смикається на кожен запит форми.
    """
    cached = cache.get(_ORIGINS_CACHE_KEY)
    if cached is not None:
        return cached

    from apps.clinic.models import Organization
    origins = set()
    try:
        websites = (
            Organization.objects
            .filter(is_active=True)
            .exclude(website='')
            .values_list('website', flat=True)
        )
        for raw in websites:
            origins |= _website_to_origins(raw)
    except Exception:  # БД недоступна — не валимо публічний ендпоінт
        logger.warning('CORS: не вдалось прочитати сайти організацій', exc_info=True)
        return list(())

    result = sorted(origins)
    cache.set(_ORIGINS_CACHE_KEY, result, _ORIGINS_CACHE_TTL)
    return result


def _allowed_origins():
    """Дозволені origin'и: явний список у налаштуваннях + сайти клінік з їхніх
    профілів. Whitelist, не '*' — чужий origin не отримає CORS-хедерів."""
    configured = getattr(
        settings,
        'PUBLIC_API_ALLOWED_ORIGINS',
        ['https://kizuna.com.ua'],
    )
    return list(configured) + _org_site_origins()


def _cors(response, request):
    """Додає CORS-хедери ТІЛЬКИ якщо Origin запиту в whitelist.

    Якщо запит без Origin (server-to-server) або з невідомого origin —
    хедери не додаємо, браузер заблокує. Це безпечніше за `*`.
    """
    origin = request.META.get('HTTP_ORIGIN', '')
    if origin and origin in _allowed_origins():
        response['Access-Control-Allow-Origin'] = origin
        response['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response['Access-Control-Allow-Headers'] = 'Content-Type'
        response['Vary'] = 'Origin'
    return response


# ── Авторизація через org slug ────────────────────────────────────────────────

def _resolve_org(request):
    """Витягує `org` slug з GET або POST і шукає активну Organization.

    Повертає (org, error_response). Якщо org знайдено — error_response is None.
    """
    org_slug = (
        request.GET.get('org')
        or request.POST.get('org')
        or ''
    ).strip()

    if not org_slug:
        # Дозволяємо також dictionary body для POST з JSON.
        if request.method == 'POST' and request.content_type == 'application/json':
            try:
                body = json.loads(request.body)
                org_slug = (body.get('org') or '').strip()
            except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
                org_slug = ''

    if not org_slug:
        return None, _cors(
            JsonResponse({'error': 'org параметр обов\'язковий'}, status=400),
            request,
        )

    from apps.clinic.models import Organization
    try:
        org = Organization.objects.get(slug=org_slug, is_active=True)
    except Organization.DoesNotExist:
        return None, _cors(
            JsonResponse({'error': 'org не знайдено'}, status=404),
            request,
        )
    return org, None


# ── Перевірка зайнятості (єдина правда: показ слотів == прийом заявки) ─────────
#
# Раніше показ слотів (slots_view) рахував зайнятість з урахуванням тривалості,
# а створення запису (lead) перевіряло лише точний збіг starts_at. Через це
# заявка на час, що частково накладається на існуючий запис (напр. 14:30 при
# записі 14:00 на 90 хв), або заявка зі стейлого/гоночного слота — проскакувала
# і створювала накладку. Тепер обидва шляхи використовують ОДИН інтервальний
# перетин і однаковий статус-фільтр (блокує все, крім 'cancelled').

def _blocking_appointments(org, d):
    """Записи org на дату d, що блокують час (усі статуси крім скасованих).

    Повертає список (starts_at, duration) — обидва aware/int.

    ВАЖЛИВО: Appointment.objects — OrgManager (fail-closed). У анонімному
    публічному API org-контекст не виставлений автоматично, тож БЕЗ
    org_context() цей запит повернув би qs.none() і всі слоти вважались би
    вільними (= накладки). Тому явно входимо в org_context(org).
    """
    from apps.clinic.tenant import org_context
    with org_context(org):
        return list(
            Appointment.objects.filter(
                organization=org,
                starts_at__date=d,
            ).exclude(status='cancelled').values_list('starts_at', 'duration')
        )


def _overlaps(new_start, new_duration, blocking, default_duration):
    """True, якщо інтервал [new_start, new_start+new_duration) перетинає будь-який
    із blocking-записів. Класичний перетин: A.start < B.end AND A.end > B.start.
    Порівняння у aware-datetime (UTC), тому tz-зсуви не плутають.
    """
    new_end = new_start + timedelta(minutes=new_duration)
    for ex_start, ex_dur in blocking:
        ex_end = ex_start + timedelta(minutes=int(ex_dur or default_duration))
        if ex_start < new_end and ex_end > new_start:
            return True
    return False


def _org_schedule(org):
    """Робочі параметри org з безпечними дефолтами."""
    work_days = org.work_days if org.work_days else [0, 1, 4, 5, 6]
    start_hour = org.work_start if org.work_start else dt_time(10, 0)
    end_hour = org.work_end if org.work_end else dt_time(18, 0)
    duration = org.slot_duration if org.slot_duration else 30
    return work_days, start_hour, end_hour, duration


def _free_slots(org, d, blocking=None):
    """Список вільних слотів 'HH:MM' для дати d.

    Повертає None, якщо день — вихідний (щоб caller віддав day_off).
    Якщо blocking не передано — підвантажує сам.
    """
    if d < timezone.localdate():
        return []

    work_days, start_hour, end_hour, duration = _org_schedule(org)
    if d.weekday() not in work_days:
        return None  # day_off

    if blocking is None:
        blocking = _blocking_appointments(org, d)

    free = []
    t = datetime.combine(d, start_hour)
    end_t = datetime.combine(d, end_hour)
    while t < end_t:
        slot_start = timezone.make_aware(t)
        if not _overlaps(slot_start, duration, blocking, duration):
            free.append(t.time().strftime('%H:%M'))
        t += timedelta(minutes=duration)
    return free


def _slot_is_free(org, starts_at, duration):
    """True, якщо запит [starts_at, +duration) не перетинає жоден активний запис."""
    d = timezone.localtime(starts_at).date()
    blocking = _blocking_appointments(org, d)
    return not _overlaps(starts_at, duration, blocking, duration)


# ── Вільні слоти ──────────────────────────────────────────────────────────────

def slots_view(request):
    """GET /api/public/slots/?date=2026-04-20&org=kizuna

    Повертає список вільних часових слотів для вказаної дати (клінічні
    години 10:00–18:00, по 30 хв), виключаючи вже зайняті записи.
    """
    if request.method == 'OPTIONS':
        return _cors(JsonResponse({}), request)

    org, err = _resolve_org(request)
    if err is not None:
        return err

    raw = request.GET.get('date', '')
    try:
        d = date.fromisoformat(raw)
    except (ValueError, TypeError):
        return _cors(
            JsonResponse({'error': 'Невірний формат дати. Очікується YYYY-MM-DD.'}, status=400),
            request,
        )

    free = _free_slots(org, d)
    if free is None:
        return _cors(
            JsonResponse({'slots': [], 'date': d.isoformat(), 'day_off': True}),
            request,
        )

    return _cors(JsonResponse({'slots': free, 'date': d.isoformat()}), request)


# ── Rate limit для lead ───────────────────────────────────────────────────────

def _client_ip(request):
    """Намагається отримати реальний IP клієнта з X-Forwarded-For."""
    xff = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '0.0.0.0')


def _rate_limit_ok(request, max_per_minute=5):
    """Простий cache-based rate limit. Повертає True якщо запит дозволено."""
    ip = _client_ip(request)
    minute = int(timezone.now().timestamp() // 60)
    key = f'lead-rl:{ip}:{minute}'
    # incr() атомарно у backend'ах memcached/redis. Якщо ключа нема — set+1.
    try:
        current = cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=70)
        current = 1
    return current <= max_per_minute


# ── Прийом заявки ─────────────────────────────────────────────────────────────

@csrf_exempt
def lead_view(request):
    """POST /api/public/lead/?org=<slug>

    Тіло запиту (JSON):
      name*        — ім'я власника
      phone*       — телефон
      pet_name     — кличка тварини
      pet_type     — вид тварини
      service      — причина звернення
      date         — бажана дата (YYYY-MM-DD)
      time         — бажаний час (HH:MM)
      notes        — додаткові примітки
      source       — джерело ('kizuna-website', 'partner-x' і т.д.)
    """
    if request.method == 'OPTIONS':
        return _cors(JsonResponse({}), request)

    if request.method != 'POST':
        return _cors(JsonResponse({'error': 'Method not allowed'}, status=405), request)

    # Rate limit: 5/хв з одного IP.
    if not _rate_limit_ok(request, max_per_minute=5):
        return _cors(
            JsonResponse({'error': 'Too many requests, повторіть пізніше'}, status=429),
            request,
        )

    org, err = _resolve_org(request)
    if err is not None:
        return err

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return _cors(JsonResponse({'error': 'Invalid JSON'}, status=400), request)

    name = (data.get('name') or '').strip()
    phone = (data.get('phone') or '').strip()

    if not name or not phone:
        return _cors(
            JsonResponse({'error': 'name та phone обов\'язкові'}, status=400),
            request,
        )

    preferred_date = preferred_time = None
    try:
        if data.get('date'):
            preferred_date = date.fromisoformat(data['date'])
    except ValueError:
        pass
    try:
        if data.get('time'):
            preferred_time = datetime.strptime(data['time'], '%H:%M').time()
    except ValueError:
        pass

    # Якщо вказані і дата, і час — час МУСИТЬ бути вільним. Перевірка + створення
    # запису відбуваються в одній транзакції з блокуванням рядків дня, щоб два
    # одночасні сабміти на той самий слот не створили накладку (закриває гонку).
    booking_dt = None
    slot_duration = org.slot_duration if org.slot_duration else 30
    if preferred_date and preferred_time:
        booking_dt = timezone.make_aware(
            datetime.combine(preferred_date, preferred_time)
        )

    lead_payload = dict(
        name=name,
        phone=phone,
        pet_name=(data.get('pet_name') or '').strip(),
        pet_type=(data.get('pet_type') or '').strip(),
        service_note=(data.get('service') or '').strip(),
        preferred_date=preferred_date,
        preferred_time=preferred_time,
        notes=(data.get('notes') or '').strip(),
        organization=org,
        source=(data.get('source') or 'website').strip()[:100],
    )

    class _SlotTaken(Exception):
        pass

    # org_context — ОБОВ'ЯЗКОВО: усі менеджери (Appointment/Client/Patient) —
    # OrgManager/RelatedOrgManager (fail-closed). Без виставленого org-контексту
    # SELECT'и повертають qs.none() → перевірка зайнятості нічого не бачить
    # (накладки) і get_or_create клієнта плодить дублі. Виставляємо явно.
    from apps.clinic.tenant import org_context
    try:
        with org_context(org), transaction.atomic():
            if booking_dt is not None:
                # Серіалізуємо одночасні сабміти: блокуємо рядки записів цього дня.
                lock_date = timezone.localtime(booking_dt).date()
                list(
                    Appointment.objects.select_for_update()
                    .filter(organization=org, starts_at__date=lock_date)
                    .exclude(status='cancelled')
                    .values_list('pk', flat=True)
                )
                if not _slot_is_free(org, booking_dt, slot_duration):
                    raise _SlotTaken()

            lead = LeadRequest.objects.create(**lead_payload)
            _create_crm_objects(lead, org, booking_dt, slot_duration)
    except _SlotTaken:
        # Жорсткий блок: запис не створено, лід не збережено. Віддаємо свіжі
        # вільні слоти, щоб людина одразу обрала інший час.
        fresh = _free_slots(org, preferred_date)
        return _cors(
            JsonResponse(
                {
                    'ok': False,
                    'slot_taken': True,
                    'error': 'Цей час щойно зайняли. Оберіть інший вільний час.',
                    'slots': fresh or [],
                    'date': preferred_date.isoformat(),
                },
                status=409,
            ),
            request,
        )

    _notify_staff(lead, org)

    return _cors(JsonResponse({'ok': True, 'id': lead.pk}), request)


# ── Маппінг виду тварини ─────────────────────────────────────────────────────

_SPECIES_MAP = {
    'Кіт / Кішка':        'cat',
    'Собака':              'dog',
    'Кролик':              'rabbit',
    'Птах':                'bird',
    'Черепаха / Рептилія': 'reptile',
}


def _map_species(pet_type: str) -> str:
    return _SPECIES_MAP.get(pet_type, 'other')


# ── Автоматичне створення Client / Patient / Appointment ─────────────────────

def _create_crm_objects(lead: LeadRequest, org, booking_dt=None, slot_duration=30) -> None:
    """
    При отриманні заявки з сайту автоматично:
      1. Знаходить або створює Client (за телефоном + org)
      2. Знаходить або створює Patient (за кличкою + client), якщо кличка є
      3. Створює Appointment, якщо переданий booking_dt (вже перевірений
         на вільність під блокуванням у lead_view)

    Викликається всередині transaction.atomic() у lead_view. Помилки
    створення Client/Patient логуються, але не валять заявку.
    """
    try:
        from apps.clients.models import Client, Patient

        # Savepoint: збій тут не отруює зовнішню транзакцію lead_view —
        # заявка (LeadRequest) усе одно збережеться.
        with transaction.atomic():
            # ── 1. Client ──
            name_parts = lead.name.strip().split(None, 1)
            first_name = name_parts[0]
            last_name  = name_parts[1] if len(name_parts) > 1 else ''

            client, _ = Client.objects.get_or_create(
                phone=lead.phone[:20],
                organization=org,
                defaults={
                    'first_name': first_name,
                    'last_name':  last_name,
                },
            )

            # ── 2. Patient ──
            patient = None
            if lead.pet_name:
                patient, _ = Patient.objects.get_or_create(
                    client=client,
                    name=lead.pet_name,
                    defaults={'species': _map_species(lead.pet_type)},
                )

            # ── 3. Appointment ──
            # Слот уже перевірений на вільність під select_for_update у lead_view,
            # тож тут просто створюємо запис із тривалістю слота клініки.
            if booking_dt is not None:
                notes = f'Заявка з сайту. Причина: {lead.service_note}' if lead.service_note else 'Заявка з сайту'
                Appointment.objects.create(
                    client=client,
                    patient=patient,
                    starts_at=booking_dt,
                    duration=slot_duration,
                    organization=org,
                    notes=notes,
                )

    except Exception:
        logger.exception('Lead CRM create failed')


# ── Telegram-нотифікація ──────────────────────────────────────────────────────

def _notify_staff(lead: LeadRequest, org) -> None:
    """Надсилає повідомлення в TG усім адмінам організації, у яких є чат з ботом."""
    try:
        from apps.tg.views import _send_tg, _get_token
        from apps.tg.models import TelegramChat
        from django.contrib.auth import get_user_model

        token = _get_token(org)
        if not token:
            return

        date_str = lead.preferred_date.strftime('%d.%m.%Y') if lead.preferred_date else '—'
        time_str = lead.preferred_time.strftime('%H:%M') if lead.preferred_time else '—'

        lines = ['🐾 <b>Нова заявка з сайту</b>\n']
        lines.append(f'👤 <b>{lead.name}</b>')
        lines.append(f'📞 {lead.phone}')
        if lead.pet_name:
            pet_str = lead.pet_name
            if lead.pet_type:
                pet_str += f' ({lead.pet_type})'
            lines.append(f'🐶 <i>{pet_str}</i>')
        if lead.service_note:
            lines.append(f'💊 {lead.service_note}')
        lines.append(f'📅 <b>{date_str}</b> о <b>{time_str}</b>')
        lines.append(f'\n<i>Джерело: {lead.source}</i>')

        text = '\n'.join(lines)

        # TelegramChat теж org-scoped (fail-closed) — без org_context запит
        # повернув би qs.none() і ніхто б не отримав сповіщення.
        from apps.clinic.tenant import org_context
        with org_context(org):
            chats = list(
                TelegramChat.objects.filter(organization=org, receive_leads=True)
            )

        notified = set()
        for chat in chats:
            if chat.tg_user_id not in notified:
                _send_tg(chat.tg_user_id, text, org=org)
                notified.add(chat.tg_user_id)

    except Exception:
        logger.exception('Lead TG notify failed')
