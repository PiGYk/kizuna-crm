# Підготовка Meta App + токенів — інструкція для Олега

**Кому:** Олегу (власнику CRM)
**Коли робити:** Після того як SMM повідомила «готово» (виконано все з `instagram_smm_setup.md`)
**Скільки часу:** ~1-2 години
**Що на виході:** набір з 4 значень які ти передаси Claude — і він почне писати код

---

## Передумови (перевір перед стартом)

- [ ] SMM завершила всі пункти A-G з `instagram_smm_setup.md`
- [ ] У тебе на email `olegdergachov20@gmail.com` прийшов запит «Stati an admin of Kizuna Clinic Page» — підтвердив
- [ ] Заходиш на business.facebook.com під своїм акаунтом і бачиш у списку Pages — Kizuna Clinic
- [ ] Бачиш Instagram акаунт клініки в Business Settings → Instagram Accounts

Якщо щось не так — напиши SMM щоб доробила. Без цього далі не йде.

---

## Етап 1. Створення Meta App

**Куди:** https://developers.facebook.com/apps/

1. Зайти під своїм акаунтом (тим що адмін Page).
2. **Create App** (правий верхній кут) → **Other** → **Next**.
3. Тип: **Business** → **Next**.
4. Назва: `Kizuna CRM Integration` (видно тільки тобі і ревʼюверам Meta).
5. Контактний email: `olegdergachov20@gmail.com`.
6. Business Account: вибрати той що містить Kizuna Clinic.
7. **Create App** → введи свій FB-пароль → готово.

Тебе кидає в Dashboard нового App. Запиши **App ID** (видно зверху, ~16 цифр).

---

## Етап 2. Додати продукт «Instagram»

1. Dashboard додатку → ліва панель → **Add Products**.
2. Знайти **Instagram** → **Set Up**.
3. Усередині → перейти у вкладку **API Setup with Instagram Login** (нова версія API, з 2024).
4. Підключи свій Instagram бізнес-акаунт (через popup) — той що клініки.
5. Запиши:
   - **Instagram User ID** (буде показано після підключення, ~17 цифр) → це **`IG_USER_ID`**
   - **Page ID** Facebook-сторінки клініки (теж видно тут) → це **`FB_PAGE_ID`**

---

## Етап 3. Налаштувати Permissions і Webhook

### 3.1. Дозволи

В App → ліва панель → **App Review** → **Permissions and Features**.

Запросити (поки в Development mode — спрацює без ревʼю):
- `instagram_basic`
- `instagram_manage_messages`
- `pages_manage_metadata`
- `pages_messaging`
- `pages_show_list`
- `business_management`

Кнопка біля кожного — **Request advanced access**. Заповни короткий опис use-case (можна шаблонний: «Receive Instagram DMs in our internal CRM and reply to clients»).

### 3.2. Webhook

В App → **Instagram** → **Webhooks**:

1. **Callback URL:** `https://crm.kizuna.com.ua/webhooks/instagram/`
2. **Verify Token:** придумай рандомний рядок ~32 символи (наприклад `kizuna_ig_webhook_a8f3k2j9x7m1q4w8z6b5n3p`) → **запиши** його. Це **`IG_WEBHOOK_VERIFY_TOKEN`**.
3. **Subscribe to fields:** обовʼязково `messages`, `messaging_postbacks`, `messaging_seen`. Додатково — `message_reactions`, `messaging_referrals` (опційно).

⚠️ Поки Claude не задеплоїть webhook handler — Meta скаже «Verification failed». Це нормально. Передай Verify Token Claude-у; він напише handler, потім ти повернешся сюди і натиснеш **Verify and Save**.

---

## Етап 4. Генерація довгоживучого токена

Це найболючіший крок — токени треба правильно виставити.

### 4.1. User Token через Graph API Explorer

1. Відкрий https://developers.facebook.com/tools/explorer/
2. Application: вибери щойно створений `Kizuna CRM Integration`.
3. User or Page: **User Token**.
4. Permissions: натисни **Add a Permission** і додай ВСІ що з 3.1 (`instagram_basic`, `instagram_manage_messages`, `pages_manage_metadata`, `pages_messaging`, `pages_show_list`, `business_management`).
5. **Generate Access Token** → підтвердити в попапі (вибрати Page клініки + Instagram акаунт).
6. Скопіювати токен (короткоживучий, 1-2 години).

### 4.2. Перетворити на довгоживучий User Token (60 днів)

Відкрий термінал і виконай (підстав свої значення):

```bash
APP_ID="<твій App ID з етапу 1>"
APP_SECRET="<App Secret — у App Dashboard → Settings → Basic, треба натиснути Show>"
SHORT_TOKEN="<токен з 4.1>"

curl -G "https://graph.facebook.com/v21.0/oauth/access_token" \
  -d "grant_type=fb_exchange_token" \
  -d "client_id=${APP_ID}" \
  -d "client_secret=${APP_SECRET}" \
  -d "fb_exchange_token=${SHORT_TOKEN}"
```

Відповідь:
```json
{"access_token":"EAAxxxxxxx...", "token_type":"bearer", "expires_in":5183999}
```
Це довгоживучий **User Token** (60 днів). Запиши.

### 4.3. Отримати Page Access Token (живе вічно)

```bash
USER_LONG_TOKEN="<щойно отриманий>"
FB_PAGE_ID="<з етапу 2>"

curl -G "https://graph.facebook.com/v21.0/${FB_PAGE_ID}" \
  -d "fields=access_token" \
  -d "access_token=${USER_LONG_TOKEN}"
```

Відповідь:
```json
{"access_token":"EAAxxxxxxx_PAGE...", "id":"123456789"}
```

Цей **Page Access Token** живе **поки існує User Token** (тобто 60 днів і автопродовжується якщо ти не змінюєш пароль). Це **`IG_PAGE_TOKEN`** — головний токен для нашої CRM.

---

## Етап 5. Підписка Page на Instagram webhook

```bash
PAGE_TOKEN="<з 4.3>"
FB_PAGE_ID="<з етапу 2>"

curl -X POST "https://graph.facebook.com/v21.0/${FB_PAGE_ID}/subscribed_apps" \
  -d "subscribed_fields=messages,messaging_postbacks,message_reactions" \
  -d "access_token=${PAGE_TOKEN}"
```

Відповідь: `{"success": true}`. Якщо так — Page тепер відсилає DM події у наш webhook.

---

## Етап 6. Що передати Claude

Створи **новий чат з Claude** і скинь усі ці значення (краще через окремий приватний канал, не в публічний repo!):

```
IG_APP_ID = <етап 1>
IG_APP_SECRET = <етап 4.2>
IG_USER_ID = <етап 2>
FB_PAGE_ID = <етап 2>
IG_WEBHOOK_VERIFY_TOKEN = <етап 3.2>
IG_PAGE_TOKEN = <етап 4.3, довгоживучий>
USER_LONG_TOKEN = <етап 4.2, на випадок якщо треба буде Page Token регенерувати>
```

**ВАЖЛИВО:** ці токени дають повний контроль над Page і Instagram. Не комітити в git, не вкидати в GPT/публічні чати. Claude збереже у `/opt/kizuna-crm/.env` з правами 600.

---

## Етап 7. Подача на App Review (після того як код готовий)

Цей крок робиться **після того як Claude напише і задеплоїть код**, бо Meta перевіряє реальну роботу.

1. App Dashboard → **App Review** → **Submissions**
2. Запросити кожен permission з 3.1 в **Advanced Access** з:
   - **Use Case Description**: підготує Claude (стандартний текст про використання DM в CRM ветклініки)
   - **Demo Video**: 1-2 хвилинне відео як ти заходиш в CRM, бачиш DM від клієнта, відповідаєш, клієнт отримує
   - **Test Credentials**: тестовий логін у CRM (`claude / code@1233333@@##` з memory)
   - **Privacy Policy URL**: треба буде створити сторінку на kizuna.com.ua/privacy/ — Claude згенерує текст
3. Submit. Чекати 3-7 днів. Може запросити доуточнення.

Поки в Development Mode — інтеграція працює тільки з акаунтами, доданими в **Roles → Test Users / Roles → Admins**. Тобто можна вже зараз тестувати на власному IG.

---

## Чек-ліст (для тебе)

- [ ] App створено, App ID записано
- [ ] Instagram product підключено, IG_USER_ID + FB_PAGE_ID записано
- [ ] Permissions запитано
- [ ] Webhook URL і Verify Token налаштовано (Verify пройде після того як Claude задеплоїть)
- [ ] User Token згенеровано через Explorer
- [ ] User Token обміняно на довгоживучий
- [ ] Page Token отримано
- [ ] Page підписано на Instagram webhook (відповідь `{"success":true}`)
- [ ] Усі 7 значень з етапу 6 зібрані в одному місці і передані Claude
- [ ] (Після коду) App Review submited

---

## Якщо щось пішло не так

| Проблема | Рішення |
|---|---|
| «You don't have permission to access this app» | Перевірити що Business Account вибраний той самий що містить Page |
| Permissions не дають Advanced Access | Спочатку натисни «Submit for Review» — там опис use-case |
| Webhook Verify Failed | Це нормально поки Claude не задеплоїть handler. Передай йому Verify Token, він зробить і скаже коли Verify натискати |
| User Token expired через 1 годину | Це короткий токен. Переходь до етапу 4.2 — обмін на довгий |
| `(#100) The parameter pretty is required` | Додай `&pretty=0` в URL або проігноруй (косметичне) |
| Page Token не видається на 4.3 | Перевір що User Token має `pages_show_list` permission |

Питання — пиши Claude.
