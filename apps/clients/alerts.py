"""Смуга тривог картки пацієнта (перебудова 31.10.2026, крок 2 —
docs/patient-card/OCINKA-2026-10-31.md). Чисті функції: правила перевіряються
тестом без бази (apps/clients/tests/test_alerts.py).

Рівні: danger (червоне) — діяти зараз; warning (бурштин) — скоро або варто
глянути; info (синє) — стан. Золото в картці — колір дії, тому тривоги ним не
малюємо."""
from datetime import timedelta

SOON_DAYS = 30
_ORDER = {'danger': 0, 'warning': 1, 'info': 2}


def vaccine_alerts(vaccines, today, soon_days=SOON_DAYS):
    """Лише за ОСТАННІМ записом кожної назви: торішнє щеплення, яке вже повторили,
    не повинно кричати «прострочено»."""
    latest = {}
    for v in sorted(vaccines, key=lambda x: (x.date is not None, x.date), reverse=True):
        key = (v.name or '').strip().lower()
        if key and key not in latest:
            latest[key] = v
    out = []
    for v in latest.values():
        nd = v.next_date
        if not nd:
            continue
        if nd < today:
            out.append({'level': 'danger', 'text': f'Прострочено щеплення: {v.name} (з {nd:%d.%m.%Y})'})
        elif nd <= today + timedelta(days=soon_days):
            out.append({'level': 'warning', 'text': f'Щеплення {v.name} — до {nd:%d.%m.%Y}'})
    return out


def _kg(x):
    return format(float(x), 'g').replace('.', ',')


def weight_alert(weights):
    """weights — за датою від старих до нових. Ті самі пороги, що й /weight-alert/."""
    if len(weights) < 2:
        return None
    prev, cur = weights[-2].weight, weights[-1].weight
    if not prev or float(prev) <= 0:
        return None
    pct = abs(float(cur - prev) / float(prev) * 100)
    if pct <= 15:
        return None
    sign = '+' if cur > prev else '−'
    return {'level': 'warning' if pct < 25 else 'danger',
            'text': f'Вага {sign}{pct:.0f}% ({_kg(prev)} → {_kg(cur)} кг)'}


def invoice_alert(invoices):
    drafts = [i for i in invoices if getattr(i, 'status', '') == 'draft']
    if not drafts:
        return None
    total = sum((i.total or 0) for i in drafts)
    return {'level': 'warning', 'text': f'Неоплачені рахунки: {len(drafts)} на {_kg(total)} ₴',
            'pk': drafts[0].pk}


def patient_alerts(patient, vaccines, weights, invoices, today):
    from django.urls import reverse
    from .models import Hospitalization
    from .models_health import HealthCheck

    alerts = list(vaccine_alerts(vaccines, today))
    w = weight_alert(weights)
    if w:
        alerts.append(w)
    # картка показує лише оплачені рахунки — чернетки беремо окремим запитом
    from apps.billing.models import Invoice
    drafts = list(Invoice._base_manager.filter(patient=patient, status='draft').only('pk', 'status', 'total'))
    inv = invoice_alert(list(invoices) + drafts)
    if inv:
        inv['url'] = reverse('billing:detail', args=[inv.pop('pk')])
        alerts.append(inv)
    hosp = Hospitalization._base_manager.filter(patient=patient, status='active').order_by('-admitted_at').first()
    if hosp:
        alerts.append({'level': 'info', 'text': f'У стаціонарі з {hosp.admitted_at:%d.%m.%Y}',
                       'url': reverse('clients:hospitalization_list')})
    hc = (HealthCheck._base_manager.filter(patient=patient, status='concern',
                                           sent_at__date__gte=today - timedelta(days=30))
          .order_by('-sent_at').first())
    if hc:
        alerts.append({'level': 'danger', 'text': f'Власник повідомив про проблему (опитування {hc.sent_at:%d.%m})',
                       'url': reverse('clients:health_diary') + f'?patient={patient.pk}'})
    alerts.sort(key=lambda a: _ORDER.get(a['level'], 9))
    return alerts
