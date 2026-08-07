# VetCRM — повний аудит багів та помилок (2026-05-18 v2)

**Метод:** 5 паралельних спеціалізованих агентів (ruflo swarm `swarm-1779100834126-zomwi6`, hierarchical-mesh, namespace `vetcrm-audit-2026-05-18-v2`):
security-auditor (sonnet), analyst (sonnet, data-integrity), performance-engineer (sonnet), code-analyzer (sonnet, business-logic), reviewer (haiku, UX).

**Скоп:** `/opt/kizuna-crm/` — 12 apps (accounts, analytics, appointments, billing, clients, clinic, dashboard_builder, finance, inventory, services, tg, utils) + config + templates + scripts.

**Підсумок:**
| Домен | P0 | P1 | P2 |
|---|---|---|---|
| Security | 5 | 12 | 12 |
| Data integrity | 11 | 14 | 9 |
| Performance | 9 | 8 | ~20 (включно з missing indexes) |
| Business logic | 13 | 25 | 20 |
| UX / templates | 0 | 9 | 11 |
| **Разом** | **~38** | **~68** | **~72** |

Після зведення дублів між доменами (одна знахідка часто потрапляє в 2-3 домени): **унікальних P0 — ~28, P1 — ~50, P2 — ~60.**

---

## TOP-10 НАЙКРИТИЧНІШИХ (виправляти СЬОГОДНІ-ЗАВТРА)

| # | Назва | Файл | Симптом |
|---|---|---|---|
| 1 | **Celery tasks broken** через OrgManager fail-closed без `set_current_org` | `apps/clients/tasks.py`, `apps/tg/broadcast_tasks.py` | Vaccine/appointment reminders НЕ розсилаються; broadcast мовчки повертає `sent=0`; no-show ростe. |
| 2 | **TG booking ламає час 10:30→10:00** через `split(':')` | `apps/tg/views.py:1298-1305` | КОЖЕН клієнт що записується через бота отримує неправильний час. |
| 3 | **Cross-tenant media leak** (старі шляхи `patients/`, `tg_media/`, `analyses/`) | `apps/clinic/media_serve.py:31-44` | Будь-який залогований юзер GET'ом отримує фото пацієнтів іншої клініки. |
| 4 | **Cross-tenant Product у billing** (`add_line`, `_writeoff_stock` без org filter) | `apps/billing/views.py:189,221,706` | Через DevTools можна списати чужий склад. |
| 5 | **Cross-tenant фінанси/аналітика** (`calculate_balances`, `analytics_data`, `report_data` ігнорують org) | `apps/finance/models.py:62-90`, `apps/analytics/views.py:62-96`, `apps/finance/views.py:254-310` | Баланс/виручка показуються через ВСІ клініки. |
| 6 | **Brute-force на /login/** без захисту | `apps/accounts/urls.py:9` | django-axes не встановлений, rate-limit лише на /register/. |
| 7 | **payroll_calculate без admin check** | `apps/accounts/views_payroll.py:103-271` | Будь-який doctor бачить/створює/виплачує зарплати всіх. |
| 8 | **WayForPay callback без idempotency** | `apps/clinic/views.py:266-323` | Дубль callback продовжує trial двічі (+60 днів за 1 платіж). |
| 9 | **close_checkbox_shift щовечора крах** (виклик без `org`) | `apps/billing/management/commands/close_checkbox_shift.py:10` | Зміна Checkbox не закривається → штрафи ДПС. |
| 10 | **Списання при недостатньому залишку** мовчки робить мінус | `apps/billing/views.py:716-741` | Склад йде у мінус, юзер не бачить warning. |

---

# ФАЗА 0 — критичні фікси (1-2 дні, blocking для SaaS-роботи)

## P0-S — Security

### [ ] P0-S1: Cross-tenant media leak
- `apps/clinic/media_serve.py:31-44` — заборонити доступ до всього що НЕ з префіксом `org_{pk}/`
- Migration: перенести `media/patients/*` → `media/org_{client.organization_id}/patients/*`, оновити `Patient.photo`, `PatientDocument.file`, `PatientAnalysis.file`, `HealthCheck.response_photo` upload_to callable
- Аналогічно для `tg_media/`, `analyses/`, `invoices/`, `expenses/`, `health_checks/`, `org_logos/`
- Перевірити nginx config: `/x-media/` має бути `internal;` без публічного `location /media/`

### [ ] P0-S2: Brute-force protection на login
- Додати `django-axes` у `requirements.txt`
- `INSTALLED_APPS += ['axes']`, `MIDDLEWARE += ['axes.middleware.AxesMiddleware']`, `AUTHENTICATION_BACKENDS = ['axes.backends.AxesBackend', 'django.contrib.auth.backends.ModelBackend']`
- `AXES_FAILURE_LIMIT=5, AXES_COOLOFF_TIME=1, AXES_LOCKOUT_PARAMETERS=['ip_address', 'username']`

### [ ] P0-S3: payroll_calculate без admin check
- `apps/accounts/views_payroll.py` — додати `@admin_required` декоратор на: `payroll_list`, `payroll_calculate`, `payroll_approve`, `payroll_pay`, `payroll_detail`, `payroll_delete`, `payroll_export`
- `payroll_view` у analytics (`apps/analytics/views.py:266`) — теж `@admin_required`

### [ ] P0-S4: WayForPay callback idempotency
- Створити модель `PaymentTransaction(order_ref UNIQUE, transaction_status, raw_payload JSON, processed_at)`
- `apps/clinic/views.py:266-323` — обернути в `get_or_create(order_ref=...)`, якщо існує `Approved` → повернути accept_response БЕЗ продовження trial
- Fix також: на `Organization.DoesNotExist` → status=500 замість accept_response (P1-S8)

### [ ] P0-S5: TenantMiddleware довіра до субдомену
- `config/middleware.py:71-89` — після `_org_from_subdomain()` валідувати: якщо `request.user.is_authenticated` і `user.organization_id != subdomain_org.pk` і не superuser → `logout()` + redirect login
- Покрити тестом cross-subdomain session

## P0-D — Data integrity

### [ ] P0-D1: Celery tasks broken (OrgManager fail-closed)
- Створити helper `apps/utils/celery_org.py`:
  ```python
  from contextlib import contextmanager
  from apps.clinic.tenant import set_current_org, clear_current_org
  @contextmanager
  def org_context(org):
      set_current_org(org)
      try: yield
      finally: clear_current_org()
  ```
- Обернути ВСІ ORM-блоки в `apps/clients/tasks.py` (рядки 23, 130, 145, 174, 220, 232, 279, 286, 289, 330, 336, 343)
- Обернути broadcast tasks: `apps/tg/broadcast_tasks.py:18, 24, 73, 77, 88`
- АБО (краще) — замінити `Model.objects.filter(organization=org)` на `Model._base_manager.filter(organization=org)` у task'ах

### [ ] P0-D2: StockMovement.save() non-atomic
- `apps/inventory/models.py:138-146` — обернути в `transaction.atomic()`, перенести `Product.objects.update(quantity=F+/-)` ПІСЛЯ `super().save()`
- Management command `apps/inventory/management/commands/audit_stock.py` — порівняти `Sum(StockMovement)` з `Product.quantity` по org

### [ ] P0-D3: confirm_checkbox_payment без @transaction.atomic
- `apps/billing/views.py:581-646` — `@transaction.atomic` декоратор
- Винести HTTP-виклики Checkbox через `transaction.on_commit(lambda: ...)` або 2-фазний паттерн

### [ ] P0-D4: Cross-tenant Product у billing
- `apps/billing/views.py:189,221` (`add_line`) — `get_object_or_404(Product, pk=..., organization=request.organization)`
- `apps/billing/views.py:319` (`toggle_vaccine`) — додати `organization=invoice.organization`
- `apps/billing/views.py:706-709` (`_writeoff_stock`) — `Product.objects.select_for_update().filter(pk__in=..., organization=invoice.organization)`

### [ ] P0-D5: Appointment overlap не перевіряється
- `apps/appointments/forms.py:AppointmentForm.clean()` — перевірити `Appointment.objects.filter(doctor=..., starts_at__range=(start, end)).exclude(pk=self.instance.pk).exists()`
- `apps/appointments/views.py:236-252` (`appointment_move`) — те саме
- `apps/appointments/public_api.py:323-333` — overlap + per-(phone, org) lock на 60с (P2-D7 теж)
- Опційно PG EXCLUDE constraint з tsrange (потребує btree_gist)

### [ ] P0-D7: batch_intake без atomic
- `apps/inventory/views.py:831-886` — `with transaction.atomic():` навколо циклу + per-row savepoint

### [ ] P0-D8: Hard delete клієнтів/пацієнтів
- Додати `is_archived = BooleanField(default=False)`, `archived_at = DateTimeField(null=True)` у `Client`, `Patient`, `Visit`
- `apps/clients/views.py:446-478` — замінити `.delete()` на `is_archived=True, archived_at=now()`
- OrgManager: дефолтно фільтрувати `is_archived=False`
- Окремий view `client_archive_view` для перегляду архіву (admin only)

### [ ] P0-D9: Backup без PITR
- Налаштувати WAL archiving у Postgres + `pgbackrest` або `wal-g`
- Як мінімум — додати pg_dump кожні 4 години у робочий час (поточний `scripts/backup.sh` тільки нічний)

### [ ] P0-D10: close_checkbox_shift крах
- `apps/billing/management/commands/close_checkbox_shift.py:10` — ітерувати `Organization._base_manager.filter(is_active=True).exclude(checkbox_pin='')` і викликати `CheckboxService(org).close_shift()` per-org з try/except

### [ ] P0-D11: TG webhook дублі
- `apps/tg/models.py:76` — `UniqueConstraint(fields=['chat', 'tg_message_id'])`
- `apps/tg/views.py:329-511` — замінити `TelegramMessage.objects.create` на `get_or_create`
- Redis SETNX на `update_id` з TTL 60s як зовнішній дедуп

## P0-B — Business logic

### [ ] P0-B-TG-time: split(':') ламає час
- `apps/tg/views.py:1298-1305` — змінити роздільник callback_data з `:` на `|` або `_`, або декодувати лише перші 3 splits і парсити решту як один токен
- `parts = cb_data.split(':', 3)` → `['book_confirm', '5', '2026-05-18', '10:30']`

### [ ] P0-B-payroll-types: salary в аналітиці = 0 для per_shift/hourly/fixed_percent
- `apps/analytics/views.py:300-307` — додати гілки:
  - `per_shift`: `Shift.objects.filter(user=u, date__range=...).count() * u.salary_per_shift`
  - `hourly`: `Shift.objects.aggregate(Sum('hours')) * u.salary_hourly`
  - `mixed`/`fixed_percent`: `u.salary_fixed + revenue * u.salary_percent / 100`

### [ ] P0-B-shift-hours: Shift.save() не перераховує hours
- `apps/accounts/models_payroll.py:36-45` — прибрати `and not self.hours` з умови

### [ ] P0-B-stock-insufficient: списання без блокування
- `apps/billing/views.py:716-741` — якщо `insufficient` непорожній → `transaction.set_rollback(True)` і `messages.error` з переліком позицій, redirect назад до edit

### [ ] P0-B-DST: naive_dt.replace(tzinfo) у TG booking
- `apps/tg/views.py:1037-1039` — замінити на `timezone.make_aware(naive_dt, ZoneInfo('Europe/Kyiv'))`

### [ ] P0-B-multi-tenant-leak (cross-cutting fix після P0-D і P0-S)
- `apps/finance/models.py:62-90` — `calculate_balances(org)` має використовувати `org` у фільтрах для Invoice/Expense/CashOperation aggregate
- `apps/finance/views.py:22,131,254,264,286` — додати `.filter(organization=request.organization)` явно
- `apps/analytics/views.py:62-96, 221-263` — те саме у `analytics_data`, `services_view`, `top_products`, etc.
- `apps/inventory/views.py:44-74` (`ProductListView`), `46-105` (`product_search`), `546-571` (`reorder_view`), `643-661` (`inventory_settings`) — `.filter(organization=request.organization)`
- `apps/appointments/views.py:47-52, 99-105` (calendar) — додати org filter

### [ ] P0-B-fiscal-cash: cash fiscalize не закриває invoice
- `apps/billing/views.py:543-551` — після `create_cash_receipt` викликати `_writeoff_stock(invoice, user)` і поставити `invoice.status=PAID`

### [ ] P0-B-fiscal-cancel: ERROR fiscal не скасовується
- `apps/billing/views.py:669` — `if fiscal_status in (PENDING, ERROR) and fiscal_receipt_id`

### [ ] P0-B-payroll-advance: нема авансів
- Створити `PayrollPayment(period FK, amount, kind=advance|final, paid_at, created_by)`
- View `payroll_advance` + у `period.calculate()` віднімати попередні payments

### [ ] P0-B-import-decimal: float() для цін
- `apps/inventory/views.py:368-371` — `Decimal(str(_get(row, 'buy_price') or '0'))`

### [ ] P0-B-stocktake-race: інвентаризація без atomic + race
- `apps/inventory/views.py:967-1004` — `@transaction.atomic` + `select_for_update` на Products + hidden version field

## P0-P — Performance (cross-tenant + UX-blocking)

### [ ] P0-P-WeasyPrint-blocking: PDF блокує gunicorn
- `apps/clients/views.py:617` (`patient_medical_card`), `apps/billing/views.py` (`invoice_pdf`) — винести у Celery task з SSE/polling result
- Або задеплоїти `--worker-class gevent` тимчасово

### [ ] P0-P-import-N+1: inventory import_execute 5000+ queries
- `apps/inventory/views.py:329-413` — pre-cache `units = {u.name: u for u in Unit.objects.filter(organization=org)}`, `categories = {c.name: c for c in Category.objects.filter(organization=org)}`, bulk_create нових Product батчами по 100

### [ ] P0-P-PatientDetail-N+1: prefetch_related відсутні
- `apps/clients/views.py:166-190` — додати в context:
  ```python
  ctx['visits'] = self.object.visits.select_related('doctor').prefetch_related('prescriptions').all()
  ctx['invoices'] = self.object.invoices.select_related('doctor').filter(status='paid').prefetch_related('lines__service', 'lines__product').all()
  ctx['ultrasounds'] = self.object.ultrasounds.select_related('doctor').all()
  ctx['health_checks'] = self.object.health_checks.all()
  ctx['documents'] = self.object.documents.all()
  ```

### [ ] P0-P-aggregate-consolidation
- `apps/analytics/views.py:71-86` (`analytics_data`) — 8 окремих `aggregate` → один з conditional `Q(filter=...)`
- `apps/finance/views.py:259-290` (`report_data`) — 11 aggregate → 3-4
- `apps/clinic/views.py:170-184` (`superadmin_dashboard`) — 4 `.count()` → conditional

### [ ] P0-P-profit-data-cold-cache: 124 queries при холодному кеші
- `apps/analytics/views.py:425-477` — один query з `TruncDate` + `annotate(net=Sum-Sum-Sum)`
- АБО Celery prewarm cache щодоби о 04:00

---

# ФАЗА 1 — важливі фікси (1 тиждень)

## P1-S — Security

- [ ] **P1-S6** TG webhook без секрету (apps/tg/views.py:217-235) — `return 503` якщо webhook_secret порожній
- [ ] **P1-S7** visit_pdf `|safe` — замінити на `|linebreaksbr` (templates/clients/visit_pdf.html:109-136)
- [ ] **P1-S9** Email enumeration timing у resend_verification — Celery delay для email
- [ ] **P1-S10** _client_ip без trusted proxy whitelist (`apps/appointments/public_api.py:169-174`, `apps/accounts/views.py:122-126`)
- [ ] **P1-S11** doctor_id у TG booking без org-check (`apps/tg/views.py:1022-1060`)
- [ ] **P1-S12** _get_token fallback на глобальний TELEGRAM_BOT_TOKEN — прибрати fallback
- [ ] **P1-S13** set_webhook без admin check
- [ ] **P1-S14** register без @transaction.atomic — атомізувати + email через Celery
- [ ] **P1-S15** UserUpdateForm дозволяє admin'у деактивувати себе/останнього admin'а — додати валідацію
- [ ] **P1-S17** is_admin() не перевіряє is_active

## P1-D — Data integrity

- [ ] **P1-D1** Invoice без номера per-org — додати `number = CharField` + `UniqueConstraint(organization, number)` + counter з `select_for_update`
- [ ] **P1-D2** Payment модель — окремо для partial/refund/multi-payment
- [ ] **P1-D3** Invoice edit race — `select_for_update` у `pay_invoice` + перерахунок total перед save status=PAID
- [ ] **P1-D4** Audit signals N+1 + skip bulk_* — перейти на django-simple-history або PG trigger
- [ ] **P1-D5** delete_invoice PAID — компенсаційний StockMovement.price повинен дорівнювати списанню
- [ ] **P1-D6** PayrollPeriod.calculate через `_base_manager` для майбутніх CLI/cron
- [ ] **P1-D7** payroll_calculate loop без atomic — обернути + per-user try/except
- [ ] **P1-D8** update_line без валідації від'ємних/extreme — `MinValueValidator(0)`
- [ ] **P1-D9** inventory.import_execute без atomic — savepoint per row
- [ ] **P1-D10** confirm_checkbox_payment стан PENDING без active receipt — перед cancel перевіряти status через get_invoice_status
- [ ] **P1-D12** send_vaccine_reminders sync send_mail блокує цикл — Celery subtask з retry
- [ ] **P1-D14** Broadcast.send time.sleep(0.05) блокує worker — `rate_limit='30/s'` або chunked subtasks

## P1-P — Performance

- [ ] **P1-P-ClientList-activity** Subquery замість JOIN+distinct (`apps/clients/views.py:73-82`)
- [ ] **P1-P-chat_list** Paginator(30) + index `TelegramMessage(chat_id, -id)` (`apps/tg/views.py:1412-1426`)
- [ ] **P1-P-chat_detail-prefetch** Звузити prefetch_related (`apps/tg/views.py:1433-1446`)
- [ ] **P1-P-dashboard-widgets** Batch endpoint `/dashboard/widgets/?keys=...` або per-widget cache 60s
- [ ] **P1-P-appointment-reminders** Bulk update reminder_24h_sent + prefetch tg_chats (`apps/clients/tasks.py:145-165`)
- [ ] **P1-P-send_health_checks** Один query на existing HealthChecks (`apps/clients/tasks.py:286-291`)
- [ ] **P1-P-vaccines_overdue** Згрупувати 4 querysets + paginate all_vaccines (`apps/clients/views.py:552-578`)

## P1-B — Business logic

- [ ] **P1-B1** Password reset — перевірити чи кнопка "Забули пароль?" на login.html
- [ ] **P1-B7** delete PAID invoice price=buy vs списання price=sell — уніфікувати
- [ ] **P1-B8** batch_intake ковтає всі Exception — log + return до юзера
- [ ] **P1-B10** expense_delete/cash_operation_delete явний org filter
- [ ] **P1-B11** patient_create/update/delete явний org через client__organization
- [ ] **P1-B13** _default_work_days хардкод Ср/Чт вихідні (Kizuna-специфічно) — Пн-Сб default
- [ ] **P1-B15** Invoice.calc_total без cap на discount>100 — `min(discount, 100)`
- [ ] **P1-B16** retry_card_fiscalize view для PAID+ERROR
- [ ] **P1-B17** _send_payment_link_tg не нотифікує при ok=False
- [ ] **P1-B18** delete_invoice CANCELLED не повертає товари коли stock_written_off=True
- [ ] **P1-B25** reorder_view/reorder_export без явного org filter
- [ ] **P1-B27** _send_appointment_reminder без TelegramMessage.objects.create — додати в історію
- [ ] **P1-B30** service_create formset без org-check на ServiceComponent.product

## P1-U — UX / templates

- [ ] **P1-U1** HTMX без `hx-indicator` — глобальний spinner у `base.html`
- [ ] **P1-U2** XSS / поламаний confirm() при апострофі — `{{ name|escapejs }}` у `templates/services/form.html:106`, `inventory/settings.html:49,93`, `clients/visit_templates.html:74`
- [ ] **P1-U3** TG bot без HTML escape — `html.escape(text)` перед `parse_mode='HTML'` (`apps/tg/views.py:67,122,155,1215`)
- [ ] **P1-U4** Broadcast textarea без maxlength=4096 + counter (`templates/tg/broadcast_form.html:31-34`)
- [ ] **P1-U5** weight_delete без confirm + ховається на mobile (`templates/clients/patient_detail.html:161`)
- [ ] **P1-U6** Mobile-таблиці overflow-hidden → overflow-x-auto (analytics/payroll, debtors, finance, accounts/users, superadmin/dashboard, finance/cash_operations)
- [ ] **P1-U7** Forms не показують field.errors — створити `_form_field.html` partial
- [ ] **P1-U8** Dead templates: `finance/supplier_*.html`, `dashboard.html`, `dashboard_builder/empty.html` — видалити
- [ ] **P1-U9** FAB ховається на більшості list-сторінок — додати `{% block fab_url %}` у clients/patients/inventory/billing/appointments/finance

---

# ФАЗА 2 — мінорні + index migration (2-3 тижні)

## P2 — Missing indexes (окрема migration `apps/{app}/migrations/00XX_perf_indexes.py`)

```python
# Product
indexes = [
    models.Index(fields=['organization', 'is_active', 'name'], name='product_org_active_name_idx'),
    models.Index(fields=['organization', 'category', 'is_active'], name='product_org_cat_active_idx'),
    models.Index(fields=['organization', 'expiry_date'], name='product_org_expiry_idx'),
]
# StockMovement
indexes = [
    models.Index(fields=['type', 'created_at'], name='stockmv_type_date_idx'),
    models.Index(fields=['product', '-created_at'], name='stockmv_product_date_idx'),
]
# Expense
indexes = [
    models.Index(fields=['organization', '-date'], name='expense_org_date_idx'),
    models.Index(fields=['organization', 'category', '-date'], name='expense_org_cat_date_idx'),
    models.Index(fields=['organization', 'payment_method', '-date'], name='expense_org_pay_idx'),
]
# CashOperation
indexes = [models.Index(fields=['organization', 'type', '-date'], name='cashop_org_type_date_idx')]
# Visit
indexes = [
    models.Index(fields=['patient', '-date'], name='visit_patient_date_idx'),
    models.Index(fields=['doctor', '-date']),
    models.Index(fields=['follow_up_date'], condition=Q(follow_up_date__isnull=False), name='visit_followup_idx'),
]
# Vaccine
indexes = [
    models.Index(fields=['next_date'], condition=Q(next_date__isnull=False), name='vaccine_next_idx'),
    models.Index(fields=['valid_until', 'reminder_sent']),
    models.Index(fields=['patient', '-date']),
]
# TelegramMessage
indexes = [
    models.Index(fields=['chat', '-id'], name='tgmsg_chat_id_idx'),
    models.Index(fields=['chat', 'direction', 'is_read']),
]
# Hospitalization, WeightRecord, Patient, Supplier — analogous
```

**⚠️ ОБОВ'ЯЗКОВО:** backup DB перед застосуванням (попередній досвід whisen 2026-05-09).

## P2 — інше (вибірка топ-15)

- [ ] WhiteNoiseMiddleware у prod (nginx уже serve static) — прибрати
- [ ] pgbouncer додати у docker-compose.prod
- [ ] expense_list/cash_operations без paginate — додати paginator(50)
- [ ] FILE_UPLOAD_MAX_MEMORY_SIZE=10MB, DATA_UPLOAD_MAX_MEMORY_SIZE=5MB у settings/prod.py
- [ ] inventory.session-stored import_rows — переключити на tmp file
- [ ] CHECKBOX_LICENSE_KEY / telegram_bot_token / wayforpay shared у БД plaintext — `django-fernet-fields` для шифрування
- [ ] .env permissions: `chmod 600 /opt/kizuna-crm/.env`
- [ ] nginx /x-media/ перевірити `internal;` + видалити публічний `/media/` location
- [ ] LeadRequest dedup per-(phone, org) 60s
- [ ] Audit `_track_changes` skip FK fields (`_id`) — увімкнути для FK теж
- [ ] HTMX vaccine toggle double-click double-fire (`hx-disable`)
- [ ] Inline `onclick=`/`onchange=` (199 випадків) — поетапно у `static/js/`
- [ ] Email template inline CSS (premailer middleware)
- [ ] `<img>` без alt (17 випадків)
- [ ] HTMX-form send_message без `hx-disable` — double-send

---

# Залежності між фіксами (порядок виконання)

```
Phase 0 → 1 → 2

[P0-D1 Celery org context] BLOCKS [P1-D11/12 reminders]
[P0-D8 soft-delete model] BLOCKS [audit framework changes]
[P0-S1 media migration] BLOCKS [P2-S27 health_checks/org_logos paths]
[P0-S4 PaymentTransaction model] BLOCKS [P1-S8 callback error handling]
[P0-B-multi-tenant org filter] CONFLICTS WITH [pending OrgManager refactor]
   → робити обережно: спочатку явні filter, потім поступово прибирати OrgManager fail-closed
[P2 indexes migration] BLOCKS BY [DB backup + maintenance window]
```

---

# Чек-лист виконання (sprint board)

## Спринт 1 (тиждень 1) — фаза 0
- [ ] Branch: `audit-2026-05-18-fix-p0`
- [ ] BACKUP DB → `/opt/kizuna-crm/backups/before_audit_fix.sql.gz`
- [ ] Phase 0 — security (S1-S5): ~6 годин
- [ ] Phase 0 — data integrity (D1-D11): ~10 годин
- [ ] Phase 0 — business logic (B-TG-time, B-payroll-types, B-stock, B-DST, B-multi-tenant): ~8 годин
- [ ] Phase 0 — performance (WeasyPrint, import N+1, PatientDetail, aggregate, profit cache): ~6 годин
- [ ] Tests: `python manage.py test --keepdb` + manual smoke
- [ ] Deploy → systemd restart kizuna-crm-web kizuna-crm-celery kizuna-crm-celery-beat

## Спринт 2 (тижні 2-3) — фаза 1
- [ ] Branch: `audit-2026-05-18-fix-p1`
- [ ] P1-S (10 items): ~12 годин
- [ ] P1-D (12 items): ~16 годин
- [ ] P1-P (7 items): ~10 годин
- [ ] P1-B (13 items): ~14 годин
- [ ] P1-U (9 items): ~8 годин

## Спринт 3 (тижні 4-6) — фаза 2 + hardening
- [ ] Branch: `audit-2026-05-18-fix-p2`
- [ ] Index migration (з maintenance window 30 хв): ~4 години
- [ ] P2 решта (15 items): ~16 годин
- [ ] CI: bandit + safety check у GitHub Actions
- [ ] Документація: оновити `/opt/kizuna-crm/CLAUDE.md` з посиланням на цей аудит

---

# Регресії з попередніх аудитів (статус)

| Знахідка (audit 2026-04-11 / 2026-05-18 v1) | Статус |
|---|---|
| `is_admin()` bypass | ✅ FIXED |
| `OrgManager` fail-open → fail-closed | ✅ FIXED, але створило P0-D1 (Celery без context) |
| `public_api` leak (cross-tenant) | ✅ FIXED — `?org=<slug>` required |
| `calculate_balances` 8 SUMs | ✅ PARTIALLY (3 aggregate замість 8), але БЕЗ org filter — P0-B-multi-tenant |
| `profit_data` 93 queries | ✅ PARTIALLY (Redis cache 5хв), але cold cache 90+ queries — P0-P-profit-data |
| Org FK indexes | ✅ FIXED для Invoice/Appointment/Expense/CashOperation/Product/StockMovement/TelegramMessage/TelegramChat |
| Password reset | ✅ FIXED |
| Brute-force login | ❌ STILL OPEN (P0-S2) |

---

**Артефакти аудиту:**
- Swarm: `swarm-1779100834126-zomwi6`
- Trajectory: `traj-1779100834941-hc0ohc`
- Memory namespace: `vetcrm-audit-2026-05-18-v2`
- Reports: 5 повних звітів у task output files (security, data integrity, performance, business logic, UX)

**Підготував:** ruflo multi-agent swarm + claude-flow orchestrator, 2026-05-18.
