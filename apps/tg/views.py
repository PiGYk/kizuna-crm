import io
import json
import uuid
import requests
from django.conf import settings
from django.core.files.base import ContentFile
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import TelegramChat, TelegramMessage


def _require_telegram_plan(view_fn):
    """Декоратор: блокує доступ якщо план не включає Telegram."""
    def wrapper(request, *args, **kwargs):
        if request.user.is_superuser:
            return view_fn(request, *args, **kwargs)
        org = getattr(request, 'organization', None)
        if org and not org.can_use_telegram:
            return render(request, 'plan_upgrade_required.html', {
                'feature': 'Telegram-бот',
                'required_plan': 'Клініка або Мережа',
            }, status=403)
        return view_fn(request, *args, **kwargs)
    wrapper.__name__ = view_fn.__name__
    return wrapper


MENU_BUTTONS = ['🐾 Мої тварини', '📅 Мої записи', '🔬 Аналізи', '💊 Назначення', '📄 Останній чек', '📞 Контакти']


def _get_token(org=None):
    """Повертає Telegram bot token: з організації (per-tenant) або з settings (fallback)."""
    if org and org.telegram_bot_token:
        return org.telegram_bot_token
    return settings.TELEGRAM_BOT_TOKEN


def _get_base_url():
    """Базова URL для WeasyPrint (CSS/зображення у PDF).
    Береться з SITE_URL → https://{MAIN_DOMAIN} → 'http://localhost'.
    """
    site_url = getattr(settings, 'SITE_URL', '').rstrip('/')
    if site_url:
        return site_url
    main_domain = getattr(settings, 'MAIN_DOMAIN', '')
    if main_domain:
        return f'https://{main_domain}'
    return 'http://localhost'


def _send_tg(chat_id, text, reply_markup=None, org=None):
    token = _get_token(org)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {'chat_id': chat_id, 'text': text}
    if reply_markup:
        payload['reply_markup'] = reply_markup
    resp = requests.post(url, json=payload, timeout=10)
    return resp.json()


def _download_tg_file(file_id, org=None):
    """Завантажує файл з Telegram і повертає (ContentFile, filename) або (None, None)."""
    token = _get_token(org)
    try:
        info = requests.get(
            f"https://api.telegram.org/bot{token}/getFile",
            params={'file_id': file_id},
            timeout=10,
        ).json()
        if not info.get('ok'):
            return None, None
        file_path = info['result']['file_path']
        ext = file_path.rsplit('.', 1)[-1] if '.' in file_path else 'jpg'
        resp = requests.get(
            f"https://api.telegram.org/file/bot{token}/{file_path}",
            timeout=30,
        )
        if not resp.ok:
            return None, None
        return ContentFile(resp.content), f'{uuid.uuid4().hex}.{ext}'
    except Exception:
        return None, None


def _send_tg_photo(chat_id, photo_path, caption='', org=None):
    token = _get_token(org)
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    try:
        with open(photo_path, 'rb') as f:
            resp = requests.post(
                url,
                data={'chat_id': chat_id, 'caption': caption},
                files={'photo': f},
                timeout=30,
            )
        return resp.json()
    except Exception:
        return {'ok': False}


def _inline_keyboard(rows):
    """rows — список [(text, callback_data), ...]"""
    return {
        'inline_keyboard': [[{'text': t, 'callback_data': d}] for t, d in rows]
    }


def _main_menu_keyboard():
    return {
        'keyboard': [MENU_BUTTONS[:2], MENU_BUTTONS[2:4], MENU_BUTTONS[4:]],
        'resize_keyboard': True,
        'persistent': True,
    }


def _remove_keyboard():
    return {'remove_keyboard': True}


def _send_tg_document(chat_id, pdf_bytes, filename, caption='', org=None):
    token = _get_token(org)
    url = f"https://api.telegram.org/bot{token}/sendDocument"
    resp = requests.post(
        url,
        data={'chat_id': chat_id, 'caption': caption},
        files={'document': (filename, io.BytesIO(pdf_bytes), 'application/pdf')},
        timeout=30,
    )
    return resp.json()


def _generate_pdf(html_string, base_url):
    from weasyprint import HTML
    return HTML(string=html_string, base_url=base_url).write_pdf()


# ── Webhook від Telegram ─────────────────────────────────────────────────────

@csrf_exempt
def webhook(request, org_slug):
    if request.method != 'POST':
        return HttpResponse('ok')

    from apps.clinic.models import Organization
    try:
        org = Organization.objects.get(slug=org_slug, is_active=True)
    except Organization.DoesNotExist:
        return HttpResponse('unknown org', status=404)

    # Перевірка підпису Telegram (X-Telegram-Bot-Api-Secret-Token).
    # Якщо webhook зареєстровано з secret_token — перевіряємо.
    # Без перевірки будь-хто міг би надсилати підроблені апдейти.
    if org.webhook_secret:
        incoming = request.headers.get('X-Telegram-Bot-Api-Secret-Token', '')
        if not incoming or incoming != org.webhook_secret:
            return HttpResponse('forbidden', status=403)

    try:
        data = json.loads(request.body)
    except Exception:
        return HttpResponse('bad json', status=400)

    # ── Обробка натискання inline кнопок (вибір тварини) ────────────────────
    callback = data.get('callback_query')
    if callback:
        _handle_callback(callback, org=org)
        return HttpResponse('ok')

    message = data.get('message') or data.get('edited_message')
    if not message:
        return HttpResponse('ok')

    from_user = message.get('from', {})
    tg_user_id = from_user.get('id')
    text = message.get('text', '').strip()
    photo = message.get('photo')        # список PhotoSize, останній — найбільший
    document = message.get('document')  # файл (зображення, PDF, інше)
    voice = message.get('voice')        # голосове повідомлення (.ogg)
    caption = message.get('caption', '').strip()

    has_media = bool(photo or document or voice)
    if not tg_user_id or (not text and not has_media):
        return HttpResponse('ok')

    chat, _ = TelegramChat.objects.get_or_create(
        tg_user_id=tg_user_id,
        organization=org,
        defaults={
            'tg_username': from_user.get('username', ''),
            'tg_first_name': from_user.get('first_name', ''),
            'tg_last_name': from_user.get('last_name', ''),
        }
    )
    # оновити ім'я якщо змінилось
    chat.tg_username = from_user.get('username', '')
    chat.tg_first_name = from_user.get('first_name', '')
    chat.tg_last_name = from_user.get('last_name', '')
    chat.last_message_at = timezone.now()
    chat.save()

    if photo:
        file_id = photo[-1]['file_id']
        content_file, filename = _download_tg_file(file_id, org=chat.organization)
        msg = TelegramMessage(
            chat=chat,
            direction=TelegramMessage.Direction.IN,
            text=caption,
            media_type='photo',
            tg_message_id=message.get('message_id'),
        )
        if content_file:
            msg.media_file.save(filename, content_file, save=False)
        msg.save()

    elif document:
        file_id = document['file_id']
        orig_name = document.get('file_name', '')
        mime = document.get('mime_type', '')
        if mime.startswith('image/'):
            mtype = 'image'
        elif mime == 'application/pdf':
            mtype = 'pdf'
        else:
            mtype = 'document'
        content_file, filename = _download_tg_file(file_id, org=chat.organization)
        msg = TelegramMessage(
            chat=chat,
            direction=TelegramMessage.Direction.IN,
            text=caption,
            media_type=mtype,
            media_filename=orig_name,
            tg_message_id=message.get('message_id'),
        )
        if content_file:
            # Зберігаємо під UUID-іменем — orig_name user-controlled і не довіряємо йому.
            # Оригінальне ім'я вже збережено в media_filename для відображення.
            ext = orig_name.rsplit('.', 1)[-1].lower() if orig_name and '.' in orig_name else filename.rsplit('.', 1)[-1]
            save_as = f'{uuid.uuid4().hex}.{ext}' if ext else uuid.uuid4().hex
            msg.media_file.save(save_as, content_file, save=False)
        msg.save()

    elif voice:
        file_id = voice['file_id']
        duration = voice.get('duration', 0)
        content_file, filename = _download_tg_file(file_id, org=chat.organization)
        msg = TelegramMessage(
            chat=chat,
            direction=TelegramMessage.Direction.IN,
            text=str(duration),  # зберігаємо тривалість у секундах
            media_type='voice',
            tg_message_id=message.get('message_id'),
        )
        if content_file:
            msg.media_file.save(filename, content_file, save=False)
        msg.save()

    else:
        TelegramMessage.objects.create(
            chat=chat,
            direction=TelegramMessage.Direction.IN,
            text=text,
            tg_message_id=message.get('message_id'),
        )
        reply = _handle_command(chat, text, from_user)
        if reply:
            reply_text, reply_markup = reply
            _send_tg(tg_user_id, reply_text, reply_markup, org=chat.organization)
            TelegramMessage.objects.create(
                chat=chat,
                direction=TelegramMessage.Direction.OUT,
                text=reply_text,
                is_read=True,
            )

    return HttpResponse('ok')


def _handle_command(chat, text, from_user):
    """Повертає (text, reply_markup) або None якщо відповідати не треба."""
    is_verified = chat.client is not None

    # /start
    if text == '/start':
        name = from_user.get('first_name', '').strip()
        greeting = f'Привіт{", " + name if name else ""}! 👋\n\n'
        if is_verified:
            msg = (
                greeting
                + f'Раді бачити вас у {chat.organization.name if chat.organization else "нашій клініці"}! 🐾\n\n'
                + 'Оберіть потрібний розділ у меню нижче.'
            )
            return msg, _main_menu_keyboard()
        else:
            msg = (
                greeting
                + f'Це {chat.organization.name if chat.organization else "ветеринарна клініка"}.\n\n'
                + 'Адміністратор отримав ваше повідомлення і відповість найближчим часом.\n\n'
                + 'А поки що — опишіть, будь ласка, вашу проблему або запит до клініки. '
                + 'Вкажіть вид та ім\'я вашого улюбленця, якщо це стосується прийому. 🐾'
            )
            return msg, _remove_keyboard()

    # Меню доступне лише верифікованим
    if not is_verified:
        return None

    if text == '🐾 Мої тварини':
        return _cmd_my_pets(chat)

    if text == '📅 Мої записи':
        return _cmd_my_appointments(chat)

    if text == '📞 Контакти':
        org = chat.organization
        parts = [org.name if org else 'Клініка']
        if org and org.address:
            parts.append(f'📍 {org.address}')
        if org and org.phone:
            parts.append(f'📞 {org.phone}')
        if org and org.work_hours:
            parts.append(f'🕐 {org.work_hours}')
        parts.append('🚨 У термінових випадках телефонуйте у будь-який час — ми відповімо.')
        return '\n'.join(parts), _main_menu_keyboard()

    if text == '🔬 Аналізи':
        return _pet_picker(chat, 'analyses')

    if text == '💊 Назначення':
        return _pet_picker(chat, 'treatment')

    if text == '📄 Останній чек':
        return _cmd_last_invoice(chat)

    return None


def _pet_picker(chat, action):
    """Якщо одна тварина — одразу відповідь. Якщо кілька — inline вибір."""
    patients = list(chat.client.patients.all())
    if not patients:
        return 'У вас поки немає зареєстрованих тварин 🐾', _main_menu_keyboard()
    if len(patients) == 1:
        return _pet_action(chat, patients[0], action)
    label = 'аналізи' if action == 'analyses' else 'назначення'
    markup = _inline_keyboard([
        (p.name, f'{action}:{p.pk}') for p in patients
    ])
    return f'Для якої тварини показати {label}?', markup


def _pet_action(chat, patient, action):
    if action == 'analyses':
        return _cmd_analyses_for_pet(chat, patient)
    if action == 'treatment':
        return _cmd_treatment_for_pet(chat, patient)
    return 'Невідома дія', _main_menu_keyboard()


def _cmd_analyses_for_pet(chat, patient):
    analyses = patient.analyses.order_by('-date')[:5]
    if not analyses:
        return f'Аналізів для {patient.name} поки немає 🔬', _main_menu_keyboard()
    # надсилаємо фото одне за одним, перший з клавіатурою
    tg_id = chat.tg_user_id
    for i, a in enumerate(analyses):
        photo_path = settings.MEDIA_ROOT / a.image.name
        caption = f'🔬 {a.title}\n📅 {a.date:%d.%m.%Y}'
        if a.notes:
            caption += f'\n📝 {a.notes}'
        result = _send_tg_photo(tg_id, str(photo_path), caption, org=chat.organization)
        if not result.get('ok'):
            _send_tg(tg_id, f'⚠️ Не вдалось надіслати: {a.title}', org=chat.organization)
    # після всіх фото — повернути головне меню
    return f'Надіслано {len(analyses)} аналіз(и) для {patient.name}', _main_menu_keyboard()


def _cmd_treatment_for_pet(chat, patient):
    visits = list(patient.visits.exclude(treatment='').order_by('-date')[:5])
    if not visits:
        return (
            f'Записів про лікування для {patient.name} поки немає 💊',
            _main_menu_keyboard(),
        )
    if len(visits) == 1:
        return _send_visit_pdf(chat, patient, visits[0])

    markup = _inline_keyboard([
        (
            f'📅 {v.date:%d.%m.%Y}' + (f' · {v.diagnosis[:30]}…' if len(v.diagnosis) > 30 else (f' · {v.diagnosis}' if v.diagnosis else '')),
            f'visit:{v.pk}',
        )
        for v in visits
    ])
    return f'Оберіть прийом для {patient.name}:', markup


def _send_visit_pdf(chat, patient, visit):
    try:
        from django.template.loader import render_to_string
        html = render_to_string('clients/visit_pdf.html', {'visit': visit, 'patient': patient})
        pdf_bytes = _generate_pdf(html, _get_base_url())
        filename = f'treatment-{patient.name}-{visit.date:%d%m%Y}.pdf'
        caption = f'💊 Назначення · {patient.name} · {visit.date:%d.%m.%Y}'
        result = _send_tg_document(chat.tg_user_id, pdf_bytes, filename, caption, org=chat.organization)
        if result.get('ok'):
            return f'Протокол прийому {visit.date:%d.%m.%Y} для {patient.name} надіслано 💊', _main_menu_keyboard()
        return f'⚠️ Помилка надсилання PDF: {result.get("description", "")}', _main_menu_keyboard()
    except Exception as e:
        return f'⚠️ Не вдалось згенерувати PDF: {e}', _main_menu_keyboard()


def _cmd_last_invoice(chat):
    from apps.billing.models import Invoice
    invoice = (
        Invoice.objects
        .filter(client=chat.client)
        .exclude(status='cancelled')
        .order_by('-created_at')
        .prefetch_related('lines')
        .first()
    )
    if not invoice:
        return 'Рахунків поки немає 📄', _main_menu_keyboard()
    try:
        from django.template.loader import render_to_string
        lines = invoice.lines.select_related('service', 'product').all()
        html = render_to_string('billing/pdf.html', {'invoice': invoice, 'lines': lines})
        pdf_bytes = _generate_pdf(html, _get_base_url())
        filename = f'invoice-{invoice.pk}.pdf'
        caption = f'📄 Рахунок #{invoice.pk} · {invoice.total} ₴ · {invoice.created_at:%d.%m.%Y}'
        result = _send_tg_document(chat.tg_user_id, pdf_bytes, filename, caption, org=chat.organization)
        if result.get('ok'):
            return f'Рахунок #{invoice.pk} надіслано 📄', _main_menu_keyboard()
        return f'⚠️ Помилка надсилання: {result.get("description", "")}', _main_menu_keyboard()
    except Exception as e:
        return f'⚠️ Не вдалось згенерувати PDF: {e}', _main_menu_keyboard()


def _cmd_my_pets(chat):
    patients = chat.client.patients.all()
    if not patients.exists():
        return 'У вас поки немає зареєстрованих тварин 🐾', _main_menu_keyboard()

    lines = ['Ваші тварини:\n']
    for p in patients:
        line = f'• {p.name} ({p.get_species_display()})'
        if p.breed:
            line += f', {p.breed}'
        lines.append(line)
    return '\n'.join(lines), _main_menu_keyboard()


def _cmd_my_appointments(chat):
    from django.utils import timezone
    from apps.appointments.models import Appointment

    upcoming = (
        Appointment.objects
        .filter(
            client=chat.client,
            starts_at__gte=timezone.now(),
            status__in=[Appointment.Status.SCHEDULED, Appointment.Status.CONFIRMED],
        )
        .select_related('patient')
        .order_by('starts_at')[:5]
    )

    if not upcoming.exists():
        return 'Найближчих записів немає 📅\n\nЩоб записатись — напишіть нам!', _main_menu_keyboard()

    lines = ['Ваші найближчі записи:\n']
    for a in upcoming:
        status_icon = '✅' if a.status == Appointment.Status.CONFIRMED else '🕐'
        pet = a.patient.name if a.patient else '—'
        lines.append(f'{status_icon} {a.starts_at:%d.%m.%Y %H:%M} — {pet}')
    return '\n'.join(lines), _main_menu_keyboard()


# ── Обробка inline callback (вибір тварини для аналізів/назначень) ───────────

def _handle_callback(callback, org=None):
    """Обробляє натискання inline кнопки вибору тварини."""
    from apps.clients.models import Patient

    tg_user_id = callback.get('from', {}).get('id')
    cb_data = callback.get('data', '')

    # Відповісти Telegram щоб прибрати годинник (answerCallbackQuery)
    callback_id = callback.get('id')
    if callback_id:
        token = _get_token(org)
        requests.post(
            f"https://api.telegram.org/bot{token}/answerCallbackQuery",
            json={'callback_query_id': callback_id},
            timeout=5,
        )

    if ':' not in cb_data:
        return

    action, id_s = cb_data.split(':', 1)

    try:
        chat = TelegramChat.objects.get(tg_user_id=tg_user_id, organization=org)
    except TelegramChat.DoesNotExist:
        return

    # ── Вибір конкретного прийому ──────────────────────────────────────────
    if action == 'visit':
        from apps.clients.models import Visit
        try:
            visit = Visit.objects.select_related('patient__client').get(pk=int(id_s))
        except (Visit.DoesNotExist, ValueError):
            return
        if not chat.client or visit.patient.client_id != chat.client_id:
            return
        reply_text, markup = _send_visit_pdf(chat, visit.patient, visit)
        _send_tg(tg_user_id, reply_text, markup, org=chat.organization)
        TelegramMessage.objects.create(
            chat=chat, direction=TelegramMessage.Direction.OUT,
            text=reply_text, is_read=True,
        )
        return

    if action not in ('analyses', 'treatment'):
        return

    try:
        patient = Patient.objects.select_related('client').get(pk=int(id_s))
    except (Patient.DoesNotExist, ValueError):
        return

    # перевірити що клієнт справді власник тварини
    if not chat.client or patient.client_id != chat.client_id:
        return

    reply_text, markup = _pet_action(chat, patient, action)
    _send_tg(tg_user_id, reply_text, markup, org=chat.organization)
    TelegramMessage.objects.create(
        chat=chat,
        direction=TelegramMessage.Direction.OUT,
        text=reply_text,
        is_read=True,
    )


# ── Пошук клієнтів (JSON API для автокомпліту) ───────────────────────────────

@login_required
@_require_telegram_plan
def search_clients(request):
    q = request.GET.get('q', '').strip()
    if len(q) < 2:
        return JsonResponse([], safe=False)
    from apps.clients.models import Client
    from django.db.models import Q
    clients = (
        Client.objects
        .filter(Q(last_name__icontains=q) | Q(first_name__icontains=q) | Q(phone__icontains=q))
        .order_by('last_name', 'first_name')[:15]
    )
    return JsonResponse([
        {'id': c.pk, 'name': f'{c.last_name} {c.first_name}', 'phone': c.phone}
        for c in clients
    ], safe=False)


# ── Список чатів ─────────────────────────────────────────────────────────────

@login_required
@_require_telegram_plan
def chat_list(request):
    chats = TelegramChat.objects.prefetch_related('messages').all()
    return render(request, 'tg/chat_list.html', {'chats': chats})


# ── Відкрити чат ─────────────────────────────────────────────────────────────

@login_required
@_require_telegram_plan
def chat_detail(request, pk):
    chat = get_object_or_404(TelegramChat, pk=pk)
    # позначаємо прочитаними
    chat.messages.filter(direction='in', is_read=False).update(is_read=True)

    return render(request, 'tg/chat_detail.html', {
        'chat': chat,
    })


# ── HTMX: нові повідомлення (polling) ────────────────────────────────────────

@login_required
@_require_telegram_plan
def chat_messages(request, pk):
    chat = get_object_or_404(TelegramChat, pk=pk)
    chat.messages.filter(direction='in', is_read=False).update(is_read=True)
    chat_messages = chat.messages.all()
    return render(request, 'tg/partials/messages.html', {'chat': chat, 'messages': chat_messages})


# ── HTMX: список чатів (для оновлення лічильників) ───────────────────────────

@login_required
@_require_telegram_plan
def chat_list_partial(request):
    from django.db.models import Q
    q = request.GET.get('q', '').strip()
    chats = TelegramChat.objects.prefetch_related('messages')
    if q:
        chats = chats.filter(
            Q(tg_first_name__icontains=q) |
            Q(tg_last_name__icontains=q) |
            Q(tg_username__icontains=q) |
            Q(client__first_name__icontains=q) |
            Q(client__last_name__icontains=q) |
            Q(client__phone__icontains=q) |
            Q(client__patients__name__icontains=q)
        ).distinct()
    return render(request, 'tg/partials/chat_list.html', {'chats': chats})


# ── Відправити повідомлення ───────────────────────────────────────────────────

@login_required
@_require_telegram_plan
@require_POST
def send_message(request, pk):
    chat = get_object_or_404(TelegramChat, pk=pk)
    text = request.POST.get('text', '').strip()
    if not text:
        chat_messages = chat.messages.all()
        return render(request, 'tg/partials/messages.html', {'chat': chat, 'messages': chat_messages})

    result = _send_tg(chat.tg_user_id, text, org=chat.organization)

    TelegramMessage.objects.create(
        chat=chat,
        direction=TelegramMessage.Direction.OUT,
        text=text,
        tg_message_id=result.get('result', {}).get('message_id'),
        sent_by=request.user,
        is_read=True,
    )
    chat.last_message_at = timezone.now()
    chat.save(update_fields=['last_message_at'])

    chat_messages = chat.messages.all()
    return render(request, 'tg/partials/messages.html', {'chat': chat, 'messages': chat_messages})


# ── Прив'язати до клієнта ─────────────────────────────────────────────────────

@login_required
@_require_telegram_plan
@require_POST
def link_client(request, pk):
    chat = get_object_or_404(TelegramChat, pk=pk)
    client_id = request.POST.get('client_id')
    if client_id:
        from apps.clients.models import Client
        client = get_object_or_404(Client, pk=client_id)
        chat.client = client
        chat.save(update_fields=['client'])
        _send_tg(
            chat.tg_user_id,
            '✅ Вас верифіковано! Оберіть потрібний розділ у меню нижче.',
            _main_menu_keyboard(),
            org=chat.organization,
        )
    return render(request, 'tg/chat_detail.html', {
        'chat': chat,
    })


# ── Відправити PDF рахунку в Telegram ────────────────────────────────────────

@login_required
@_require_telegram_plan
@require_POST
def send_invoice_pdf(request, invoice_pk):
    from django.template.loader import render_to_string
    from apps.billing.models import Invoice

    invoice = get_object_or_404(Invoice, pk=invoice_pk)

    tg_chats = list(invoice.client.tg_chats.all())
    if not tg_chats:
        messages.error(request, f'Клієнт {invoice.client} не прив\'язаний до Telegram.')
        return redirect('billing:detail', pk=invoice_pk)

    try:
        lines = invoice.lines.select_related('service', 'product').all()
        html_string = render_to_string('billing/pdf.html', {
            'invoice': invoice,
            'lines': lines,
            'request': request,
        })
        pdf_bytes = _generate_pdf(html_string, request.build_absolute_uri('/'))
    except Exception as e:
        messages.error(request, f'Помилка генерації PDF: {e}')
        return redirect('billing:detail', pk=invoice_pk)

    filename = f'invoice-{invoice.pk}.pdf'
    caption = f'Рахунок #{invoice.pk} · {invoice.total} ₴'
    sent = 0
    for tg_chat in tg_chats:
        result = _send_tg_document(tg_chat.tg_user_id, pdf_bytes, filename, caption, org=tg_chat.organization)
        if result.get('ok'):
            TelegramMessage.objects.create(
                chat=tg_chat,
                direction=TelegramMessage.Direction.OUT,
                text=f'[PDF] {caption}',
                tg_message_id=result.get('result', {}).get('message_id'),
                sent_by=request.user,
                is_read=True,
            )
            tg_chat.last_message_at = timezone.now()
            tg_chat.save(update_fields=['last_message_at'])
            sent += 1

    if sent:
        messages.success(request, f'PDF рахунку #{invoice.pk} відправлено в Telegram ({sent} чат(ів)).')
    else:
        messages.error(request, 'Telegram помилка: не вдалось відправити жодному чату.')

    return redirect('billing:detail', pk=invoice_pk)


# ── Відправити PDF протоколу прийому в Telegram ───────────────────────────────

@login_required
@_require_telegram_plan
@require_POST
def send_visit_pdf(request, visit_pk):
    from django.template.loader import render_to_string
    from apps.clients.models import Visit

    visit = get_object_or_404(Visit.objects.select_related('patient__client'), pk=visit_pk)
    patient = visit.patient

    tg_chats = list(patient.client.tg_chats.all())
    if not tg_chats:
        messages.error(request, f'Клієнт {patient.client} не прив\'язаний до Telegram.')
        return redirect('clients:patient_detail', pk=patient.pk)

    try:
        html_string = render_to_string('clients/visit_pdf.html', {
            'visit': visit,
            'patient': patient,
            'request': request,
        })
        pdf_bytes = _generate_pdf(html_string, request.build_absolute_uri('/'))
    except Exception as e:
        messages.error(request, f'Помилка генерації PDF: {e}')
        return redirect('clients:patient_detail', pk=patient.pk)

    filename = f'visit-{patient.name}-{visit.date:%d%m%Y}.pdf'
    caption = f'Протокол прийому · {patient.name} · {visit.date:%d.%m.%Y}'
    sent = 0
    for tg_chat in tg_chats:
        result = _send_tg_document(tg_chat.tg_user_id, pdf_bytes, filename, caption, org=tg_chat.organization)
        if result.get('ok'):
            TelegramMessage.objects.create(
                chat=tg_chat,
                direction=TelegramMessage.Direction.OUT,
                text=f'[PDF] {caption}',
                tg_message_id=result.get('result', {}).get('message_id'),
                sent_by=request.user,
                is_read=True,
            )
            tg_chat.last_message_at = timezone.now()
            tg_chat.save(update_fields=['last_message_at'])
            sent += 1

    if sent:
        messages.success(request, f'PDF протоколу відправлено в Telegram ({sent} чат(ів)).')
    else:
        messages.error(request, 'Telegram помилка: не вдалось відправити жодному чату.')

    return redirect('clients:patient_detail', pk=patient.pk)


# ── Відправити фото аналізу в Telegram ──────────────────────────────────────

@login_required
@_require_telegram_plan
@require_POST
def send_analysis_photo(request, analysis_pk):
    from apps.clients.models import PatientAnalysis

    analysis = get_object_or_404(
        PatientAnalysis.objects.select_related('patient__client'),
        pk=analysis_pk,
    )
    patient = analysis.patient

    tg_chats = list(patient.client.tg_chats.all())
    if not tg_chats:
        messages.error(request, f'Клієнт {patient.client} не прив\'язаний до Telegram.')
        return redirect('clients:patient_detail', pk=patient.pk)

    photo_path = str(settings.MEDIA_ROOT / analysis.image.name)
    caption = f'🔬 {analysis.title}\n📅 {analysis.date:%d.%m.%Y}'
    if analysis.notes:
        caption += f'\n📝 {analysis.notes}'

    sent = 0
    for tg_chat in tg_chats:
        result = _send_tg_photo(tg_chat.tg_user_id, photo_path, caption, org=tg_chat.organization)
        if result.get('ok'):
            TelegramMessage.objects.create(
                chat=tg_chat,
                direction=TelegramMessage.Direction.OUT,
                text=f'[Фото] {caption}',
                tg_message_id=result.get('result', {}).get('message_id'),
                sent_by=request.user,
                is_read=True,
            )
            tg_chat.last_message_at = timezone.now()
            tg_chat.save(update_fields=['last_message_at'])
            sent += 1

    if sent:
        messages.success(request, f'Аналіз «{analysis.title}» відправлено в Telegram ({sent} чат(ів)).')
    else:
        messages.error(request, 'Telegram помилка: не вдалось відправити жодному чату.')

    return redirect('clients:patient_detail', pk=patient.pk)


# ── Реєстрація webhook у Telegram ────────────────────────────────────────────

@login_required
@_require_telegram_plan
@require_POST
def set_webhook(request):
    """Реєструє webhook поточної організації в Telegram API."""
    org = request.organization
    if not org or not org.telegram_bot_token:
        messages.error(request, 'Спочатку збережіть Telegram Bot Token у налаштуваннях.')
        return redirect('clinic:settings')

    base_url = _get_base_url() or request.build_absolute_uri('/').rstrip('/')
    webhook_url = f'{base_url}/tg/webhook/{org.slug}/'

    # Генеруємо secret_token для верифікації підпису Telegram
    import secrets as _secrets
    secret_token = _secrets.token_hex(32)

    token = org.telegram_bot_token
    resp = requests.post(
        f'https://api.telegram.org/bot{token}/setWebhook',
        json={'url': webhook_url, 'secret_token': secret_token},
        timeout=10,
    )
    data = resp.json()
    if data.get('ok'):
        org.webhook_secret = secret_token
        org.save(update_fields=['webhook_secret'])
        messages.success(request, f'Webhook зареєстровано: {webhook_url}')
    else:
        messages.error(request, f'Помилка Telegram: {data.get("description", resp.text)}')

    return redirect('clinic:settings')
