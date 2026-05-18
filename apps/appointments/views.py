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

    return render(request, 'appointments/calendar_day.html', {
        'ref': ref,
        'today': today,
        'prev_day': prev_day,
        'next_day': next_day,
        'appts': appts,
        'nearest_with_appts': nearest_with_appts,
    })


# ── Календар (тиждень) ───────────────────────────────────────────────────────

@login_required
def calendar_view(request):
    # яку дату показувати
    try:
        ref = date.fromisoformat(request.GET.get('date', ''))
    except (ValueError, TypeError):
        ref = timezone.localdate()

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
    # групуємо по даті
    appts_by_day = {d: [] for d in days}
    for a in appts:
        d = timezone.localtime(a.starts_at).date()
        if d in appts_by_day:
            appts_by_day[d].append(a)

    slots = _day_slots(days[0])

    has_appointments = any(appts_by_day.values())

    return render(request, 'appointments/calendar.html', {
        'days': days,
        'slots': slots,
        'appts_by_day': appts_by_day,
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

    return render(request, 'appointments/form.html', {'form': form, 'title': 'Новий запис'})


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
    return render(request, 'appointments/form.html', {
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
        )
    return render(request, 'appointments/partials/patient_options.html', {'patients': patients})


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
