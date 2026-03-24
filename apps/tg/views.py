import io
import json
import requests
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import TelegramChat, TelegramMessage


MENU_BUTTONS = ['🐾 Мої тварини', '📅 Мої записи', '🔬 Аналізи', '💊 Назначення', '📄 Останній чек', '📞 Контакти']
BOT_BASE_URL = 'https://crm.kizuna.com.ua'


def _send_tg(chat_id, text, reply_markup=None):
    token = settings.TELEGRAM_BOT_TOKEN
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {'chat_id': chat_id, 'text': text}
    if reply_markup:
        payload['reply_markup'] = reply_markup
    resp = requests.post(url, json=payload, timeout=10)
    return resp.json()


def _send_tg_photo(chat_id, photo_path, caption=''):
    token = settings.TELEGRAM_BOT_TOKEN
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


def _send_tg_document(chat_id, pdf_bytes, filename, caption=''):
    token = settings.TELEGRAM_BOT_TOKEN
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
def webhook(request):
    if request.method != 'POST':
        return HttpResponse('ok')

    try:
        data = json.loads(request.body)
    except Exception:
        return HttpResponse('bad json', status=400)

    # ── Обробка натискання inline кнопок (вибір тварини) ────────────────────
    callback = data.get('callback_query')
    if callback:
        _handle_callback(callback)
        return HttpResponse('ok')

    message = data.get('message') or data.get('edited_message')
    if not message:
        return HttpResponse('ok')

    from_user = message.get('from', {})
    tg_user_id = from_user.get('id')
    text = message.get('text', '').strip()

    if not tg_user_id or not text:
        return HttpResponse('ok')

    chat, _ = TelegramChat.objects.get_or_create(
        tg_user_id=tg_user_id,
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

    TelegramMessage.objects.create(
        chat=chat,
        direction=TelegramMessage.Direction.IN,
        text=text,
        tg_message_id=message.get('message_id'),
    )

    reply = _handle_command(chat, text, from_user)
    if reply:
        reply_text, reply_markup = reply
        _send_tg(tg_user_id, reply_text, reply_markup)
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
                + f'Раді бачити вас у Kizuna Clinic! 🐾\n\n'
                + 'Оберіть потрібний розділ у меню нижче.'
            )
            return msg, _main_menu_keyboard()
        else:
            msg = (
                greeting
                + 'Це Kizuna Clinic — ветеринарна клініка в Ірпені.\n\n'
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
        msg = (
            'Kizuna Clinic\n'
            '📍 Ірпінь, Університетська 2Ю\n'
            '📞 +38 (068) 239-80-95\n'
            '🕐 Пн–Нд: 10:00 – 18:00'
        )
        return msg, _main_menu_keyboard()

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
        result = _send_tg_photo(tg_id, str(photo_path), caption)
        if not result.get('ok'):
            _send_tg(tg_id, f'⚠️ Не вдалось надіслати: {a.title}')
    # після всіх фото — повернути головне меню
    return f'Надіслано {len(analyses)} аналіз(и) для {patient.name}', _main_menu_keyboard()


def _cmd_treatment_for_pet(chat, patient):
    visit = patient.visits.exclude(treatment='').order_by('-date').first()
    if not visit:
        return (
            f'Записів про лікування для {patient.name} поки немає 💊',
            _main_menu_keyboard(),
        )
    try:
        from django.template.loader import render_to_string
        html = render_to_string('clients/visit_pdf.html', {'visit': visit, 'patient': patient})
        pdf_bytes = _generate_pdf(html, BOT_BASE_URL)
        filename = f'treatment-{patient.name}-{visit.date:%d%m%Y}.pdf'
        caption = f'💊 Назначення · {patient.name} · {visit.date:%d.%m.%Y}'
        result = _send_tg_document(chat.tg_user_id, pdf_bytes, filename, caption)
        if result.get('ok'):
            return f'Протокол останнього прийому для {patient.name} надіслано 💊', _main_menu_keyboard()
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
        pdf_bytes = _generate_pdf(html, BOT_BASE_URL)
        filename = f'invoice-{invoice.pk}.pdf'
        caption = f'📄 Рахунок #{invoice.pk} · {invoice.total} ₴ · {invoice.created_at:%d.%m.%Y}'
        result = _send_tg_document(chat.tg_user_id, pdf_bytes, filename, caption)
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

def _handle_callback(callback):
    """Обробляє натискання inline кнопки вибору тварини."""
    from apps.clients.models import Patient

    tg_user_id = callback.get('from', {}).get('id')
    cb_data = callback.get('data', '')

    # Відповісти Telegram щоб прибрати годинник (answerCallbackQuery)
    callback_id = callback.get('id')
    if callback_id:
        token = settings.TELEGRAM_BOT_TOKEN
        requests.post(
            f"https://api.telegram.org/bot{token}/answerCallbackQuery",
            json={'callback_query_id': callback_id},
            timeout=5,
        )

    if ':' not in cb_data:
        return

    action, patient_id_s = cb_data.split(':', 1)
    if action not in ('analyses', 'treatment'):
        return

    try:
        patient = Patient.objects.select_related('client').get(pk=int(patient_id_s))
    except (Patient.DoesNotExist, ValueError):
        return

    try:
        chat = TelegramChat.objects.get(tg_user_id=tg_user_id)
    except TelegramChat.DoesNotExist:
        return

    # перевірити що клієнт справді власник тварини
    if not chat.client or patient.client_id != chat.client_id:
        return

    reply_text, markup = _pet_action(chat, patient, action)
    _send_tg(tg_user_id, reply_text, markup)
    TelegramMessage.objects.create(
        chat=chat,
        direction=TelegramMessage.Direction.OUT,
        text=reply_text,
        is_read=True,
    )


# ── Список чатів ─────────────────────────────────────────────────────────────

@login_required
def chat_list(request):
    chats = TelegramChat.objects.prefetch_related('messages').all()
    return render(request, 'tg/chat_list.html', {'chats': chats})


# ── Відкрити чат ─────────────────────────────────────────────────────────────

@login_required
def chat_detail(request, pk):
    chat = get_object_or_404(TelegramChat, pk=pk)
    # позначаємо прочитаними
    chat.messages.filter(direction='in', is_read=False).update(is_read=True)

    from apps.clients.models import Client
    unlinked_clients = Client.objects.exclude(tg_chat__isnull=False).order_by('last_name')

    return render(request, 'tg/chat_detail.html', {
        'chat': chat,
        'unlinked_clients': unlinked_clients,
    })


# ── HTMX: нові повідомлення (polling) ────────────────────────────────────────

@login_required
def chat_messages(request, pk):
    chat = get_object_or_404(TelegramChat, pk=pk)
    chat.messages.filter(direction='in', is_read=False).update(is_read=True)
    chat_messages = chat.messages.all()
    return render(request, 'tg/partials/messages.html', {'chat': chat, 'messages': chat_messages})


# ── HTMX: список чатів (для оновлення лічильників) ───────────────────────────

@login_required
def chat_list_partial(request):
    chats = TelegramChat.objects.prefetch_related('messages').all()
    return render(request, 'tg/partials/chat_list.html', {'chats': chats})


# ── Відправити повідомлення ───────────────────────────────────────────────────

@login_required
@require_POST
def send_message(request, pk):
    chat = get_object_or_404(TelegramChat, pk=pk)
    text = request.POST.get('text', '').strip()
    if not text:
        chat_messages = chat.messages.all()
        return render(request, 'tg/partials/messages.html', {'chat': chat, 'messages': chat_messages})

    result = _send_tg(chat.tg_user_id, text)

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
        )
    from apps.clients.models import Client
    unlinked_clients = Client.objects.exclude(tg_chat__isnull=False).order_by('last_name')
    return render(request, 'tg/chat_detail.html', {
        'chat': chat,
        'unlinked_clients': unlinked_clients,
    })


# ── Відправити PDF рахунку в Telegram ────────────────────────────────────────

@login_required
@require_POST
def send_invoice_pdf(request, invoice_pk):
    from django.template.loader import render_to_string
    from apps.billing.models import Invoice

    invoice = get_object_or_404(Invoice, pk=invoice_pk)

    try:
        tg_chat = invoice.client.tg_chat
    except TelegramChat.DoesNotExist:
        tg_chat = None

    if not tg_chat:
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
    result = _send_tg_document(tg_chat.tg_user_id, pdf_bytes, filename, caption)

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
        messages.success(request, f'PDF рахунку #{invoice.pk} відправлено в Telegram.')
    else:
        messages.error(request, f'Telegram помилка: {result.get("description", "невідома")}')

    return redirect('billing:detail', pk=invoice_pk)


# ── Відправити PDF протоколу прийому в Telegram ───────────────────────────────

@login_required
@require_POST
def send_visit_pdf(request, visit_pk):
    from django.template.loader import render_to_string
    from apps.clients.models import Visit

    visit = get_object_or_404(Visit.objects.select_related('patient__client'), pk=visit_pk)
    patient = visit.patient

    try:
        tg_chat = patient.client.tg_chat
    except TelegramChat.DoesNotExist:
        tg_chat = None

    if not tg_chat:
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
    result = _send_tg_document(tg_chat.tg_user_id, pdf_bytes, filename, caption)

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
        messages.success(request, 'PDF протоколу відправлено в Telegram.')
    else:
        messages.error(request, f'Telegram помилка: {result.get("description", "невідома")}')

    return redirect('clients:patient_detail', pk=patient.pk)
