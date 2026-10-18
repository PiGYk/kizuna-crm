from datetime import date, timedelta, time
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .mixins import admin_required, menu_required


def _staff_label(user):
    """«Катерина С.» — ім'я і перша літера прізвища.

    Самого імені мало: у клініці дві Катерини, і в старому календарі на
    телефоні від обох лишалась одна літера «К».
    """
    first = (user.first_name or '').strip()
    last = (user.last_name or '').strip()
    if first and last:
        return f'{first} {last[0]}.'
    return first or last or user.username


def _day_slots(day_shifts):
    """Розкладає зміни дня по слотах: лікар, до двох асистентів, решта.

    «Асистент» — будь-хто, крім лікаря: у Kizuna асистентка Софія має роль
    адміністратора, і фільтр за роллю assistant її б не побачив. «Решта» — це
    рідкісний другий лікар чи третій асистент: їх показуємо, але панель їх
    не чіпає, щоб збереження не стирало людей мовчки.
    """
    doctor = next((s for s in day_shifts if s.user.role == 'doctor'), None)
    rest = [s for s in day_shifts if s is not doctor]
    assistants = [s for s in rest if s.user.role != 'doctor'][:2]
    others = [s for s in rest if s not in assistants]
    return doctor, assistants, others


def _day_context(d, day_shifts, org, month, today):
    doctor, assistants, others = _day_slots(day_shifts)
    first = doctor or (assistants[0] if assistants else None)
    start = (first.start_time if first and first.start_time else org.work_start)
    end = (first.end_time if first and first.end_time else org.work_end)
    return {
        'date': d,
        'key': d.isoformat(),
        'in_month': d.month == month,
        'is_today': d == today,
        'is_past': d < today,
        'doctor': doctor,
        'assistants': assistants,
        'others': others,
        'empty': not day_shifts,
        'start': start,
        'end': end,
        'custom_time': (start, end) != (org.work_start, org.work_end),
        'doctor_id': doctor.user_id if doctor else '',
        'a1_id': assistants[0].user_id if len(assistants) > 0 else '',
        'a2_id': assistants[1].user_id if len(assistants) > 1 else '',
    }


def _shift_pickers(org):
    """Хто з'являється в меню «Лікар» і «Асистент».

    Тільки живі люди: без імені — службові акаунти (тестовий «claude»). Зверху —
    ті, хто реально виходив на зміни за останні три місяці, щоб не гортати
    власників і звільнених.
    """
    from django.db.models import Count, Q
    from .models import User
    since = date.today() - timedelta(days=90)
    people = (
        User.objects.filter(organization=org, is_active=True)
        .exclude(first_name='', last_name='')
        .annotate(recent=Count('shifts', filter=Q(shifts__date__gte=since)))
        .order_by('-recent', 'first_name', 'last_name')
    )
    from .staff_colors import color_of, ensure_colors

    people = list(people)
    ensure_colors(org, people)   # новенькому — вільний колір, раз і назавжди
    doctors, assistants = [], []
    for u in people:
        item = {'id': u.pk, 'label': _staff_label(u), 'full': u.get_full_name() or u.username,
                'color': color_of(u), 'recent': u.recent}
        (doctors if u.role == 'doctor' else assistants).append(item)
    return doctors, assistants


@menu_required('shifts')
def shift_list(request):
    """Графік роботи — місяць, склад зміни на кожен день.

    Переписано 18.10 (наказ Олега): «незручно і мені, і дівчатам». Було так:
    щоб поставити лікаря й двох асистентів — тричі «+», тричі вибір зі
    спільного списку, тричі час, і перезавантаження після кожного. З жовтня
    графік фактично покинули — заповнено один день із двадцяти. Тепер клік по
    дню відкриває одну панель: лікар, асистент, додатковий асистент, «Зберегти».
    """
    import calendar
    from collections import defaultdict
    from .models_payroll import Shift

    org = request.organization
    today = date.today()
    try:
        year = int(request.GET.get('year', today.year))
        month = int(request.GET.get('month', today.month))
        first_day = date(year, month, 1)
    except (TypeError, ValueError):
        year, month = today.year, today.month
        first_day = date(year, month, 1)
    last_day = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)

    weeks_raw = calendar.Calendar(firstweekday=0).monthdatescalendar(year, month)
    grid_from, grid_to = weeks_raw[0][0], weeks_raw[-1][-1]
    doctors, assistants = _shift_pickers(org)

    by_date = defaultdict(list)
    for s in (Shift.objects.filter(organization=org, date__gte=grid_from, date__lte=grid_to)
              .select_related('user').order_by('date', 'start_time', 'id')):
        by_date[s.date].append(s)

    weeks = [[_day_context(d, by_date.get(d, []), org, month, today) for d in w] for w in weeks_raw]
    days = [day for w in weeks for day in w if day['in_month']]
    # Легенда = ключ до кольорів того, що на екрані: лише люди цього місяця.
    # Порожній місяць — хто виходив за 90 днів, щоб ключ не зникав зовсім.
    seen = set()
    for d in days:
        for sh in ([d['doctor']] if d['doctor'] else []) + d['assistants'] + d['others']:
            seen.add(sh.user_id)
    if seen:
        legend_doctors = [p for p in doctors if p['id'] in seen]
        legend_assistants = [p for p in assistants if p['id'] in seen]
    else:
        legend_doctors = [p for p in doctors if p['recent']] or doctors
        legend_assistants = [p for p in assistants if p['recent']] or assistants
    staff_colors = {str(p['id']): p['color'] for p in doctors + assistants}

    prev_month = first_day - timedelta(days=1)
    next_month = last_day + timedelta(days=1)
    return render(request, 'accounts/shifts.html', {
        'weeks': weeks,
        'days': days,
        'current_month': first_day,
        'year': year,
        'month': month,
        'doctors': doctors,
        'assistants': assistants,
        'legend_doctors': legend_doctors,
        'legend_assistants': legend_assistants,
        'staff_colors': staff_colors,
        'default_start': org.work_start,
        'default_end': org.work_end,
        'can_edit': True,   # правити може кожен, кому графік видно (наказ Олега 18.10)
        'prev_year': prev_month.year,
        'prev_month_num': prev_month.month,
        'next_year': next_month.year,
        'next_month_num': next_month.month,
        'is_current_month': (year, month) == (today.year, today.month),
        'today': today,
        'filled_days': sum(1 for d in days if not d['empty']),
        'weekdays': ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Нд'],
    })


@menu_required('shifts')
@require_POST
def shift_day_save(request):
    """Зберегти склад зміни на день одним натиском.

    Клієнт шле, хто стояв у слотах на момент відкриття панелі (prev_*), і кого
    обрано тепер. Рахуємо множинами: прибраних видаляємо, нових додаємо, тих,
    хто лишився, не чіпаємо — тож перестановка асистентів місцями нікого не
    губить. Людей поза слотами (другий лікар) не чіпаємо взагалі.
    Модель Shift НЕ змінюється: з неї рахується зарплата за зміни.
    Права ті самі, що на перегляд: хто бачить графік, той і править — адмін
    клініки закриває графік ролі в налаштуваннях меню. Хто що змінив,
    пише журнал дій (Shift зареєстровано в apps/clients/apps.py).
    """
    from django.db import transaction
    from django.http import JsonResponse
    from django.template.loader import render_to_string
    from .models import User
    from .models_payroll import Shift

    org = request.organization
    try:
        d = date.fromisoformat(request.POST.get('date', ''))
    except ValueError:
        return JsonResponse({'ok': False, 'error': 'Невірна дата'}, status=400)

    org_users = dict(User.objects.filter(organization=org).values_list('pk', 'is_active'))

    def _uid(name, need_active):
        raw = (request.POST.get(name) or '').strip()
        if not raw.isdigit():
            return None
        pk = int(raw)
        if pk not in org_users or (need_active and not org_users[pk]):
            return None   # чужа клініка або звільнений — ігноруємо
        return pk

    new_set = {u for u in (_uid('doctor', True), _uid('assistant', True), _uid('assistant2', True)) if u}
    prev_set = {u for u in (_uid('prev_doctor', False), _uid('prev_assistant', False), _uid('prev_assistant2', False)) if u}

    def _t(name, fallback):
        try:
            return time.fromisoformat(request.POST.get(name, '')) if request.POST.get(name) else fallback
        except ValueError:
            return fallback
    start_t = _t('start_time', org.work_start)
    end_t = _t('end_time', org.work_end)

    with transaction.atomic():
        removed = Shift.objects.filter(organization=org, date=d, user_id__in=prev_set - new_set).delete()[0]
        for pk in new_set:
            shift, made = Shift.objects.get_or_create(
                organization=org, date=d, user_id=pk,
                defaults={'start_time': start_t, 'end_time': end_t},
            )
            if not made and (shift.start_time, shift.end_time) != (start_t, end_t):
                shift.start_time, shift.end_time = start_t, end_t
                shift.save()   # save(), не update(): перераховує години для зарплати

    day_shifts = list(Shift.objects.filter(organization=org, date=d)
                      .select_related('user').order_by('start_time', 'id'))
    today = date.today()
    day = _day_context(d, day_shifts, org, d.month, today)
    ctx = {'day': day, 'can_edit': True, 'default_start': org.work_start, 'default_end': org.work_end}
    return JsonResponse({
        'ok': True,
        'removed': removed,
        'cell': render_to_string('accounts/_shift_cell.html', ctx, request=request),
        'row': render_to_string('accounts/_shift_row.html', ctx, request=request),
        'state': {
            'doctor': day['doctor_id'], 'a1': day['a1_id'], 'a2': day['a2_id'],
            'start': day['start'].strftime('%H:%M') if day['start'] else '',
            'end': day['end'].strftime('%H:%M') if day['end'] else '',
            'empty': day['empty'],
        },
    })


@admin_required
@require_POST
def shift_toggle(request):
    """HTMX: додати/видалити зміну на конкретну дату для працівника."""
    from .models_payroll import Shift

    org = request.organization
    user_id = request.POST.get('user_id')
    date_str = request.POST.get('date')

    try:
        shift_date = date.fromisoformat(date_str)
    except (ValueError, TypeError):
        return redirect('accounts:shifts')

    shift = Shift.objects.filter(user_id=user_id, date=shift_date, organization=org).first()
    if shift:
        shift.delete()
    else:
        start_time_str = request.POST.get('start_time', '')
        end_time_str = request.POST.get('end_time', '')
        try:
            start_t = time.fromisoformat(start_time_str) if start_time_str else None
            end_t = time.fromisoformat(end_time_str) if end_time_str else None
        except ValueError:
            start_t = end_t = None

        Shift.objects.create(
            user_id=user_id,
            organization=org,
            date=shift_date,
            start_time=start_t,
            end_time=end_t,
        )

    return redirect(request.META.get('HTTP_REFERER', 'accounts:shifts'))



@admin_required
@require_POST
def shift_delete(request, pk):
    from .models_payroll import Shift
    shift = get_object_or_404(Shift, pk=pk, organization=request.organization)
    shift.delete()
    from django.http import JsonResponse
    return JsonResponse({'ok': True})


@admin_required
def payroll_list(request):
    """Список розрахунків зарплат."""
    from .models_payroll import PayrollPeriod

    org = request.organization
    periods = PayrollPeriod.objects.filter(
        organization=org
    ).select_related('user').order_by('-period_end')

    status_filter = request.GET.get('status', '')
    if status_filter in ('draft', 'approved', 'paid'):
        periods = periods.filter(status=status_filter)

    return render(request, 'accounts/payroll_list.html', {
        'payrolls': periods,
        'status_filter': status_filter,
    })


@admin_required
def payroll_calculate(request):
    """Створити розрахунок зарплати за період."""
    from .models import User
    from .models_payroll import PayrollPeriod

    org = request.organization
    staff = User.objects.filter(organization=org, is_active=True).order_by('last_name')

    if request.method == 'POST':
        period_start = request.POST.get('period_start')
        period_end = request.POST.get('period_end')
        user_ids = request.POST.getlist('user_ids') or request.POST.getlist('user_id')

        try:
            p_start = date.fromisoformat(period_start)
            p_end = date.fromisoformat(period_end)
        except (ValueError, TypeError):
            messages.error(request, 'Невірний формат дат.')
            return redirect('accounts:payroll_calculate')

        if p_start > p_end:
            messages.error(request, 'Дата початку не може бути пізніше дати кінця.')
            return redirect('accounts:payroll_calculate')

        # Pre-fetch users та existing periods одним запитом замість N+1.
        users_by_pk = {
            str(u.pk): u
            for u in User.objects.filter(pk__in=user_ids, organization=org)
        }
        existing_user_ids = set(
            PayrollPeriod.objects.filter(
                user_id__in=user_ids,
                period_start=p_start,
                period_end=p_end,
            ).values_list('user_id', flat=True)
        )

        created = 0
        for uid in user_ids:
            user = users_by_pk.get(str(uid))
            if not user:
                continue
            if user.pk in existing_user_ids:
                continue

            period = PayrollPeriod(
                user=user,
                organization=org,
                period_start=p_start,
                period_end=p_end,
            )
            period.calculate()
            period.save()
            created += 1

        if created:
            messages.success(request, f'Розраховано зарплату для {created} працівників.')
        return redirect('accounts:payroll_list')

    # Підказка дат: попередній місяць
    today = date.today()
    if today.month == 1:
        default_start = date(today.year - 1, 12, 1)
        default_end = date(today.year - 1, 12, 31)
    else:
        default_start = date(today.year, today.month - 1, 1)
        default_end = date(today.year, today.month, 1) - timedelta(days=1)

    return render(request, 'accounts/payroll_calculate.html', {
        'staff': staff,
        'default_start': default_start,
        'default_end': default_end,
    })


@admin_required
def payroll_detail(request, pk):
    """Деталі розрахунку зарплати."""
    from .models_payroll import PayrollPeriod, Shift

    period = get_object_or_404(PayrollPeriod, pk=pk, organization=request.organization)
    shifts = Shift.objects.filter(
        user=period.user, organization=period.organization,
        date__gte=period.period_start, date__lte=period.period_end,
    ).order_by('date')

    return render(request, 'accounts/payroll_detail.html', {
        'payroll': period,
        'shifts': shifts,
    })


@admin_required
@require_POST
def payroll_approve(request, pk):
    """Затвердити розрахунок."""
    from .models_payroll import PayrollPeriod

    period = get_object_or_404(PayrollPeriod, pk=pk, organization=request.organization)
    if period.status == 'draft':
        period.status = PayrollPeriod.Status.APPROVED
        period.approved_at = timezone.now()
        period.save(update_fields=['status', 'approved_at'])
        messages.success(request, 'Розрахунок затверджено.')
    return redirect('accounts:payroll_detail', pk=pk)


@admin_required
@require_POST
def payroll_pay(request, pk):
    """Позначити як виплачено + створити Expense."""
    from .models_payroll import PayrollPeriod

    period = get_object_or_404(PayrollPeriod, pk=pk, organization=request.organization)
    if period.status in ('draft', 'approved'):
        period.status = PayrollPeriod.Status.PAID
        period.paid_at = timezone.now()
        period.save(update_fields=['status', 'paid_at'])

        # Створити витрату в фінансах
        try:
            from apps.finance.models import Expense, ExpenseCategory
            cat, _ = ExpenseCategory.objects.get_or_create(
                name='Зарплата', organization=period.organization,
            )
            payment_method = request.POST.get('payment_method', 'cash')
            Expense.objects.create(
                organization=period.organization,
                category=cat,
                amount=period.salary_total,
                payment_method=payment_method,
                description=f'Зарплата {period.user.get_full_name()} за '
                            f'{period.period_start.strftime("%d.%m")}'
                            f'\u2014{period.period_end.strftime("%d.%m.%Y")}',
                date=timezone.now().date(),
                created_by=request.user,
            )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).exception('Expense creation failed for payroll=%s', period.pk)
            messages.warning(request, f'Зарплату виплачено, але витрату не створено: {exc}')

        messages.success(request, f'Виплату {period.salary_total} \u20b4 зафіксовано.')
    return redirect('accounts:payroll_detail', pk=pk)


@admin_required
@require_POST
def payroll_recalculate(request, pk):
    """Перерахувати зарплату."""
    from .models_payroll import PayrollPeriod

    period = get_object_or_404(PayrollPeriod, pk=pk, organization=request.organization)
    if period.status == 'draft':
        period.calculate()
        period.save()
        messages.success(request, 'Перераховано.')
    return redirect('accounts:payroll_detail', pk=pk)


@admin_required
@require_POST
def payroll_delete(request, pk):
    """Видалити розрахунок (тільки чернетки)."""
    from .models_payroll import PayrollPeriod

    period = get_object_or_404(PayrollPeriod, pk=pk, organization=request.organization)
    if period.status == 'draft':
        period.delete()
        messages.success(request, 'Розрахунок видалено.')
    return redirect('accounts:payroll_list')
