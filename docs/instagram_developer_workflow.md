# Instagram Direct ↔ VetCRM — інструкція для Claude (developer workflow)

**Контекст:** VetCRM (kizuna-crm) на `/opt/kizuna-crm/`. Уже є робочий модуль `apps/tg/` (Telegram бот: webhook, чат клієнт↔staff, розсилка PDF/фото). Завдання — повторити архітектуру для Instagram Direct, поряд з Telegram. Спільний UI чату повинен показувати обидва канали.

**Коли стартувати:** коли Олег пришле 7 значень з `instagram_owner_setup.md` етап 6.

---

## Вхідні дані (отримуєш від Олега)

```
IG_APP_ID              = ...
IG_APP_SECRET          = ...
IG_USER_ID             = ...   (instagram_business_account.id, ~17 цифр)
FB_PAGE_ID             = ...   (id facebook-сторінки)
IG_WEBHOOK_VERIFY_TOKEN= ...   (рандомний рядок який Олег придумав)
IG_PAGE_TOKEN          = ...   (довгоживучий, 60 днів, автоматично оновлюється коли є User Token)
USER_LONG_TOKEN        = ...   (на випадок refresh)
```

**Зберегти:**
1. У `/opt/kizuna-crm/.env` (chmod 600), додати в `.gitignore` якщо ще нема.
2. Додати у `kizuna_crm/settings.py`:
   ```python
   IG_APP_ID = os.environ.get('IG_APP_ID')
   IG_APP_SECRET = os.environ.get('IG_APP_SECRET')
   IG_USER_ID = os.environ.get('IG_USER_ID')
   IG_WEBHOOK_VERIFY_TOKEN = os.environ.get('IG_WEBHOOK_VERIFY_TOKEN')
   IG_PAGE_TOKEN = os.environ.get('IG_PAGE_TOKEN')
   IG_PAGE_ID = os.environ.get('FB_PAGE_ID')
   ```
3. У `docker-compose.yml` додати environment проброс або через `env_file`.

---

## Розвідка перед кодом

```bash
# Глянути існуючий tg як референс
cat /opt/kizuna-crm/apps/tg/models.py
cat /opt/kizuna-crm/apps/tg/views.py
cat /opt/kizuna-crm/apps/tg/urls.py
ls /opt/kizuna-crm/templates/tg/

# Multi-tenant: перевір як Telegram моделі обмежено організацією
grep -n "organization" /opt/kizuna-crm/apps/tg/models.py
```

**Прийняте архітектурне рішення:** не створюємо `apps/ig/` з дубльованою логікою. Замість цього — **узагальнюємо** через `apps/messaging/` як базу або (простіше) робимо `apps/ig/` з тими ж паттернами що `tg/`. Вибір: **простий шлях — окремий `apps/ig/`** (узагальнення можна зробити пізніше коли захочемо WhatsApp).

---

## Архітектура `apps/ig/`

### Моделі

```python
# apps/ig/models.py
class IgChat(models.Model):
    """Один чат з клієнтом в Instagram. Аналог TelegramChat."""
    organization = ForeignKey('clinic.Organization', on_delete=CASCADE)
    ig_user_id = CharField(max_length=64, db_index=True)  # Instagram-scoped sender ID
    username = CharField(max_length=100, blank=True)      # @username (можна null поки не отримали)
    full_name = CharField(max_length=200, blank=True)
    profile_pic_url = URLField(blank=True)

    # Зв'язок з клієнтом CRM
    client = ForeignKey('clients.Client', null=True, blank=True, on_delete=SET_NULL)
    is_verified = BooleanField(default=False)  # підтверджено staff що це той клієнт

    last_message_at = DateTimeField(null=True, blank=True)
    last_inbound_at = DateTimeField(null=True, blank=True)  # для перевірки 24h window
    unread_count = IntegerField(default=0)

    objects = OrgManager()

    class Meta:
        unique_together = [('organization', 'ig_user_id')]


class IgMessage(models.Model):
    chat = ForeignKey(IgChat, on_delete=CASCADE, related_name='messages')

    # direction
    DIRECTION = [('in', 'Inbound'), ('out', 'Outbound')]
    direction = CharField(max_length=3, choices=DIRECTION)

    # IG message id (mid) — для дедуплікації webhook
    mid = CharField(max_length=200, blank=True, db_index=True)

    text = TextField(blank=True)

    # Медіа
    media_type = CharField(max_length=20, blank=True)  # image, video, audio, file, story_mention
    media_url = URLField(blank=True)
    local_file = FileField(upload_to='ig_media/%Y/%m/', blank=True, null=True)

    # Хто з staff відправив (для outbound)
    sent_by = ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=SET_NULL)

    # Статуси Meta
    is_read = BooleanField(default=False)
    delivered_at = DateTimeField(null=True, blank=True)
    error_message = TextField(blank=True)

    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
```

### Webhook view

```python
# apps/ig/views.py
import hmac, hashlib, json
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings

@csrf_exempt
def ig_webhook(request):
    if request.method == 'GET':
        # Meta verification
        mode = request.GET.get('hub.mode')
        token = request.GET.get('hub.verify_token')
        challenge = request.GET.get('hub.challenge')
        if mode == 'subscribe' and token == settings.IG_WEBHOOK_VERIFY_TOKEN:
            return HttpResponse(challenge)
        return HttpResponse('Forbidden', status=403)

    # POST: подія
    raw = request.body

    # Перевірити підпис X-Hub-Signature-256
    sig = request.headers.get('X-Hub-Signature-256', '')
    expected = 'sha256=' + hmac.new(
        settings.IG_APP_SECRET.encode(),
        raw,
        hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return HttpResponse('Bad signature', status=403)

    payload = json.loads(raw)
    # обробка в process_event(payload) — у services.py
    from apps.ig.services import process_webhook_event
    process_webhook_event(payload)

    return JsonResponse({'ok': True})
```

### Services (логіка)

```python
# apps/ig/services.py
import requests
from django.conf import settings
from .models import IgChat, IgMessage

GRAPH = 'https://graph.facebook.com/v21.0'


def process_webhook_event(payload):
    """Розпарсити webhook payload і зберегти в БД."""
    for entry in payload.get('entry', []):
        for messaging in entry.get('messaging', []):
            sender_id = messaging['sender']['id']
            recipient_id = messaging['recipient']['id']

            # Пропустити echo (наші ж повідомлення)
            if sender_id == settings.IG_USER_ID:
                continue

            # знайти/створити чат
            # Multi-tenant: organization визначається через FB_PAGE_ID → Organization
            org = _resolve_organization(recipient_id)
            chat, created = IgChat._base_manager.get_or_create(
                organization=org,
                ig_user_id=sender_id,
            )

            if created or not chat.username:
                _enrich_profile(chat)  # GET /{ig_user_id}?fields=name,profile_pic

            msg_data = messaging.get('message', {})
            mid = msg_data.get('mid', '')

            # Дедуплікація
            if mid and IgMessage.objects.filter(mid=mid).exists():
                continue

            text = msg_data.get('text', '')
            attachments = msg_data.get('attachments', [])

            msg = IgMessage.objects.create(
                chat=chat,
                direction='in',
                mid=mid,
                text=text,
                media_type=attachments[0]['type'] if attachments else '',
                media_url=attachments[0]['payload']['url'] if attachments else '',
            )

            # Скачати медіа локально (бо URL з IG живе ~5 годин)
            if msg.media_url:
                _download_media_async(msg)

            chat.last_inbound_at = msg.created_at
            chat.last_message_at = msg.created_at
            chat.unread_count = F('unread_count') + 1
            chat.save()


def send_message(chat: IgChat, text: str = None, image_url: str = None, sent_by=None):
    """Надіслати DM. Перевіряє 24-hour window."""
    from datetime import timedelta
    from django.utils import timezone

    if not chat.last_inbound_at or (timezone.now() - chat.last_inbound_at) > timedelta(hours=24):
        raise ValueError('24-hour messaging window expired. Use message_tag or wait for client to write first.')

    payload = {
        'recipient': {'id': chat.ig_user_id},
        'messaging_type': 'RESPONSE',
    }
    if text:
        payload['message'] = {'text': text}
    elif image_url:
        payload['message'] = {
            'attachment': {
                'type': 'image',
                'payload': {'url': image_url, 'is_reusable': False},
            }
        }

    r = requests.post(
        f'{GRAPH}/{settings.IG_PAGE_ID}/messages',
        params={'access_token': settings.IG_PAGE_TOKEN},
        json=payload,
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()

    msg = IgMessage.objects.create(
        chat=chat, direction='out', text=text or '',
        media_url=image_url or '',
        mid=data.get('message_id', ''),
        sent_by=sent_by,
    )
    chat.last_message_at = msg.created_at
    chat.save()
    return msg


def _enrich_profile(chat: IgChat):
    r = requests.get(
        f'{GRAPH}/{chat.ig_user_id}',
        params={
            'fields': 'name,profile_pic,username',
            'access_token': settings.IG_PAGE_TOKEN,
        },
        timeout=10,
    )
    if r.ok:
        d = r.json()
        chat.username = d.get('username', '')
        chat.full_name = d.get('name', '')
        chat.profile_pic_url = d.get('profile_pic', '')
        chat.save(update_fields=['username', 'full_name', 'profile_pic_url'])


def _resolve_organization(recipient_id):
    """Зіставити IG_USER_ID отримувача (Page) з організацією.
    Поки що — одна клініка → org_id=1. Коли SaaS multi-tenant — таблиця IgPageBinding.
    """
    from apps.clinic.models import Organization
    return Organization.objects.get(pk=1)


def _download_media_async(msg: IgMessage):
    """Скачати у local_file. Використати Celery або threading.Thread якщо нема."""
    # MVP: синхронно
    r = requests.get(msg.media_url, timeout=30)
    if r.ok:
        from django.core.files.base import ContentFile
        ext = msg.media_url.split('?')[0].split('.')[-1][:5] or 'bin'
        msg.local_file.save(f'{msg.id}.{ext}', ContentFile(r.content))
```

### URLs

```python
# apps/ig/urls.py
from django.urls import path
from . import views

app_name = 'ig'
urlpatterns = [
    path('webhooks/instagram/', views.ig_webhook, name='webhook'),
    path('chats/', views.chat_list, name='list'),
    path('chats/<int:pk>/', views.chat_detail, name='detail'),
    path('chats/<int:pk>/send/', views.send, name='send'),
    path('chats/<int:pk>/verify-client/', views.verify_client, name='verify_client'),
]
```

У головному `kizuna_crm/urls.py`:
```python
path('webhooks/instagram/', include('apps.ig.urls')),  # для Meta callback
path('messaging/instagram/', include(('apps.ig.urls', 'ig'), namespace='ig')),  # для UI
```
(або використати один include з префіксами всередині — на твій смак)

---

## UI (templates/ig/)

Перевикористати UX `templates/tg/`. Спільний UI чату:
- `templates/ig/list.html` — список чатів (кнопка з Telegram + Instagram у sidebar).
- `templates/ig/detail.html` — окремий чат.
- Або **краще:** додати у `templates/tg/list.html` фільтр-табик `Telegram | Instagram` і робити одну сторінку «Месенджери» з обома джерелами через одну view, що merge’ить queryset (TgChat + IgChat) по `last_message_at`.

Sidebar `base.html`:
- Поточний пункт «Telegram» перейменувати на «Месенджери», іконка — універсальна (chat bubbles).
- Або лишити Telegram окремо + додати Instagram. На смак.

---

## Cron на оновлення токена

Page Token живе поки User Token живий (60 днів). User Token треба оновлювати раз на 50 днів.

```python
# apps/ig/management/commands/refresh_ig_token.py
from django.core.management.base import BaseCommand
from django.conf import settings
import requests, os
from pathlib import Path

class Command(BaseCommand):
    def handle(self, *args, **opts):
        # Поточний User Token зберігається в .env або в БД (краще в БД як IgConfig сінглетон)
        user_token = os.environ.get('USER_LONG_TOKEN')

        # 1. Refresh user token
        r = requests.get(
            'https://graph.facebook.com/v21.0/oauth/access_token',
            params={
                'grant_type': 'fb_exchange_token',
                'client_id': settings.IG_APP_ID,
                'client_secret': settings.IG_APP_SECRET,
                'fb_exchange_token': user_token,
            },
        )
        new_user_token = r.json()['access_token']

        # 2. Get fresh page token
        r2 = requests.get(
            f'https://graph.facebook.com/v21.0/{settings.IG_PAGE_ID}',
            params={'fields': 'access_token', 'access_token': new_user_token},
        )
        new_page_token = r2.json()['access_token']

        # 3. Зберегти (у БД IgConfig або notify через Telegram)
        # MVP: писати у файл /opt/kizuna-crm/.env-tokens-refresh.log
        Path('/opt/kizuna-crm/logs/ig_tokens.log').write_text(
            f'USER_LONG_TOKEN={new_user_token}\nIG_PAGE_TOKEN={new_page_token}\n'
        )
        # + надіслати Олегу в TG бот «онови .env і перезапусти контейнер»
```

Cron (на хості):
```
0 3 1,15 * * cd /opt/kizuna-crm && docker compose exec -T web python manage.py refresh_ig_token >> /opt/kizuna-crm/logs/cron.log 2>&1
```

---

## Тестування перед App Review

1. Поки App у Development — DM приймаються тільки від адмінів App. Олег додасть себе як **Tester** в Roles.
2. Олег пише з власного IG в DM до Kizuna Clinic → перевір що webhook отримав, IgMessage створено.
3. Через CRM відповідь → перевір що приходить в Олегів IG.
4. Verify виконати в App Dashboard → Instagram → Webhooks → Verify and Save (тепер що handler задеплоєний).

---

## Чек-ліст для тебе

- [ ] Отримав від Олега 7 значень → зберіг в `.env` (chmod 600)
- [ ] Прочитав `apps/tg/` як референс
- [ ] Створив `apps/ig/` (models, views, urls, services, admin, migrations)
- [ ] Додав у `INSTALLED_APPS` і у головний `urls.py`
- [ ] Створив webhook handler з підписом + verify
- [ ] Створив services: `process_webhook_event`, `send_message`, `_enrich_profile`, `_download_media`
- [ ] Створив templates `templates/ig/list.html`, `detail.html` (або обʼєднав з tg)
- [ ] Sidebar оновив у base.html (новий пункт або об'єднання)
- [ ] Створив management command `refresh_ig_token`
- [ ] Додав cron у README
- [ ] Перевірив `docker compose exec web python manage.py check` → 0 issues
- [ ] Перевірив `docker compose exec web python manage.py migrate`
- [ ] Перезапустив `docker compose restart web`
- [ ] Перевірив що `https://crm.kizuna.com.ua/webhooks/instagram/` відповідає 200 на GET з валідним verify_token
- [ ] Сказав Олегу що Verify Token can be saved → він натиснув Verify and Save в Meta App
- [ ] Тестовий DM з його IG → побачив у CRM
- [ ] Тестова відповідь з CRM → отримав в IG
- [ ] Згенерував демо-відео для App Review (1-2 хв)
- [ ] Згенерував текст use-case description для permissions
- [ ] Створив сторінку kizuna.com.ua/privacy/ (або згенерував текст для додавання)
- [ ] Оновив `MEMORY.md` і створив `project_vetcrm_instagram.md`
- [ ] Оновив `CLAUDE.md` з новим app

---

## Ризики і пастки

| Ризик | Mitigation |
|---|---|
| Webhook не валідується через bad signature | Перевір що APP_SECRET без зайвих пробілів; HMAC по raw body, не по json.dumps |
| `(#10) Application does not have permission for this action` | Page не підписана на webhook → курл з 4.5 owner_setup |
| `(#100) Tried accessing nonexisting field` | Перевір API version (треба v21.0+); поле може бути deprecated |
| 24-hour window закрите | Реалізувати `message_tag` (HUMAN_AGENT) для відповіді поза window — Meta дозволяє з певними обмеженнями |
| Media URL з IG помирає за 5 годин | `_download_media` зберігає локально одразу при отриманні webhook |
| Race condition на дедуплікацію mid | `unique=True` на `mid` в моделі + ловити `IntegrityError` |
| Multi-tenant: різні клініки одна Page | Поки одна клініка — `_resolve_organization` повертає `pk=1`. Коли SaaS — таблиця `IgPageBinding(organization, ig_user_id)` |
| Echo своїх повідомлень в webhook | Пропускаємо коли `sender_id == IG_USER_ID` (`is_echo=True` теж може прийти у payload) |
| App Review завернуть | Підготувати `kizuna.com.ua/privacy/`, демо-відео, чіткий use-case заздалегідь |
| Токен expired в продакшені | Cron `refresh_ig_token` + alert у TG бот клініки якщо refresh failed |

---

## Memory після завершення

Створити:
- `~/.claude/projects/-root/memory/project_vetcrm_instagram.md` — статус інтеграції, токени НЕ записувати, тільки шляхи в .env, дата деплою, статус App Review.
- Оновити `project_vetcrm.md` — додати до списку apps `ig` і доповнити Telegram до Telegram + Instagram.
- Якщо `apps/messaging/` як обʼєднана база — описати в окремій memory як архітектурне рішення.

---

**Стиль роботи:** не лізь у `apps/tg/` без потреби. Якщо помічаєш що там можна узагальнити — пиши Олегу: «Пропоную винести спільне в `apps/messaging/`», чекай добро. Не перероблюй мовчки.
