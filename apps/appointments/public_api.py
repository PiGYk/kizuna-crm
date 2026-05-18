"""
Публічне API для форми запису на сайті.

Endpoints:
  GET  /api/public/slots/?date=YYYY-MM-DD&org=<slug>  — вільні часові слоти
  POST /api/public/lead/?org=<slug>                   — прийом заявки з сайту

Контракт безпеки:
  * Параметр `org` (slug організації) — ОБОВ'ЯЗКОВИЙ. Без нього 400.
    Анонімні ендпоінти не повинні «вгадувати» першу-ліпшу активну org —
    це призводило до cross-tenant витоків і записів не в ту клініку.
  * CORS — whitelist через settings.PUBLIC_API_ALLOWED_ORIGINS (за замовч.
    лише https://kizuna.com.ua). Origin не з whitelist → відсутні CORS
    headers, браузер заблокує крос-доменний fetch.
  * Rate limit на lead: 5 запитів/хв з IP через Django cache.
"""
import json
import logging
from datetime import date, datetime, time as dt_time, timedelta

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .models import Appointment, LeadRequest

logger = logging.getLogger(__name__)


# ── CORS whitelist ───────────────────────────────────────────────────────────

def _allowed_origins():
    """Список дозволених origin'ів для CORS. Fallback — лише kizuna.com.ua."""
    return getattr(
        settings,
        'PUBLIC_API_ALLOWED_ORIGINS',
        ['https://kizuna.com.ua'],
    )


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

    if d < timezone.localdate():
        return _cors(JsonResponse({'slots': [], 'date': d.isoformat()}), request)

    work_days = org.work_days if org.work_days else [0, 1, 4, 5, 6]
    if d.weekday() not in work_days:
        return _cors(
            JsonResponse({'slots': [], 'date': d.isoformat(), 'day_off': True}),
            request,
        )

    start_hour = org.work_start if org.work_start else dt_time(10, 0)
    end_hour = org.work_end if org.work_end else dt_time(18, 0)
    duration = org.slot_duration if org.slot_duration else 30

    # Генеруємо слоти
    slots = []
    t = datetime.combine(d, start_hour)
    end_t = datetime.combine(d, end_hour)
    while t < end_t:
        slots.append(t.time())
        t += timedelta(minutes=duration)

    # Зайняті слоти (включно з усіма проміжними при тривалості > slot_duration).
    # Запис на 90 хв з 10:00 блокує 10:00, 10:30, 11:00.
    # ВАЖЛИВО: фільтр по організації, щоб не палити чужі брони.
    booked_appts = Appointment.objects.filter(
        starts_at__date=d,
        organization=org,
    ).exclude(status='cancelled').values_list('starts_at', 'duration')

    booked_times = set()
    for starts_at, dur in booked_appts:
        start_local = timezone.localtime(starts_at)
        # Округлення вгору: 1-30 хв = 1 слот, 31-60 = 2, 61-90 = 3 ...
        n_slots = max(1, (int(dur or duration) + duration - 1) // duration)
        for i in range(n_slots):
            slot_dt = start_local + timedelta(minutes=i * duration)
            booked_times.add(slot_dt.time().replace(second=0, microsecond=0))

    free = [s.strftime('%H:%M') for s in slots
            if s.replace(second=0, microsecond=0) not in booked_times]

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

    lead = LeadRequest.objects.create(
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

    _create_crm_objects(lead, org)
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

def _create_crm_objects(lead: LeadRequest, org) -> None:
    """
    При отриманні заявки з сайту автоматично:
      1. Знаходить або створює Client (за телефоном + org)
      2. Знаходить або створює Patient (за кличкою + client), якщо кличка є
      3. Створює Appointment, якщо вказані дата та час
    """
    try:
        import datetime as dt_module
        from django.utils import timezone as tz
        from apps.clients.models import Client, Patient

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
        if lead.preferred_date and lead.preferred_time:
            naive_dt = dt_module.datetime.combine(lead.preferred_date, lead.preferred_time)
            starts_at = tz.make_aware(naive_dt)
            notes = f'Заявка з сайту. Причина: {lead.service_note}' if lead.service_note else 'Заявка з сайту'
            Appointment.objects.create(
                client=client,
                patient=patient,
                starts_at=starts_at,
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

        chats = TelegramChat.objects.filter(organization=org, receive_leads=True)

        notified = set()
        for chat in chats:
            if chat.tg_user_id not in notified:
                _send_tg(chat.tg_user_id, text, org=org)
                notified.add(chat.tg_user_id)

    except Exception:
        logger.exception('Lead TG notify failed')
