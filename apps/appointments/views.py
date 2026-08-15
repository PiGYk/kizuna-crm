import json
from datetime import date, timedelta, datetime
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import AppointmentForm
from .models import Appointment
from apps.tg.utils import is_mobile


def _week_days(ref: date):
    """Повертає [понеділок .. неділя] для тижня що містить ref."""
    monday = ref - timedelta(days=ref.weekday())
    return [monday + timedelta(days=i) for i in range(7)]


def _day_slots(day: date):
    """Слоти 08:00–20:00 по 30 хв."""
    slots = []
    t = datetime.combine(day, datetime.min.time()).replace(hour=8)
    end = t.replace(hour=20)
    while t < end:
        slots.append(t.time())
        t += timedelta(minutes=30)
    return slots


# Календарне вікно: година старту, година кінця (включно), pixel-per-30min.
CAL_START_HOUR = 8
CAL_END_HOUR = 20  # неактивний слот після 20:00
CAL_SLOT_PX = 32   # висота одного 30-хв слоту в пікселях


def _layout_day_appts(appts):
    """Collision-aware layout: визначає column + cols для кожного запису.

    Алгоритм:
    1. Сортуємо за start_min.
    2. Йдемо по списку, тримаємо "active" — список записів що ще не закінчились
       на момент початку поточного.
    3. Шукаємо вільну колонку (де серед active ніхто її не займає).
    4. Якщо нема — додаємо нову, збільшуємо cols групи.
    5. Коли поточний кластер закінчився (active пустий) — фіксуємо `cols`
       для всіх його учасників.

    Кожен запис отримує атрибути:
      start_min — хв від CAL_START_HOUR (відносна координата)
      dur_min   — тривалість у хв
      column    — індекс колонки (0..N-1)
      cols      — скільки колонок у його кластері
    """
    items = []
    for a in appts:
        starts_local = timezone.localtime(a.starts_at)
        if starts_local.date() != starts_local.date():  # paranoia
            continue
        start_min = (starts_local.hour - CAL_START_HOUR) * 60 + starts_local.minute
        if start_min < 0:
            start_min = 0
        max_min = (CAL_END_HOUR - CAL_START_HOUR) * 60
        if start_min >= max_min:
            continue
        dur = max(int(a.duration or 30), 15)
        items.append({
            'appt': a,
            'start_min': start_min,
            'end_min': start_min + dur,
            'dur_min': dur,
        })

    items.sort(key=lambda x: (x['start_min'], x['end_min']))

    cluster = []          # active list
    cluster_cols = 0      # max cols у поточному кластері
    cluster_members = []  # всі items кластера (для фікс cols)

    for it in items:
        # видаляємо з кластера ті, що закінчились до старту поточного
        cluster = [c for c in cluster if c['end_min'] > it['start_min']]
        if not cluster:
            # закриваємо попередній кластер
            for m in cluster_members:
                m['cols'] = cluster_cols or 1
            cluster_members = []
            cluster_cols = 0

        used_cols = {c['column'] for c in cluster}
        col = 0
        while col in used_cols:
            col += 1
        it['column'] = col
        cluster.append(it)
        cluster_members.append(it)
        cluster_cols = max(cluster_cols, col + 1)

    # закриваємо останній кластер
    for m in cluster_members:
        m['cols'] = cluster_cols or 1

    return items


# ── Календар (день, моб) ─────────────────────────────────────────────────────

@login_required
def calendar_day_view(request):
    """Денний вигляд для моб: вертикальний список записів на одну дату."""
    try:
        ref = date.fromisoformat(request.GET.get('date', ''))
    except (ValueError, TypeError):
        ref = timezone.localdate()

    prev_day = (ref - timedelta(days=1)).isoformat()
    next_day = (ref + timedelta(days=1)).isoformat()
    today = timezone.localdate()

    appts = list(
        Appointment.objects
        .filter(organization=request.organization, starts_at__date=ref)
        .select_related('client', 'patient', 'doctor')
        .prefetch_related('services')
        .order_by('starts_at')
    )

    # Якщо порожньо — знайти найближчі майбутні дні з записами (для empty state)
    nearest_with_appts = []
    if not appts:
        from collections import Counter
        future_qs = (
            Appointment.objects
            .filter(organization=request.organization, starts_at__date__gt=ref)
            .exclude(status__in=['cancelled', 'no_show'])
            .order_by('starts_at')[:50]
        )
        # групуємо по даті
        by_date = Counter()
        for a in future_qs:
            by_date[timezone.localtime(a.starts_at).date()] += 1
        nearest_with_appts = [
            {'date': d, 'count': c}
            for d, c in sorted(by_date.items())[:3]
        ]

    # 7-day strip (3 before + ref + 3 after) для mobile date-picker
    date_strip = [ref + timedelta(days=i) for i in range(-3, 4)]

    template = 'appointments/calendar_day_mobile.html' if is_mobile(request) else 'appointments/calendar_day.html'
    return render(request, template, {
        'ref': ref,
        'today': today,
        'prev_day': prev_day,
        'next_day': next_day,
        'appts': appts,
        'nearest_with_appts': nearest_with_appts,
        'date_strip': date_strip,
    })


# ── Календар (тиждень) ───────────────────────────────────────────────────────

@login_required
def calendar_view(request):
    # яку дату показувати
    try:
        ref = date.fromisoformat(request.GET.get('date', ''))
    except (ValueError, TypeError):
        ref = timezone.localdate()

    # На мобайлі тижнева сітка не читається — серверний редирект на день.
    if is_mobile(request):
        return redirect(f"/appointments/day/?date={ref.isoformat()}")

    days = _week_days(ref)
    prev_week = (days[0] - timedelta(days=7)).isoformat()
    next_week = (days[0] + timedelta(days=7)).isoformat()
    today = timezone.localdate()

    # всі записи на цей тиждень
    appts = (
        Appointment.objects
        .filter(
            organization=request.organization,
            starts_at__date__gte=days[0],
            starts_at__date__lte=days[-1],
        )
        .select_related('client', 'patient', 'doctor')
        .prefetch_related('services')
        .exclude(status='cancelled')
    )
    # групуємо по даті + застосовуємо collision-layout
    raw_by_day = {d: [] for d in days}
    for a in appts:
        d = timezone.localtime(a.starts_at).date()
        if d in raw_by_day:
            raw_by_day[d].append(a)

    layout_by_day = {d: _layout_day_appts(raw_by_day[d]) for d in days}
    has_appointments = any(layout_by_day.values())

    # Години для time-axis (08:00 ... 19:00 — 12 годинних позначок)
    hour_labels = list(range(CAL_START_HOUR, CAL_END_HOUR))

    return render(request, 'appointments/calendar.html', {
        'days': days,
        'hour_labels': hour_labels,
        'cal_start_hour': CAL_START_HOUR,
        'cal_end_hour': CAL_END_HOUR,
        'cal_slot_px': CAL_SLOT_PX,
        'cal_total_px': (CAL_END_HOUR - CAL_START_HOUR) * 2 * CAL_SLOT_PX,
        'layout_by_day': layout_by_day,
        'has_appointments': has_appointments,
        'prev_week': prev_week,
        'next_week': next_week,
        'today': today,
        'ref': ref,
    })


# ── Створити запис ───────────────────────────────────────────────────────────

@login_required
def appointment_create(request):
    initial = {}
    # ?date=2026-03-22&time=10:30 — якщо клікнули по слоту
    d = request.GET.get('date')
    t = request.GET.get('time', '08:00')
    if d:
        try:
            initial['starts_at'] = datetime.fromisoformat(f"{d}T{t}")
        except ValueError:
            pass
    org = request.organization
    default_doc = org.get_default_doctor(request.user) if org else request.user
    initial.setdefault('doctor', default_doc)

    form = AppointmentForm(request.POST or None, initial=initial, org=org)
    if request.method == 'POST' and form.is_valid():
        appt = form.save(commit=False)
        appt.created_by = request.user
        appt.organization = request.organization
        appt.save()
        form.save_m2m()
        messages.success(request, 'Запис створено.')
        back = request.GET.get('back')
        if back and url_has_allowed_host_and_scheme(
            back, allowed_hosts={request.get_host()}, require_https=request.is_secure()
        ):
            return redirect(back)
        return redirect(f"/appointments/?date={appt.starts_at.date().isoformat()}")

    template = 'appointments/form_mobile.html' if is_mobile(request) else 'appointments/form.html'
    return render(request, template, {'form': form, 'title': 'Новий запис'})


# ── Редагувати ───────────────────────────────────────────────────────────────

@login_required
def appointment_edit(request, pk):
    appt = get_object_or_404(Appointment, pk=pk, organization=request.organization)
    org = request.organization
    form = AppointmentForm(request.POST or None, instance=appt, org=org)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Запис оновлено.')
        return redirect(f"/appointments/?date={form.instance.starts_at.date().isoformat()}")
    template = 'appointments/form_mobile.html' if is_mobile(request) else 'appointments/form.html'
    return render(request, template, {
        'form': form, 'appt': appt, 'title': 'Редагувати запис'
    })


# ── Змінити статус (HTMX кнопка) ────────────────────────────────────────────

@login_required
@require_POST
def appointment_status(request, pk):
    appt = get_object_or_404(Appointment, pk=pk, organization=request.organization)
    new_status = request.POST.get('status')
    if new_status in dict(Appointment.Status.choices):
        appt.status = new_status
        appt.save(update_fields=['status'])
        messages.success(request, f'Статус змінено на «{appt.get_status_display()}».')
    # Куди повертати: явний ?next=, або референс, або дефолт-тижневий
    nxt = request.POST.get('next') or request.GET.get('next')
    if nxt and url_has_allowed_host_and_scheme(
        nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(nxt)
    return redirect(f"/appointments/?date={appt.starts_at.date().isoformat()}")


# ── Видалити ─────────────────────────────────────────────────────────────────

@login_required
@require_POST
def appointment_delete(request, pk):
    appt = get_object_or_404(Appointment, pk=pk, organization=request.organization)
    d = appt.starts_at.date().isoformat()
    appt.delete()
    messages.success(request, 'Запис видалено.')
    nxt = request.POST.get('next') or request.GET.get('next')
    if nxt and url_has_allowed_host_and_scheme(
        nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(nxt)
    return redirect(f"/appointments/?date={d}")


# ── HTMX: пацієнти клієнта (динамічно при виборі клієнта у формі) ───────────

@login_required
def patient_options(request):
    client_id = request.GET.get('client') or request.GET.get('client_id')
    patients = []
    if client_id:
        from apps.clients.models import Patient
        patients = Patient.objects.filter(
            client_id=client_id,
            client__organization=request.organization,
            is_archived=False,
        )
    return render(request, 'appointments/partials/patient_options.html', {'patients': patients})


# ── Пошук пацієнтів (autocomplete на сторінці запису) ──────────────────────

_SPECIES_EMOJI = {
    'dog': '🐶', 'cat': '🐱', 'rabbit': '🐰', 'bird': '🐦',
    'hamster': '🐹', 'guinea_pig': '🐹', 'ferret': '🦨',
    'chinchilla': '🐭', 'rat': '🐭', 'turtle': '🐢',
    'reptile': '🦎', 'fish': '🐟', 'hedgehog': '🦔', 'other': '🐾',
}


@login_required
def patient_search(request):
    """JSON-search для autocomplete у appointment form.

    GET /appointments/patient-search/?q=… → {results: [...]}
    Шукає по name + breed, повертає фото + інфо про власника.
    """
    from django.db.models import Q
    from apps.clients.models import Patient

    q = request.GET.get('q', '').strip()
    client_id = request.GET.get('client_id', '').strip()
    results = []
    if q and len(q) >= 1:
        qs = (
            Patient._meta.base_manager
            .select_related('client')
            .filter(
                client__organization=request.organization,
                client__is_archived=False,
                is_archived=False,
            )
            .filter(Q(name__icontains=q) | Q(breed__icontains=q))
            .order_by('name')[:15]
        )
        if client_id and client_id.isdigit():
            qs = qs.filter(client_id=int(client_id))
        for p in qs:
            results.append({
                'id': p.pk,
                'name': p.name,
                'species_emoji': _SPECIES_EMOJI.get(p.species, '🐾'),
                'species_label': p.get_species_display(),
                'breed': p.breed or '',
                'photo': p.photo.url if p.photo else None,
                'client_id': p.client.pk,
                'client_label': str(p.client),
                'client_phone': p.client.phone or '',
            })
    return JsonResponse({'results': results})


# ── Пошук клієнтів (autocomplete) ──────────────────────────────────────────

@login_required
def client_search(request):
    """JSON-пошук клієнтів для autocomplete на appointment form.

    GET /appointments/client-search/?q=… → {results: [...]}
    Шукає по прізвищу/імені/телефону.
    """
    from django.db.models import Q
    from apps.clients.models import Client

    q = request.GET.get('q', '').strip()
    results = []
    if q and len(q) >= 1:
        qs = (
            Client._meta.base_manager
            .filter(organization=request.organization, is_archived=False)
            .filter(
                Q(last_name__icontains=q) |
                Q(first_name__icontains=q) |
                Q(phone__icontains=q)
            )
            .order_by('last_name', 'first_name')[:15]
        )
        for c in qs:
            full = f'{c.last_name} {c.first_name}'.strip() or '—'
            results.append({
                'id': c.pk,
                'label': full,
                'phone': c.phone or '',
                'patient_count': c.patients.count(),
            })
    return JsonResponse({'results': results})


# ── Швидка реєстрація клієнта+тваринки прямо зі сторінки запису ─────────────

@login_required
def client_by_phone(request):
    """GET /appointments/client-by-phone/?phone=… → JSON {exists, client?}.

    Шукає клієнта за останніми 9 цифрами телефону (без країнного коду).
    """
    from .forms_quick import normalize_phone
    from apps.clients.models import Client

    phone_raw = request.GET.get('phone', '').strip()
    digits = normalize_phone(phone_raw)
    if len(digits) < 5:
        return JsonResponse({'exists': False})

    tail = digits[-9:]
    existing = Client.objects.filter(
        organization=request.organization, phone__regex=fr'.*{tail}$',
    ).first()
    if not existing:
        return JsonResponse({'exists': False})

    return JsonResponse({
        'exists': True,
        'client': {
            'id': existing.pk,
            'label': f'{existing} · {existing.phone}',
        },
    })


@login_required
@require_POST
def quick_create_client_patient(request):
    """POST /appointments/quick-client/ → створює Client (+ Patient опційно).

    Тіло form-data: first_name, last_name, phone, email, discount_percent +
                    (опц.) pet_name, species, breed, sex, date_of_birth.
    Якщо pet_name або species пустий — patient НЕ створюється.
    Дублі телефону блокуються у QuickClientForm.clean().
    """
    from .forms_quick import QuickClientForm, QuickPatientForm

    org = request.organization
    client_form = QuickClientForm(request.POST)
    client_form._org = org

    # Збираємо patient-поля з префіксом `pet_*` (щоб не конфліктувати з ClientForm).
    pet_data = {
        'name': request.POST.get('pet_name', '').strip(),
        'species': request.POST.get('pet_species', '').strip(),
        'breed': request.POST.get('pet_breed', '').strip(),
        'sex': request.POST.get('pet_sex', '').strip(),
        'date_of_birth': request.POST.get('pet_date_of_birth', '').strip() or None,
    }
    has_pet = bool(pet_data['name'] and pet_data['species'])
    patient_form = QuickPatientForm(pet_data) if has_pet else None

    errors = {}
    if not client_form.is_valid():
        errors.update({f'client_{k}': v for k, v in client_form.errors.items()})
    if patient_form and not patient_form.is_valid():
        errors.update({f'pet_{k}': v for k, v in patient_form.errors.items()})

    if errors:
        return JsonResponse({'ok': False, 'errors': errors}, status=400)

    client = client_form.save(commit=False)
    client.organization = org
    client.save()

    patient = None
    if patient_form:
        patient = patient_form.save(commit=False)
        patient.client = client
        patient.save()

    return JsonResponse({
        'ok': True,
        'client': {
            'id': client.pk,
            'label': f'{client} · {client.phone}',
        },
        'patient': (
            {'id': patient.pk, 'label': f'{patient.name} ({patient.get_species_display()})'}
            if patient else None
        ),
    })


# ── API: перемістити запис (drag & drop) ────────────────────────────────────

@login_required
@require_POST
def appointment_move(request, pk):
    """Змінити дату/час запису через drag & drop."""
    appt = get_object_or_404(Appointment, pk=pk, organization=request.organization)

    try:
        data = json.loads(request.body)
        new_date = date.fromisoformat(data['date'])
        hour, minute = map(int, data['time'].split(':'))
    except (json.JSONDecodeError, KeyError, ValueError):
        return JsonResponse({'error': 'Invalid data'}, status=400)

    # Зберегти тривалість, змінити тільки час
    new_dt = datetime(new_date.year, new_date.month, new_date.day, hour, minute)
    new_starts_at = timezone.make_aware(new_dt)

    # Перевірка конфлікту слотів з тим самим лікарем
    if appt.doctor_id:
        conflict = Appointment.objects.filter(
            organization=request.organization,
            doctor_id=appt.doctor_id,
            starts_at=new_starts_at,
            status__in=['scheduled', 'confirmed'],
        ).exclude(pk=appt.pk).exists()
        if conflict:
            return JsonResponse(
                {'error': f'На {hour:02d}:{minute:02d} вже є запис у цього лікаря'},
                status=409,
            )

    appt.starts_at = new_starts_at
    appt.save(update_fields=['starts_at'])

    return JsonResponse({'ok': True, 'id': appt.pk})
