import functools
import io
import json
import logging
import uuid
import requests

logger = logging.getLogger(__name__)
from django.conf import settings
from django.core.files.base import ContentFile
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from django.db import transaction

from .models import TelegramChat, TelegramMessage, QuickReplyPrompt
from .utils import is_mobile


def _require_telegram_plan(view_fn):
    """Декоратор: блокує доступ якщо план не включає Telegram."""
    @functools.wraps(view_fn)
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
    return wrapper


MENU_BUTTONS = ['🐾 Мої тварини', '📋 Паспорт', '📅 Мої записи', '🔬 Аналізи', '💊 Назначення', '📄 Рахунки', '📅 Записатись', '🎫 Знижка', '📞 Контакти']


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
    payload = {'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'}
    if reply_markup:
        payload['reply_markup'] = reply_markup
    resp = requests.post(url, json=payload, timeout=10)
    return resp.json()


def _fetch_avatar_file_id(tg_user_id, org=None):
    """Повертає file_id аватарки юзера або '' якщо немає."""
    token = _get_token(org)
    try:
        resp = requests.get(
            f"https://api.telegram.org/bot{token}/getUserProfilePhotos",
            params={'user_id': tg_user_id, 'limit': 1},
            timeout=10,
        ).json()
        photos = resp.get('result', {}).get('photos', [])
        if photos:
            return photos[0][0]['file_id']  # найменший розмір (~160px), достатньо для аватарки
    except Exception:
        pass
    return ''


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
                data={'chat_id': chat_id, 'caption': caption, 'parse_mode': 'HTML'},
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
        'keyboard': [MENU_BUTTONS[:2], MENU_BUTTONS[2:4], MENU_BUTTONS[4:6], MENU_BUTTONS[6:8], MENU_BUTTONS[8:]],
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
        data={'chat_id': chat_id, 'caption': caption, 'parse_mode': 'HTML'},
        files={'document': (filename, io.BytesIO(pdf_bytes), 'application/pdf')},
        timeout=30,
    )
    return resp.json()


def _send_tg_photo_upload(chat_id, file_bytes, filename, caption='', org=None):
    """Відправити фото з bytes (завантажений файл від користувача)."""
    token = _get_token(org)
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    try:
        resp = requests.post(
            url,
            data={'chat_id': chat_id, 'caption': caption},
            files={'photo': (filename, io.BytesIO(file_bytes))},
            timeout=30,
        )
        return resp.json()
    except Exception:
        return {'ok': False}


def _send_tg_document_upload(chat_id, file_bytes, filename, content_type='application/octet-stream', caption='', org=None):
    """Відправити файл-документ з bytes."""
    token = _get_token(org)
    url = f"https://api.telegram.org/bot{token}/sendDocument"
    try:
        resp = requests.post(
            url,
            data={'chat_id': chat_id, 'caption': caption},
            files={'document': (filename, io.BytesIO(file_bytes), content_type)},
            timeout=60,
        )
        return resp.json()
    except Exception:
        return {'ok': False}


def _send_tg_video_upload(chat_id, file_bytes, filename, caption='', org=None):
    """Відправити відео з bytes (програється inline в Telegram)."""
    token = _get_token(org)
    url = f"https://api.telegram.org/bot{token}/sendVideo"
    try:
        resp = requests.post(
            url,
            data={'chat_id': chat_id, 'caption': caption, 'supports_streaming': True},
            files={'video': (filename, io.BytesIO(file_bytes))},
            timeout=120,
        )
        return resp.json()
    except Exception:
        return {'ok': False}


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
    if not org.webhook_secret:
        logger.warning('webhook: org %s has no webhook_secret — all requests accepted (insecure)', org_slug)
    else:
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
    video = message.get('video')        # відео
    animation = message.get('animation')  # GIF / mp4 без звуку
    video_note = message.get('video_note')  # круглі відео
    audio = message.get('audio')        # музика з метаданими
    sticker = message.get('sticker')    # стікер
    contact = message.get('contact')    # контакт
    location = message.get('location')  # геолокація {latitude, longitude}
    caption = message.get('caption', '').strip()

    has_media = bool(
        photo or document or voice or video or animation
        or video_note or audio or sticker or contact or location
    )
    if not tg_user_id or (not text and not has_media):
        return HttpResponse('ok')

    # Атомарний get_or_create + update щоб уникнути LOST UPDATE при паралельних webhook'ах.
    with transaction.atomic():
        chat, created = TelegramChat.objects.get_or_create(
            tg_user_id=tg_user_id,
            organization=org,
            defaults={
                'tg_username': from_user.get('username', ''),
                'tg_first_name': from_user.get('first_name', ''),
                'tg_last_name': from_user.get('last_name', ''),
            }
        )
        # оновити ім'я якщо змінилось — лише ці поля, без перезапису client/is_staff/etc.
        chat.tg_username = from_user.get('username', '')
        chat.tg_first_name = from_user.get('first_name', '')
        chat.tg_last_name = from_user.get('last_name', '')
        chat.last_message_at = timezone.now()
        update_fields = ['tg_username', 'tg_first_name', 'tg_last_name', 'last_message_at']
        if not chat.avatar_file_id:
            chat.avatar_file_id = _fetch_avatar_file_id(tg_user_id, org=org)
            update_fields.append('avatar_file_id')
        chat.save(update_fields=update_fields)

    # Staff reply на ForceReply-промпт → пересилаємо текст клієнту і виходимо.
    reply_to = message.get('reply_to_message') or {}
    if chat.is_staff and reply_to.get('message_id'):
        if _handle_staff_quickreply_message(chat, text, reply_to.get('message_id')):
            return HttpResponse('ok')

    incoming_msg_id = message.get('message_id')
    is_edited = bool(data.get('edited_message'))

    # Dedup для edited_message — оновити text замість дубля.
    if is_edited and incoming_msg_id:
        existing = TelegramMessage.objects.filter(
            chat=chat, tg_message_id=incoming_msg_id,
        ).first()
        if existing:
            existing.text = text or caption or existing.text
            existing.save(update_fields=['text'])
            return HttpResponse('ok')

    if photo:
        file_id = photo[-1]['file_id']
        content_file, filename = _download_tg_file(file_id, org=chat.organization)
        msg = TelegramMessage(
            chat=chat,
            direction=TelegramMessage.Direction.IN,
            text=caption,
            media_type='photo',
            tg_message_id=incoming_msg_id,
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
            tg_message_id=incoming_msg_id,
        )
        if content_file:
            # Зберігаємо під UUID-іменем — orig_name user-controlled і не довіряємо йому.
            # Оригінальне ім'я вже збережено в media_filename для відображення.
            ext = orig_name.rsplit('.', 1)[-1].lower() if orig_name and '.' in orig_name else filename.rsplit('.', 1)[-1]
            save_as = f'{uuid.uuid4().hex}.{ext}' if ext else uuid.uuid4().hex
            msg.media_file.save(save_as, content_file, save=False)
        msg.save()

    elif video:
        file_id = video['file_id']
        orig_name = video.get('file_name', '')
        duration = video.get('duration', 0)
        content_file, filename = _download_tg_file(file_id, org=chat.organization)
        msg = TelegramMessage(
            chat=chat,
            direction=TelegramMessage.Direction.IN,
            text=caption,
            media_type='video',
            media_filename=orig_name or filename,
            tg_message_id=incoming_msg_id,
        )
        if content_file:
            ext = (orig_name or filename).rsplit('.', 1)[-1].lower() if '.' in (orig_name or filename) else 'mp4'
            save_as = f'{uuid.uuid4().hex}.{ext}'
            msg.media_file.save(save_as, content_file, save=False)
        msg.save()

    elif animation:
        # GIF / mp4 без звуку — handle як video.
        file_id = animation['file_id']
        orig_name = animation.get('file_name', '')
        content_file, filename = _download_tg_file(file_id, org=chat.organization)
        msg = TelegramMessage(
            chat=chat,
            direction=TelegramMessage.Direction.IN,
            text=caption,
            media_type='video',
            media_filename=orig_name or filename or 'animation.mp4',
            tg_message_id=incoming_msg_id,
        )
        if content_file:
            ext = (orig_name or filename).rsplit('.', 1)[-1].lower() if '.' in (orig_name or filename) else 'mp4'
            save_as = f'{uuid.uuid4().hex}.{ext}'
            msg.media_file.save(save_as, content_file, save=False)
        msg.save()

    elif video_note:
        # Круглі відео — handle як video.
        file_id = video_note['file_id']
        content_file, filename = _download_tg_file(file_id, org=chat.organization)
        msg = TelegramMessage(
            chat=chat,
            direction=TelegramMessage.Direction.IN,
            text='',
            media_type='video',
            media_filename=filename or 'video_note.mp4',
            tg_message_id=incoming_msg_id,
        )
        if content_file:
            ext = filename.rsplit('.', 1)[-1].lower() if filename and '.' in filename else 'mp4'
            save_as = f'{uuid.uuid4().hex}.{ext}'
            msg.media_file.save(save_as, content_file, save=False)
        msg.save()

    elif audio:
        # Музика — handle як document з audio.mp3 fallback.
        file_id = audio['file_id']
        orig_name = audio.get('file_name') or audio.get('title') or 'audio.mp3'
        content_file, filename = _download_tg_file(file_id, org=chat.organization)
        msg = TelegramMessage(
            chat=chat,
            direction=TelegramMessage.Direction.IN,
            text=caption,
            media_type='document',
            media_filename=orig_name,
            tg_message_id=incoming_msg_id,
        )
        if content_file:
            ext = (orig_name or filename).rsplit('.', 1)[-1].lower() if '.' in (orig_name or filename) else 'mp3'
            save_as = f'{uuid.uuid4().hex}.{ext}'
            msg.media_file.save(save_as, content_file, save=False)
        msg.save()

    elif sticker:
        # Стікер — emoji preview або '[анім стікер]'. Файл не зберігаємо (.webp/.tgs/.webm).
        if sticker.get('is_animated') or sticker.get('is_video'):
            sticker_text = '[анім стікер]'
        else:
            sticker_text = sticker.get('emoji') or '🎯'
        TelegramMessage.objects.create(
            chat=chat,
            direction=TelegramMessage.Direction.IN,
            text=sticker_text,
            media_type='sticker',
            tg_message_id=incoming_msg_id,
        )

    elif contact:
        # Контакт — phone first_name last_name.
        phone = contact.get('phone_number', '')
        first = contact.get('first_name', '')
        last = contact.get('last_name', '')
        contact_text = f'{phone} {first} {last}'.strip()
        TelegramMessage.objects.create(
            chat=chat,
            direction=TelegramMessage.Direction.IN,
            text=contact_text,
            media_type='contact',
            tg_message_id=incoming_msg_id,
        )

    elif voice:
        file_id = voice['file_id']
        duration = voice.get('duration', 0)
        content_file, filename = _download_tg_file(file_id, org=chat.organization)
        msg = TelegramMessage(
            chat=chat,
            direction=TelegramMessage.Direction.IN,
            text='',  # тривалість тримаємо у filename, щоб не показувати у preview як текст
            media_type='voice',
            media_filename=f'voice-{duration}s.ogg',
            tg_message_id=incoming_msg_id,
        )
        if content_file:
            msg.media_file.save(filename, content_file, save=False)
        msg.save()

    elif location:
        lat = location.get('latitude')
        lon = location.get('longitude')
        # XSS guard: text йде у Google Maps URL. Зберігаємо тільки якщо це pure float pair.
        try:
            safe_text = f'{float(lat)},{float(lon)}'
        except (TypeError, ValueError):
            safe_text = ''
        TelegramMessage.objects.create(
            chat=chat,
            direction=TelegramMessage.Direction.IN,
            text=safe_text,
            media_type='location',
            tg_message_id=incoming_msg_id,
        )

    elif text:
        TelegramMessage.objects.create(
            chat=chat,
            direction=TelegramMessage.Direction.IN,
            text=text,
            tg_message_id=incoming_msg_id,
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

    else:
        # poll / dice / venue / game / etc — silent log і відповідаємо ok щоб TG не retry-ав.
        logger.warning(
            'webhook: unhandled message types in org=%s chat=%s message_keys=%s',
            org.slug, chat.pk, sorted(message.keys()),
        )

    # Нотифікація staff про нове повідомлення — від верифікованих і неверифікованих.
    # Ігноруємо натискання меню-кнопок і команди (/start тощо) — це UI-шум, не повідомлення.
    if not chat.is_staff:
        is_menu_press = text in MENU_BUTTONS or text.startswith('/')
        if has_media or not is_menu_press:
            try:
                from .broadcast_tasks import notify_staff_new_message_task
                notify_staff_new_message_task.delay(chat.pk, text or caption or '[медіа]')
            except Exception as exc:
                # Якщо Celery недоступний — пишемо у лог і не блокуємо webhook.
                logger.warning('notify_staff_new_message dispatch failed: %s', exc)

    return HttpResponse('ok')


def _notify_staff_new_message(chat, preview_text):
    """Надсилає staff-чатам з receive_messages=True сповіщення про нове повідомлення."""
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
        text = (
            f'💬 <b>Нове повідомлення</b>\n\n'
            f'Від: <b>{client_name}</b>\n'
            f'{preview}'
        )
        reply_markup = {
            'inline_keyboard': [[
                {'text': '✍️ Швидка відповідь', 'callback_data': f'quickreply:{chat.pk}'}
            ]]
        }
        for sc in staff_chats:
            _send_tg(sc.tg_user_id, text, reply_markup=reply_markup, org=chat.organization)
    except Exception:
        pass  # не крешити webhook через нотифікацію


def _handle_quickreply_start(staff_tg_user_id, target_chat_pk, org):
    """Staff натиснув '✍️ Швидка відповідь'. Шлемо йому ForceReply-промпт
    і запамʼятовуємо mapping prompt_message_id → target_chat."""
    try:
        staff_chat = TelegramChat.objects.get(
            tg_user_id=staff_tg_user_id,
            organization=org,
            is_staff=True,
        )
    except TelegramChat.DoesNotExist:
        return

    try:
        target = TelegramChat.objects.get(pk=target_chat_pk, organization=org)
    except TelegramChat.DoesNotExist:
        _send_tg(staff_tg_user_id, '⚠️ Чат клієнта не знайдено.', org=org)
        return

    target_name = str(target.client) if target.client else target.display_name
    prompt_text = (
        f'✍️ <b>Відповідь для {target_name}</b>\n\n'
        f'Напишіть повідомлення — воно буде надіслано клієнту від імені клініки.\n'
        f'<i>Щоб скасувати — просто не відповідайте на це повідомлення.</i>'
    )
    force_reply = {
        'force_reply': True,
        'input_field_placeholder': f'Відповідь для {target_name[:40]}',
    }
    resp = _send_tg(staff_tg_user_id, prompt_text, reply_markup=force_reply, org=org)
    prompt_message_id = resp.get('result', {}).get('message_id') if resp.get('ok') else None
    if not prompt_message_id:
        return

    QuickReplyPrompt.objects.create(
        staff_chat=staff_chat,
        target_chat=target,
        prompt_message_id=prompt_message_id,
    )


def _handle_staff_quickreply_message(staff_chat, text, reply_to_message_id):
    """Staff відповів на ForceReply-промпт. Знаходимо mapping, пересилаємо текст
    клієнту, зберігаємо як OUT, консумимо prompt. Повертає True якщо обробили."""
    from datetime import timedelta
    ttl_cutoff = timezone.now() - timedelta(hours=1)
    try:
        prompt = QuickReplyPrompt.objects.select_related('target_chat').get(
            staff_chat=staff_chat,
            prompt_message_id=reply_to_message_id,
            used_at__isnull=True,
            created_at__gte=ttl_cutoff,
        )
    except QuickReplyPrompt.DoesNotExist:
        return False

    target = prompt.target_chat
    if not text:
        _send_tg(staff_chat.tg_user_id, '⚠️ Швидка відповідь підтримує лише текст.', org=target.organization)
        prompt.used_at = timezone.now()
        prompt.save(update_fields=['used_at'])
        return True

    resp = _send_tg(target.tg_user_id, text, org=target.organization)
    if resp.get('ok'):
        TelegramMessage.objects.create(
            chat=target,
            direction=TelegramMessage.Direction.OUT,
            text=text,
            is_read=True,
        )
        target.last_message_at = timezone.now()
        target.save(update_fields=['last_message_at'])
        _send_tg(
            staff_chat.tg_user_id,
            f'✅ Надіслано клієнту <b>{str(target.client) if target.client else target.display_name}</b>.',
            org=target.organization,
        )
    else:
        err = resp.get('description', 'невідома помилка')
        _send_tg(
            staff_chat.tg_user_id,
            f'⚠️ Не вдалось надіслати: {err}',
            org=target.organization,
        )

    prompt.used_at = timezone.now()
    prompt.save(update_fields=['used_at'])
    return True


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

    if text == '📋 Паспорт':
        return _pet_picker(chat, 'passport')

    if text == '🎫 Знижка':
        return _cmd_my_discount(chat)

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

    if text == '📄 Рахунки':
        return _cmd_invoices_list(chat)

    if text == '📅 Записатись':
        return _cmd_book_appointment(chat)

    return None


def _pet_picker(chat, action):
    """Якщо одна тварина — одразу відповідь. Якщо кілька — inline вибір."""
    patients = list(chat.client.patients.all())
    if not patients:
        return 'У вас поки немає зареєстрованих тварин 🐾', _main_menu_keyboard()
    if len(patients) == 1:
        return _pet_action(chat, patients[0], action)
    labels = {'analyses': 'аналізи', 'treatment': 'назначення', 'passport': 'паспорт'}
    label = labels.get(action, action)
    markup = _inline_keyboard([
        (p.name, f'{action}:{p.pk}') for p in patients
    ])
    return f'Для якої тварини показати {label}?', markup


def _pet_action(chat, patient, action):
    if action == 'analyses':
        return _cmd_analyses_for_pet(chat, patient)
    if action == 'treatment':
        return _cmd_treatment_for_pet(chat, patient)
    if action == 'passport':
        return _cmd_passport_for_pet(chat, patient)
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
        html = render_to_string('clients/visit_pdf.html', {
            'visit': visit, 'patient': patient, 'clinic': chat.organization,
        })
        pdf_bytes = _generate_pdf(html, _get_base_url())
        filename = f'treatment-{patient.name}-{visit.date:%d%m%Y}.pdf'
        caption = f'💊 Назначення · {patient.name} · {visit.date:%d.%m.%Y}'
        result = _send_tg_document(chat.tg_user_id, pdf_bytes, filename, caption, org=chat.organization)
        if result.get('ok'):
            return f'Протокол прийому {visit.date:%d.%m.%Y} для {patient.name} надіслано 💊', _main_menu_keyboard()
        return f'⚠️ Помилка надсилання PDF: {result.get("description", "")}', _main_menu_keyboard()
    except Exception as e:
        return f'⚠️ Не вдалось згенерувати PDF: {e}', _main_menu_keyboard()


def _cmd_invoices_list(chat):
    """Показує список рахунків клієнта як inline кнопки."""
    from apps.billing.models import Invoice
    invoices = (
        Invoice.objects
        .filter(client=chat.client)
        .exclude(status='cancelled')
        .order_by('-created_at')[:10]
    )
    if not invoices:
        return 'Рахунків поки немає 📄', _main_menu_keyboard()

    text = '📄 <b>Ваші рахунки:</b>\n\nОберіть рахунок для завантаження PDF:'
    buttons = []
    for inv in invoices:
        label = f'#{inv.pk} · {inv.total} ₴ · {inv.created_at:%d.%m.%Y}'
        if inv.status == 'paid':
            label = '✅ ' + label
        buttons.append([{'text': label, 'callback_data': f'invoice_pdf:{inv.pk}'}])

    keyboard = {'inline_keyboard': buttons}
    return text, keyboard


def _cmd_send_invoice_pdf(chat, invoice_id):
    """Надсилає PDF конкретного рахунку."""
    from apps.billing.models import Invoice
    try:
        invoice = Invoice.objects.prefetch_related('lines').get(pk=invoice_id, client=chat.client)
    except Invoice.DoesNotExist:
        _send_tg(chat.tg_user_id, 'Рахунок не знайдено.', _main_menu_keyboard(), org=chat.organization)
        return
    try:
        from django.template.loader import render_to_string
        lines = invoice.lines.select_related('service', 'product').all()
        html = render_to_string('billing/pdf.html', {
            'invoice': invoice, 'lines': lines, 'clinic': chat.organization,
        })
        pdf_bytes = _generate_pdf(html, _get_base_url())
        filename = f'invoice-{invoice.pk}.pdf'
        caption = f'📄 Рахунок #{invoice.pk} · {invoice.total} ₴ · {invoice.created_at:%d.%m.%Y}'
        _send_tg_document(chat.tg_user_id, pdf_bytes, filename, caption, org=chat.organization)
    except Exception as e:
        _send_tg(chat.tg_user_id, f'⚠️ Помилка: {e}', _main_menu_keyboard(), org=chat.organization)


def _cmd_my_pets(chat):
    patients = chat.client.patients.all()
    if not patients.exists():
        return 'У вас поки немає зареєстрованих тварин 🐾', _main_menu_keyboard()

    lines = ['🐾 <b>Ваші тварини:</b>\n']
    for p in patients:
        line = f'• <b>{p.name}</b> ({p.get_species_display()})'
        if p.breed:
            line += f', <i>{p.breed}</i>'
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

    import zoneinfo
    kyiv_tz = zoneinfo.ZoneInfo('Europe/Kyiv')
    lines = ['📅 <b>Ваші найближчі записи:</b>\n']
    for a in upcoming:
        status_icon = '✅' if a.status == Appointment.Status.CONFIRMED else '🕐'
        pet = a.patient.name if a.patient else '—'
        local_time = a.starts_at.astimezone(kyiv_tz)
        lines.append(f'{status_icon} <b>{local_time:%d.%m.%Y}</b> о <b>{local_time:%H:%M}</b> — {pet}')
    return '\n'.join(lines), _main_menu_keyboard()


# ── Запис на прийом (booking flow) ───────────────────────────────────────────

def _cmd_book_appointment(chat):
    """Step 1: Choose doctor."""
    from django.contrib.auth import get_user_model
    User = get_user_model()
    doctors = User.objects.filter(
        role__in=['admin', 'doctor'],
        organization=chat.organization,
        is_active=True,
    ).order_by('last_name', 'first_name')[:10]

    if not doctors.exists():
        return 'Наразі немає доступних лікарів для запису.', _main_menu_keyboard()

    rows = [(f"{d.last_name} {d.first_name}".strip() or d.username, f"book_doctor:{d.pk}") for d in doctors]
    markup = _inline_keyboard(rows)
    return 'Оберіть лікаря для запису:', markup


def _cmd_book_choose_date(chat, doctor_id):
    """Step 2: Show next 7 working days as date choices."""
    from datetime import date, timedelta
    today = date.today()
    org = chat.organization
    work_days = org.work_days if org and org.work_days else [0, 1, 4, 5, 6]

    rows = []
    candidate = today
    while len(rows) < 7:
        candidate += timedelta(days=1)
        if candidate.weekday() not in work_days:
            continue
        weekdays = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Нд']
        label = f"{weekdays[candidate.weekday()]} {candidate.strftime('%d.%m')}"
        rows.append((label, f"book_date:{doctor_id}:{candidate.isoformat()}"))
    markup = _inline_keyboard(rows)
    return 'Оберіть дату запису:', markup


def _cmd_book_choose_time(chat, doctor_id, date_str):
    """Step 3: Show available time slots."""
    from datetime import datetime, time, timedelta, date as date_type
    from zoneinfo import ZoneInfo

    try:
        chosen_date = date_type.fromisoformat(date_str)
    except ValueError:
        return 'Невірна дата.', _main_menu_keyboard()

    # Working hours from organization settings (fallback: 10:00-18:00, 30 min)
    start_hour = chat.organization.work_start if chat.organization and chat.organization.work_start else time(10, 0)
    end_hour = chat.organization.work_end if chat.organization and chat.organization.work_end else time(18, 0)
    slot_min = chat.organization.slot_duration if chat.organization and chat.organization.slot_duration else 30

    slots = []
    current = datetime.combine(chosen_date, start_hour)
    end_dt = datetime.combine(chosen_date, end_hour)
    while current < end_dt:
        slots.append(current.time())
        current += timedelta(minutes=slot_min)

    # Check existing appointments for this doctor on this date
    from apps.appointments.models import Appointment
    busy = set(
        Appointment.objects.filter(
            doctor_id=doctor_id,
            starts_at__date=chosen_date,
            status__in=['scheduled', 'confirmed'],
        ).values_list('starts_at', flat=True)
    )
    kyiv_tz = ZoneInfo('Europe/Kyiv')
    busy_times = {dt.astimezone(kyiv_tz).strftime('%H:%M') for dt in busy}

    available = [
        (t.strftime('%H:%M'), f"book_time:{doctor_id}:{date_str}:{t.strftime('%H:%M')}")
        for t in slots if t.strftime('%H:%M') not in busy_times
    ]
    if not available:
        return (
            f'На {chosen_date.strftime("%d.%m")} немає вільних слотів. Оберіть інший день.',
            _inline_keyboard([('← Назад', f'book_doctor:{doctor_id}')])
        )

    return f'Оберіть час на {chosen_date.strftime("%d.%m")}:', _inline_keyboard(available[:12])


def _cmd_book_confirm(chat, doctor_id, date_str, time_str):
    """Step 4: Show confirmation message with book/cancel buttons."""
    from django.contrib.auth import get_user_model
    from datetime import date as date_type

    try:
        doctor = get_user_model().objects.get(pk=doctor_id)
    except Exception:
        return 'Лікаря не знайдено.', _main_menu_keyboard()

    doctor_name = doctor.get_full_name() or doctor.username
    try:
        chosen_date = date_type.fromisoformat(date_str)
    except ValueError:
        return 'Невірна дата.', _main_menu_keyboard()

    text = (
        f'📋 <b>Підтвердження запису</b>\n\n'
        f'👨‍⚕️ Лікар: <b>{doctor_name}</b>\n'
        f'📅 Дата: <b>{chosen_date.strftime("%d.%m.%Y")}</b>\n'
        f'🕐 Час: <b>{time_str}</b>\n\n'
        f'Підтверджуєте запис?'
    )
    markup = _inline_keyboard([
        ('Так, записуюсь', f'book_confirm:{doctor_id}:{date_str}:{time_str}'),
        ('Скасувати', 'book_cancel'),
    ])
    return text, markup


def _cmd_book_create(chat, doctor_id, date_str, time_str):
    """Step 5: Create the appointment."""
    from django.contrib.auth import get_user_model
    from datetime import datetime
    from zoneinfo import ZoneInfo

    if not chat.client:
        return 'Для запису потрібно бути зареєстрованим клієнтом. Зверніться до адміністратора.', _main_menu_keyboard()

    try:
        doctor = get_user_model().objects.get(pk=doctor_id)
    except Exception:
        return 'Лікаря не знайдено.', _main_menu_keyboard()

    try:
        kyiv_tz = ZoneInfo('Europe/Kyiv')
        naive_dt = datetime.fromisoformat(f'{date_str}T{time_str}:00')
        starts_at = naive_dt.replace(tzinfo=kyiv_tz)
    except Exception:
        return 'Помилка дати/часу.', _main_menu_keyboard()

    from apps.appointments.models import Appointment
    conflict = Appointment.objects.filter(
        doctor=doctor,
        starts_at=starts_at,
        status__in=['scheduled', 'confirmed'],
    ).exists()
    if conflict:
        return f'На {time_str} вже є запис. Оберіть інший час.', _main_menu_keyboard()

    Appointment.objects.create(
        client=chat.client,
        doctor=doctor,
        starts_at=starts_at,
        duration=chat.organization.slot_duration if chat.organization and chat.organization.slot_duration else 30,
        status='scheduled',
        organization=chat.organization,
        notes='Записано через Telegram-бот',
    )

    doctor_name = doctor.get_full_name() or doctor.username
    text = (
        f'✅ <b>Запис створено!</b>\n\n'
        f'👨‍⚕️ <b>{doctor_name}</b>\n'
        f'📅 {starts_at.strftime("%d.%m.%Y")} о <b>{starts_at.strftime("%H:%M")}</b>\n\n'
        f'Чекаємо вас! 🐾'
    )
    return text, _main_menu_keyboard()


def _cmd_passport_for_pet(chat, patient):
    """Повний паспорт тварини одним повідомленням."""
    from datetime import date
    from apps.clients.models import Vaccine

    lines = [f'📋 <b>Паспорт: {patient.name}</b>\n']

    # Основна інфо
    species = patient.get_species_display()
    breed = f', <i>{patient.breed}</i>' if patient.breed else ''
    lines.append(f'🐾 Вид: {species}{breed}')

    age = getattr(patient, 'age_display', None)
    if age:
        lines.append(f'📅 Вік: {age}')

    sex = getattr(patient, 'get_sex_display', None)
    if sex:
        sex_str = sex()
        if patient.is_neutered:
            sex_str += ' (кастр.)'
        lines.append(f'⚧ Стать: {sex_str}')

    if getattr(patient, 'chip_number', None):
        lines.append(f'🔖 Чіп: <code>{patient.chip_number}</code>')

    if getattr(patient, 'color', None):
        lines.append(f'🎨 Масть: {patient.color}')

    lines.append('')

    # Вакцини
    vaccines = Vaccine.objects.filter(patient=patient).order_by('-date')[:5]
    if vaccines:
        lines.append('💉 <b>Вакцинації:</b>')
        today = date.today()
        for v in vaccines:
            status = ''
            if v.valid_until:
                if v.valid_until < today:
                    status = ' ⚠️ <i>прострочено</i>'
                elif (v.valid_until - today).days <= 30:
                    status = f' ⏰ діє до {v.valid_until:%d.%m.%Y}'
                else:
                    status = f' ✅ до {v.valid_until:%d.%m.%Y}'
            lines.append(f'  • {v.name} ({v.date:%d.%m.%Y}){status}')
    else:
        lines.append('💉 Вакцинацій не знайдено')

    lines.append('')

    # Алергії / нотатки
    if getattr(patient, 'allergies', None):
        lines.append(f'⚠️ <b>Алергії:</b> {patient.allergies}')

    if patient.notes:
        lines.append(f'📝 <b>Нотатки:</b> {patient.notes[:200]}')

    text = '\n'.join(lines)
    return text, _main_menu_keyboard()


def _cmd_my_discount(chat):
    """Показати знижку клієнта."""
    if not chat.client:
        return 'Для перегляду знижки потрібна верифікація. Зверніться до адміністратора.', _main_menu_keyboard()

    client = chat.client
    discount = float(getattr(client, 'discount_percent', 0) or 0)

    if discount > 0:
        text = (
            f'🎫 <b>Ваша персональна знижка</b>\n\n'
            f'👤 {client.full_name()}\n'
            f'💰 Знижка: <b>{discount:.0f}%</b>\n\n'
            f'<i>Знижка застосовується автоматично при оформленні рахунку.</i>\n'
            f'Дякуємо що обираєте нашу клініку! 🐾'
        )
    else:
        text = (
            f'🎫 <b>Програма лояльності</b>\n\n'
            f'👤 {client.full_name()}\n'
            f'На даний момент персональної знижки немає.\n\n'
            f'<i>Зверніться до адміністратора клініки для отримання знижкової картки.</i> 🐾'
        )
    return text, _main_menu_keyboard()


# ── Обробка inline callback (вибір тварини для аналізів/назначень) ───────────

def _handle_health_check_callback(callback_query, chat, org, token):
    """Обробляє відповідь на опитування здоров'я."""
    from apps.clients.models_health import HealthCheck
    from django.utils import timezone as tz

    data = callback_query['data']
    try:
        hc_id = int(data.split('_')[-1])
        hc = HealthCheck.objects.get(pk=hc_id, organization=org)
    except (ValueError, HealthCheck.DoesNotExist):
        return

    if hc.status != HealthCheck.Status.PENDING:
        return  # вже відповіли

    is_ok = data.startswith('hc_ok_')
    hc.status = HealthCheck.Status.OK if is_ok else HealthCheck.Status.CONCERN
    hc.responded_at = tz.now()
    hc.save(update_fields=['status', 'responded_at'])

    if is_ok:
        reply = f'Дякуємо! Раді що {hc.patient.name} почувається добре \U0001f43e'
    else:
        reply = (
            f'Дякуємо за відповідь. Наш лікар зв\'яжеться з вами щодо {hc.patient.name}.\n\n'
            f'Або зателефонуйте: {getattr(org, "phone", "") or "+38 (068) 239-80-95"}'
        )
        # Надіслати нотифікацію staff
        from apps.tg.models import TelegramChat as TC
        staff_chats = TC.objects.filter(organization=org, receive_leads=True)
        for sc in staff_chats:
            _send_tg(sc.tg_user_id, (
                f'\u26a0\ufe0f <b>Клієнт має питання!</b>\n\n'
                f'Пацієнт: <b>{hc.patient.name}</b>\n'
                f'Власник: {hc.patient.client}\n'
                f'Тип: {hc.get_trigger_display()}\n'
                f'Питання: {hc.question[:200]}'
            ), org=org)

    # Відповідь на callback
    requests.post(
        f'https://api.telegram.org/bot{token}/answerCallbackQuery',
        json={'callback_query_id': callback_query['id'], 'text': 'Відповідь записана'},
        timeout=5,
    )
    # Редагувати повідомлення (прибрати кнопки)
    msg = callback_query.get('message', {})
    requests.post(
        f'https://api.telegram.org/bot{token}/editMessageText',
        json={
            'chat_id': chat.tg_user_id,
            'message_id': msg.get('message_id'),
            'text': reply,
            'parse_mode': 'HTML',
        },
        timeout=5,
    )


def _handle_callback(callback, org=None):
    """Обробляє натискання inline кнопки вибору тварини."""
    from apps.clients.models import Patient

    tg_user_id = callback.get('from', {}).get('id')
    cb_data = callback.get('data', '')

    # -- Health Check callbacks (hc_ok_*, hc_concern_*) --
    if cb_data.startswith('hc_ok_') or cb_data.startswith('hc_concern_'):
        try:
            chat = TelegramChat.objects.get(tg_user_id=tg_user_id, organization=org)
        except TelegramChat.DoesNotExist:
            return
        token = _get_token(org)
        _handle_health_check_callback(callback, chat, org, token)
        return

    # Відповісти Telegram щоб прибрати годинник (answerCallbackQuery)
    callback_id = callback.get('id')
    if callback_id:
        token = _get_token(org)
        requests.post(
            f"https://api.telegram.org/bot{token}/answerCallbackQuery",
            json={'callback_query_id': callback_id},
            timeout=5,
        )

    parts = cb_data.split(':')
    action = parts[0]

    # ── Швидка відповідь staff клієнту ─
    if action == 'quickreply' and len(parts) > 1:
        _handle_quickreply_start(tg_user_id, int(parts[1]), org=org)
        return

    # ── Invoice PDF ─
    if action == 'invoice_pdf' and len(parts) > 1:
        try:
            chat = TelegramChat.objects.get(tg_user_id=tg_user_id, organization=org)
            if chat.client:
                _cmd_send_invoice_pdf(chat, int(parts[1]))
        except (TelegramChat.DoesNotExist, ValueError):
            pass
        return

    # ── Booking flow (окремий блок, не потребує chat.client для першого кроку) ─
    if action == 'book_cancel':
        _send_tg(tg_user_id, 'Запис скасовано.', _main_menu_keyboard(), org=org)
        return

    if action == 'book_doctor':
        try:
            chat = TelegramChat.objects.get(tg_user_id=tg_user_id, organization=org)
        except TelegramChat.DoesNotExist:
            return
        reply_text, markup = _cmd_book_choose_date(chat, int(parts[1]))
        _send_tg(tg_user_id, reply_text, markup, org=org)
        return

    if action == 'book_date':
        try:
            chat = TelegramChat.objects.get(tg_user_id=tg_user_id, organization=org)
        except TelegramChat.DoesNotExist:
            return
        reply_text, markup = _cmd_book_choose_time(chat, int(parts[1]), parts[2])
        _send_tg(tg_user_id, reply_text, markup, org=org)
        return

    if action == 'book_time':
        try:
            chat = TelegramChat.objects.get(tg_user_id=tg_user_id, organization=org)
        except TelegramChat.DoesNotExist:
            return
        reply_text, markup = _cmd_book_confirm(chat, int(parts[1]), parts[2], parts[3])
        _send_tg(tg_user_id, reply_text, markup, org=org)
        return

    if action == 'book_confirm':
        try:
            chat = TelegramChat.objects.get(tg_user_id=tg_user_id, organization=org)
        except TelegramChat.DoesNotExist:
            return
        reply_text, markup = _cmd_book_create(chat, int(parts[1]), parts[2], parts[3])
        _send_tg(tg_user_id, reply_text, markup, org=org)
        return

    # ── Старі callback-дії ─────────────────────────────────────────────────────
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

    if action not in ('analyses', 'treatment', 'passport'):
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


# ── Пошук чатів для вибору отримувачів заявок ────────────────────────────────

@login_required
def search_lead_chats(request):
    """GET ?q=... → JSON список чатів організації (для вибору отримувачів заявок)."""
    from django.db.models import Q
    q = request.GET.get('q', '').strip()
    org = request.organization
    qs = TelegramChat.objects.filter(organization=org)
    if len(q) >= 1:
        qs = qs.filter(
            Q(tg_username__icontains=q)
            | Q(tg_first_name__icontains=q)
            | Q(tg_last_name__icontains=q)
            | Q(client__first_name__icontains=q)
            | Q(client__last_name__icontains=q)
        )
    qs = qs.select_related('client').order_by('-last_message_at')[:20]
    return JsonResponse([
        {
            'id': c.pk,
            'name': c.display_name,
            'username': c.tg_username,
            'is_client': bool(c.client),
            'receive_leads': c.receive_leads,
        }
        for c in qs
    ], safe=False)


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
    from django.db.models import Count, Q, Subquery, OuterRef
    last_msg = TelegramMessage.objects.filter(chat=OuterRef('pk')).order_by('-id')
    chats = TelegramChat.objects.filter(
        organization=request.organization,
    ).select_related('client').annotate(
        unread_count_ann=Count(
            'messages',
            filter=Q(messages__direction='in', messages__is_read=False),
        ),
        last_msg_text=Subquery(last_msg.values('text')[:1]),
        last_msg_direction=Subquery(last_msg.values('direction')[:1]),
    )
    template = 'tg/chat_list_mobile.html' if is_mobile(request) else 'tg/chat_list.html'
    return render(request, template, {'chats': chats})


# ── Відкрити чат ─────────────────────────────────────────────────────────────

@login_required
@_require_telegram_plan
def chat_detail(request, pk):
    # Prefetch для quick-send dropdown (раніше 17 queries → ~6).
    qs = (
        TelegramChat.objects
        .select_related('client', 'organization')
        .prefetch_related(
            'client__patients',
            'client__patients__visits',
            'client__patients__ultrasounds',
            'client__patients__analyses',
            'client__invoices',
        )
    )
    chat = get_object_or_404(qs, pk=pk, organization=request.organization)
    # позначаємо прочитаними
    chat.messages.filter(direction='in', is_read=False).update(is_read=True)

    template = 'tg/chat_detail_mobile.html' if is_mobile(request) else 'tg/chat_detail.html'
    return render(request, template, {
        'chat': chat,
    })


@login_required
@require_POST
def chat_toggle_staff(request, pk):
    """Toggle is_staff / receive_leads / receive_messages на чаті (тільки admin)."""
    if request.user.role != 'admin':
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden()
    chat = get_object_or_404(TelegramChat, pk=pk, organization=request.organization)
    field = request.POST.get('field')
    if field in ('is_staff', 'receive_leads', 'receive_messages'):
        current = getattr(chat, field)
        setattr(chat, field, not current)
        chat.save(update_fields=[field])
    return redirect('tg:detail', pk=pk)


# ── HTMX: нові повідомлення (polling) ────────────────────────────────────────

@login_required
@_require_telegram_plan
def chat_messages(request, pk):
    chat = get_object_or_404(
        TelegramChat, pk=pk, organization=request.organization
    )
    chat.messages.filter(direction='in', is_read=False).update(is_read=True)
    # HTMX-poll endpoint — повертаємо лише останні 50 повідомлень (chronological).
    recent_qs = chat.messages.order_by('-created_at')[:50]
    chat_messages = list(recent_qs)[::-1]
    template = 'tg/partials/messages_mobile.html' if is_mobile(request) else 'tg/partials/messages.html'
    return render(request, template, {'chat': chat, 'messages': chat_messages})


# ── HTMX: список чатів (для оновлення лічильників) ───────────────────────────

@login_required
@_require_telegram_plan
def chat_list_partial(request):
    from django.db.models import Q, Count, Subquery, OuterRef
    q = request.GET.get('q', '').strip()
    last_msg = TelegramMessage.objects.filter(chat=OuterRef('pk')).order_by('-id')
    chats = TelegramChat.objects.filter(
        organization=request.organization,
    ).select_related('client')
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
    chats = chats.annotate(
        unread_count_ann=Count(
            'messages',
            filter=Q(messages__direction='in', messages__is_read=False),
        ),
        last_msg_text=Subquery(last_msg.values('text')[:1]),
        last_msg_direction=Subquery(last_msg.values('direction')[:1]),
    )
    template = 'tg/partials/chat_list_mobile.html' if is_mobile(request) else 'tg/partials/chat_list.html'
    return render(request, template, {'chats': chats})


# ── Відправити повідомлення ───────────────────────────────────────────────────

@login_required
@_require_telegram_plan
@require_POST
def send_message(request, pk):
    chat = get_object_or_404(
        TelegramChat, pk=pk, organization=request.organization
    )
    text = request.POST.get('text', '').strip()
    media = request.FILES.get('media')

    if not text and not media:
        chat_messages = list(chat.messages.order_by('-created_at')[:50])[::-1]
        return render(request, 'tg/partials/messages.html', {'chat': chat, 'messages': chat_messages})

    msg = TelegramMessage(
        chat=chat,
        direction=TelegramMessage.Direction.OUT,
        is_read=True,
        sent_by=request.user,
        text=text,
    )

    if media:
        file_bytes = media.read()
        filename = media.name
        content_type = media.content_type or ''
        is_image = content_type.startswith('image/') or filename.lower().endswith(
            ('.jpg', '.jpeg', '.png', '.gif', '.webp')
        )
        is_video = content_type.startswith('video/') or filename.lower().endswith(
            ('.mp4', '.mov', '.avi', '.mkv', '.webm', '.3gp', '.m4v')
        )

        if is_image:
            result = _send_tg_photo_upload(
                chat.tg_user_id, file_bytes, filename, caption=text, org=chat.organization
            )
            msg.media_type = 'photo'
        elif is_video:
            result = _send_tg_video_upload(
                chat.tg_user_id, file_bytes, filename, caption=text, org=chat.organization
            )
            msg.media_type = 'video'
            msg.media_filename = filename
        else:
            result = _send_tg_document_upload(
                chat.tg_user_id, file_bytes, filename, content_type=content_type,
                caption=text, org=chat.organization,
            )
            msg.media_type = 'document'
            msg.media_filename = filename

        msg.tg_message_id = result.get('result', {}).get('message_id')
        msg.media_file.save(filename, ContentFile(file_bytes), save=False)
    else:
        result = _send_tg(chat.tg_user_id, text, org=chat.organization)
        msg.tg_message_id = result.get('result', {}).get('message_id')

    # TG помилка (юзер заблокував бота, чат недоступний тощо) — не зберігаємо як OUT,
    # повертаємо HX-Trigger щоб frontend показав banner.
    if not result.get('ok'):
        err = (result.get('description') or 'невідома помилка Telegram')[:200]
        logger.warning('send_message: TG error for chat %s: %s', chat.pk, result)
        chat_messages = list(chat.messages.order_by('-created_at')[:50])[::-1]
        response = render(request, 'tg/partials/messages.html', {'chat': chat, 'messages': chat_messages})
        response['HX-Trigger'] = json.dumps({'tg-send-failed': {'message': f'Telegram: {err}'}})
        return response

    msg.save()
    chat.last_message_at = timezone.now()
    chat.save(update_fields=['last_message_at'])

    chat_messages = list(chat.messages.order_by('-created_at')[:50])[::-1]
    return render(request, 'tg/partials/messages.html', {'chat': chat, 'messages': chat_messages})


# ── Прив'язати до клієнта ─────────────────────────────────────────────────────

@login_required
@_require_telegram_plan
@require_POST
def link_client(request, pk):
    """Привʼязати/перепривʼязати/відвʼязати клієнта від Telegram-чату.

    POST: client_id=<id> — привʼязати або перепривʼязати на іншого клієнта.
    POST: action=unlink — відвʼязати (client=None), бот переходить у неверифікований режим.
    """
    chat = get_object_or_404(TelegramChat, pk=pk, organization=request.organization)
    action = request.POST.get('action')
    client_id = request.POST.get('client_id')
    previous_client = chat.client

    if action == 'unlink':
        if chat.client:
            chat.client = None
            chat.save(update_fields=['client'])
            _send_tg(
                chat.tg_user_id,
                'ℹ️ Адміністратор відвʼязав ваш акаунт. Ви більше не верифіковані.',
                _remove_keyboard(),
                org=chat.organization,
            )
            messages.success(request, f'Чат відвʼязано від клієнта «{previous_client}».')
    elif client_id:
        from apps.clients.models import Client
        client = get_object_or_404(Client, pk=client_id, organization=request.organization)
        chat.client = client
        chat.save(update_fields=['client'])
        if previous_client and previous_client.pk != client.pk:
            messages.success(request, f'Чат перепривʼязано: «{previous_client}» → «{client}».')
            _send_tg(
                chat.tg_user_id,
                f'ℹ️ Ваш акаунт перевʼязано адміністратором на іншого клієнта: <b>{client}</b>.',
                _main_menu_keyboard(),
                org=chat.organization,
            )
        else:
            _send_tg(
                chat.tg_user_id,
                '✅ Вас верифіковано! Оберіть потрібний розділ у меню нижче.',
                _main_menu_keyboard(),
                org=chat.organization,
            )

    return redirect('tg:detail', pk=chat.pk)


# ── Відправити PDF рахунку в Telegram ────────────────────────────────────────

@login_required
@_require_telegram_plan
@require_POST
def send_invoice_pdf(request, invoice_pk):
    from django.template.loader import render_to_string
    from apps.billing.models import Invoice

    invoice = get_object_or_404(Invoice, pk=invoice_pk, organization=request.organization)

    tg_chats = list(invoice.client.tg_chats.all())
    if not tg_chats:
        messages.error(request, f'Клієнт {invoice.client} не прив\'язаний до Telegram.')
        return redirect('billing:detail', pk=invoice_pk)

    try:
        lines = invoice.lines.select_related('service', 'product').all()
        html_string = render_to_string('billing/pdf.html', {
            'invoice': invoice,
            'lines': lines,
            'clinic': request.organization,
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

    visit = get_object_or_404(
        Visit.objects.select_related('patient__client'),
        pk=visit_pk,
        patient__client__organization=request.organization,
    )
    patient = visit.patient

    tg_chats = list(patient.client.tg_chats.all())
    if not tg_chats:
        messages.error(request, f'Клієнт {patient.client} не прив\'язаний до Telegram.')
        return redirect('clients:patient_detail', pk=patient.pk)

    try:
        html_string = render_to_string('clients/visit_pdf.html', {
            'visit': visit,
            'patient': patient,
            'clinic': request.organization,
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


# ── Відправити PDF УЗД в Telegram ──────────────────────────────────────────

@login_required
@_require_telegram_plan
@require_POST
def send_ultrasound_pdf(request, report_pk):
    from django.template.loader import render_to_string
    from apps.clients.models import UltrasoundReport

    report = get_object_or_404(
        UltrasoundReport.objects.select_related('patient__client', 'doctor'),
        pk=report_pk,
        patient__client__organization=request.organization,
    )
    patient = report.patient

    tg_chats = list(patient.client.tg_chats.all())
    if not tg_chats:
        messages.error(request, f'Клієнт {patient.client} не прив\'язаний до Telegram.')
        return redirect('clients:patient_detail', pk=patient.pk)

    try:
        html_string = render_to_string('clients/ultrasound_pdf.html', {
            'report': report,
            'patient': patient,
            'client': patient.client,
            'clinic': request.organization,
            'request': request,
        })
        pdf_bytes = _generate_pdf(html_string, request.build_absolute_uri('/'))
    except Exception as e:
        messages.error(request, f'Помилка генерації PDF: {e}')
        return redirect('clients:patient_detail', pk=patient.pk)

    filename = f'uzd-{patient.name}-{report.date:%d%m%Y}.pdf'
    caption = f'Протокол УЗД · {patient.name} · {report.date:%d.%m.%Y}'
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
        messages.success(request, f'PDF протоколу УЗД відправлено в Telegram ({sent} чат(ів)).')
    else:
        messages.error(request, 'Не вдалось відправити — Telegram помилка.')

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
        patient__client__organization=request.organization,
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
            msg = TelegramMessage(
                chat=tg_chat,
                direction=TelegramMessage.Direction.OUT,
                text=caption,
                media_type='photo',
                tg_message_id=result.get('result', {}).get('message_id'),
                sent_by=request.user,
                is_read=True,
            )
            with analysis.image.open('rb') as f:
                file_bytes = f.read()
            filename = analysis.image.name.split('/')[-1]
            msg.media_file.save(filename, ContentFile(file_bytes), save=False)
            msg.save()
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


# ──────────────────────────────────────────────
# Broadcast (розсилка)
# ──────────────────────────────────────────────

@login_required
def broadcast_list(request):
    from django.http import HttpResponseForbidden
    if not request.user.is_admin():
        return HttpResponseForbidden('Тільки адмін')
    from .models import Broadcast, TelegramChat
    org = request.organization
    broadcasts = Broadcast.objects.filter(organization=org).select_related('created_by')
    chat_count = TelegramChat.objects.filter(organization=org).count()
    return render(request, 'tg/broadcast_list.html', {
        'broadcasts': broadcasts,
        'chat_count': chat_count,
    })


@login_required
def broadcast_create(request):
    from django.http import HttpResponseForbidden
    if not request.user.is_admin():
        return HttpResponseForbidden('Тільки адмін')
    from .models import Broadcast, TelegramChat
    org = request.organization
    chat_count = TelegramChat.objects.filter(organization=org).count()

    if request.method == 'POST':
        text = request.POST.get('text', '').strip()
        try:
            cooldown_days = max(0, int(request.POST.get('cooldown_days', 0)))
        except (ValueError, TypeError):
            cooldown_days = 0

        if not text:
            messages.error(request, 'Текст не може бути порожнім')
            return render(request, 'tg/broadcast_form.html', {
                'text': text, 'cooldown_days': cooldown_days, 'chat_count': chat_count,
            })

        broadcast = Broadcast.objects.create(
            text=text,
            cooldown_days=cooldown_days,
            organization=org,
            created_by=request.user,
            status=Broadcast.Status.DRAFT,
        )

        if request.POST.get('action') == 'send':
            from .broadcast_tasks import send_broadcast
            send_broadcast.delay(broadcast.pk)
            messages.success(request, f'Розсилку запущено — {chat_count} отримувачів')
            return redirect('tg:broadcast_detail', pk=broadcast.pk)

        messages.success(request, 'Чернетку збережено')
        return redirect('tg:broadcast_detail', pk=broadcast.pk)

    return render(request, 'tg/broadcast_form.html', {'chat_count': chat_count, 'cooldown_days': 0})


@login_required
def broadcast_detail(request, pk):
    from django.http import HttpResponseForbidden
    if not request.user.is_admin():
        return HttpResponseForbidden('Тільки адмін')
    from .models import Broadcast, BroadcastRecipient
    broadcast = get_object_or_404(Broadcast, pk=pk, organization=request.organization)
    skipped = broadcast.recipients.filter(status=BroadcastRecipient.Status.SKIPPED).count()
    return render(request, 'tg/broadcast_detail.html', {
        'broadcast': broadcast,
        'skipped': skipped,
    })


@login_required
def broadcast_send(request, pk):
    """Відправити вже збережену чернетку."""
    from django.http import HttpResponseForbidden
    if not request.user.is_admin():
        return HttpResponseForbidden('Тільки адмін')
    from .models import Broadcast, TelegramChat
    if request.method != 'POST':
        return redirect('tg:broadcast_detail', pk=pk)
    chat_count = TelegramChat.objects.filter(organization=request.organization).count()
    # Атомарний перехід draft→sending щоб уникнути паралельних .delay() через double-click.
    with transaction.atomic():
        broadcast = get_object_or_404(
            Broadcast.objects.select_for_update(),
            pk=pk, organization=request.organization,
        )
        if broadcast.status != Broadcast.Status.DRAFT:
            messages.warning(request, 'Розсилка вже відправляється або завершена')
            return redirect('tg:broadcast_detail', pk=pk)
        broadcast.status = Broadcast.Status.SENDING
        broadcast.save(update_fields=['status'])
    from .broadcast_tasks import send_broadcast
    send_broadcast.delay(broadcast.pk)
    messages.success(request, f'Розсилку запущено — {chat_count} отримувачів')
    return redirect('tg:broadcast_detail', pk=pk)


@login_required
def chat_avatar(request, pk):
    """Проксі аватарки з Telegram — щоб не світити токен бота у браузері."""
    from django.core.cache import cache

    chat = get_object_or_404(TelegramChat, pk=pk, organization=request.organization)
    if not chat.avatar_file_id:
        return HttpResponse(status=404)

    cache_key = f'tg_avatar_{chat.pk}_{chat.avatar_file_id}'
    cached = cache.get(cache_key)
    if cached:
        return HttpResponse(
            cached['data'],
            content_type=cached['content_type'],
            headers={'Cache-Control': 'public, max-age=86400'},
        )

    token = _get_token(chat.organization)
    try:
        info = requests.get(
            f"https://api.telegram.org/bot{token}/getFile",
            params={'file_id': chat.avatar_file_id},
            timeout=10,
        ).json()
        if not info.get('ok'):
            return HttpResponse(status=404)
        file_path = info['result']['file_path']
        resp = requests.get(
            f"https://api.telegram.org/file/bot{token}/{file_path}",
            timeout=15,
            stream=True,
        )
        if not resp.ok:
            return HttpResponse(status=404)
        data = resp.content
        content_type = resp.headers.get('Content-Type', 'image/jpeg')
        cache.set(cache_key, {
            'data': data,
            'content_type': content_type,
        }, timeout=3600)
        return HttpResponse(
            data,
            content_type=content_type,
            headers={'Cache-Control': 'public, max-age=86400'},
        )
    except Exception:
        return HttpResponse(status=404)
