import json
import requests
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import TelegramChat, TelegramMessage


def _send_tg(chat_id, text):
    token = settings.TELEGRAM_BOT_TOKEN
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(url, json={'chat_id': chat_id, 'text': text}, timeout=10)
    return resp.json()


# ── Webhook від Telegram ─────────────────────────────────────────────────────

@csrf_exempt
def webhook(request):
    if request.method != 'POST':
        return HttpResponse('ok')

    try:
        data = json.loads(request.body)
    except Exception:
        return HttpResponse('bad json', status=400)

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

    return HttpResponse('ok')


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
    messages = chat.messages.all()

    from apps.clients.models import Client
    unlinked_clients = Client.objects.exclude(tg_chat__isnull=False).order_by('last_name')

    return render(request, 'tg/chat_detail.html', {
        'chat': chat,
        'messages': messages,
        'unlinked_clients': unlinked_clients,
    })


# ── HTMX: нові повідомлення (polling) ────────────────────────────────────────

@login_required
def chat_messages(request, pk):
    chat = get_object_or_404(TelegramChat, pk=pk)
    chat.messages.filter(direction='in', is_read=False).update(is_read=True)
    messages = chat.messages.all()
    return render(request, 'tg/partials/messages.html', {'chat': chat, 'messages': messages})


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
        messages = chat.messages.all()
        return render(request, 'tg/partials/messages.html', {'chat': chat, 'messages': messages})

    result = _send_tg(chat.tg_user_id, text)

    msg = TelegramMessage.objects.create(
        chat=chat,
        direction=TelegramMessage.Direction.OUT,
        text=text,
        tg_message_id=result.get('result', {}).get('message_id'),
        sent_by=request.user,
        is_read=True,
    )
    chat.last_message_at = timezone.now()
    chat.save(update_fields=['last_message_at'])

    messages = chat.messages.all()
    return render(request, 'tg/partials/messages.html', {'chat': chat, 'messages': messages})


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
    messages = chat.messages.all()
    from apps.clients.models import Client
    unlinked_clients = Client.objects.exclude(tg_chat__isnull=False).order_by('last_name')
    return render(request, 'tg/chat_detail.html', {
        'chat': chat,
        'messages': messages,
        'unlinked_clients': unlinked_clients,
    })
