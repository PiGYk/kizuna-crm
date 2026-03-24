from datetime import date, timedelta, datetime
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
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
        .filter(starts_at__date__gte=days[0], starts_at__date__lte=days[-1])
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

    return render(request, 'appointments/calendar.html', {
        'days': days,
        'slots': slots,
        'appts_by_day': appts_by_day,
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
    t = request.GET.get('time')
    if d and t:
        try:
            initial['starts_at'] = datetime.fromisoformat(f"{d}T{t}")
        except ValueError:
            pass
    initial.setdefault('doctor', request.user)

    form = AppointmentForm(request.POST or None, initial=initial)
    if request.method == 'POST' and form.is_valid():
        appt = form.save(commit=False)
        appt.created_by = request.user
        appt.save()
        form.save_m2m()
        back = request.GET.get('back') or f"/appointments/?date={appt.starts_at.date().isoformat()}"
        return redirect(back)

    return render(request, 'appointments/form.html', {'form': form, 'title': 'Новий запис'})


# ── Редагувати ───────────────────────────────────────────────────────────────

@login_required
def appointment_edit(request, pk):
    appt = get_object_or_404(Appointment, pk=pk)
    form = AppointmentForm(request.POST or None, instance=appt)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect(f"/appointments/?date={form.instance.starts_at.date().isoformat()}")
    return render(request, 'appointments/form.html', {
        'form': form, 'appt': appt, 'title': 'Редагувати запис'
    })


# ── Змінити статус (HTMX кнопка) ────────────────────────────────────────────

@login_required
@require_POST
def appointment_status(request, pk):
    appt = get_object_or_404(Appointment, pk=pk)
    new_status = request.POST.get('status')
    if new_status in dict(Appointment.Status.choices):
        appt.status = new_status
        appt.save(update_fields=['status'])
    return redirect(f"/appointments/?date={appt.starts_at.date().isoformat()}")


# ── Видалити ─────────────────────────────────────────────────────────────────

@login_required
@require_POST
def appointment_delete(request, pk):
    appt = get_object_or_404(Appointment, pk=pk)
    d = appt.starts_at.date().isoformat()
    appt.delete()
    return redirect(f"/appointments/?date={d}")


# ── HTMX: пацієнти клієнта (динамічно при виборі клієнта у формі) ───────────

@login_required
def patient_options(request):
    client_id = request.GET.get('client') or request.GET.get('client_id')
    patients = []
    if client_id:
        from apps.clients.models import Patient
        patients = Patient.objects.filter(client_id=client_id)
    return render(request, 'appointments/partials/patient_options.html', {'patients': patients})
