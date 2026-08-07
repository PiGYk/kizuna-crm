from datetime import date, timedelta, time
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .mixins import admin_required


@login_required
def shift_list(request):
    """Розклад змін — календарний вигляд за місяць."""
    from .models_payroll import Shift
    from .models import User

    org = request.organization
    year = int(request.GET.get('year', date.today().year))
    month = int(request.GET.get('month', date.today().month))

    first_day = date(year, month, 1)
    if month == 12:
        last_day = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        last_day = date(year, month + 1, 1) - timedelta(days=1)

    shifts = Shift.objects.filter(
        organization=org, date__gte=first_day, date__lte=last_day,
    ).select_related('user').order_by('date', 'start_time')

    # Групуємо по датах (ключі — рядки ISO для template lookup)
    from collections import defaultdict
    shifts_by_date = defaultdict(list)
    for s in shifts:
        shifts_by_date[s.date.isoformat()].append(s)

    # Генеруємо календарну сітку
    import calendar
    cal = calendar.Calendar(firstweekday=0)
    weeks = cal.monthdatescalendar(year, month)

    staff = User.objects.filter(organization=org, is_active=True).order_by('last_name')

    # Навігація
    prev_month = first_day - timedelta(days=1)
    next_month = last_day + timedelta(days=1)

    return render(request, 'accounts/shifts.html', {
        'weeks': weeks,
        'shifts_by_date': dict(shifts_by_date),
        'current_month': first_day,
        'year': year,
        'month': month,
        'staff': staff,
        'prev_year': prev_month.year,
        'prev_month_num': prev_month.month,
        'next_year': next_month.year,
        'next_month_num': next_month.month,
        'today': date.today(),
    })


@login_required
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



@login_required
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
