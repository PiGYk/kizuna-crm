"""Розділ «Депозити» (ANVAR 04.11.2026): хто скільки лишив наперед, внесення й повернення.
Оплата рахунку з депозиту — у вікні оплати рахунку (спосіб «З депозиту»). Логіка — apps/billing/deposits.py."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.clients.models import Client

from . import deposits
from .models import ClientDeposit


def _back(request, fallback='billing:deposits'):
    nxt = request.POST.get('next') or ''
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(nxt)
    return redirect(fallback)


@login_required
def deposit_list(request):
    org = request.organization
    rows, on_deposit, entries, picked, picked_balance = [], 0, [], None, None
    if org is not None:
        rows, on_deposit = deposits.org_summary(org)
        entries = deposits.recent(org)
        cid = request.GET.get('client', '')
        if cid.isdigit():
            picked = Client.objects.filter(pk=cid, organization=org).first()
            picked_balance = deposits.balance(picked) if picked else None
    return render(request, 'billing/deposits.html', {
        'rows': rows,
        'on_deposit': on_deposit,
        'with_balance': sum(1 for r in rows if r['balance'] > 0),
        'entries': entries,
        'picked': picked,
        'picked_balance': picked_balance,
    })


@login_required
@require_POST
@transaction.atomic
def deposit_add(request):
    """Внести на депозит або повернути клієнту (kind=topup|refund) — готівкою чи карткою."""
    cid = request.POST.get('client', '')
    if not cid.isdigit():
        messages.error(request, 'Не збережено: оберіть клієнта.')
        return _back(request)
    client = get_object_or_404(Client, pk=cid, organization=request.organization)
    kind = request.POST.get('kind', ClientDeposit.Kind.TOPUP)
    try:
        amount = deposits.parse_amount(request.POST.get('amount'))
        method, note = request.POST.get('method', ''), request.POST.get('note', '')
        if kind == ClientDeposit.Kind.REFUND:
            deposits.refund(client, amount, method, request.user, note)
            done = f'Повернуто клієнту {deposits.money(amount)} ₴'
        elif kind == ClientDeposit.Kind.TOPUP:
            deposits.top_up(client, amount, method, request.user, note)
            done = f'Внесено на депозит {deposits.money(amount)} ₴'
        else:
            raise ValueError('невідома операція')
    except ValueError as exc:
        messages.error(request, f'Не збережено: {exc}.')
        return _back(request)
    messages.success(request, f'{done} — {client}. На депозиті: {deposits.money(deposits.balance(client))} ₴.')
    return _back(request)


@login_required
@require_POST
@transaction.atomic
def deposit_delete(request, op_id):
    """Прибрати помилковий запис внесення чи повернення (лише адміністратор)."""
    op = get_object_or_404(ClientDeposit, pk=op_id, organization=request.organization)
    if not request.user.is_admin():
        messages.error(request, 'Записи депозиту прибирає лише адміністратор.')
        return _back(request)
    try:
        deposits.delete_op(op)
    except ValueError as exc:
        messages.error(request, f'Не прибрано: {exc}.')
        return _back(request)
    messages.success(request, f'Запис «{op.get_kind_display()} {deposits.money(op.amount)} ₴» прибрано.')
    return _back(request)
