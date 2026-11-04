"""Депозит клієнта (ANVAR 04.11.2026): клієнт лишає гроші наперед — напр. 10 000 ₴ — і з них потім
оплачуються його рахунки.

Рух через касу — ClientDeposit: «внесено» (готівкою чи карткою) і «повернуто клієнту»; каса
(finance.calculate_balances) рахує саме їх. Оплата рахунку з депозиту — звичайний платіж InvoicePayment
зі способом «З депозиту»: нових грошей у касу не додає (вони прийшли при внесенні), а рахунок вважається
сплаченим. Залишок = внесено − повернуто − сплачено з депозиту, тож прибраний платіж сам повертає
гроші на депозит. Списати можна не більше, ніж є: рядок клієнта блокується до кінця транзакції.
"""
from decimal import Decimal, InvalidOperation

from django.db.models import Q, Sum

from .models import ClientDeposit, Invoice, InvoicePayment

ZERO = Decimal('0')
DEPOSIT = Invoice.PaymentMethod.DEPOSIT


def money(value):
    """10000 → «10 000», 1234.5 → «1 234,50» — для повідомлень."""
    value = Decimal(value or 0).quantize(Decimal('0.01'))
    text = f'{value:,.2f}'.replace(',', ' ').replace('.', ',')
    return text[:-3] if text.endswith(',00') else text


def parse_amount(raw):
    raw = (raw or '').strip().replace(' ', '').replace('\xa0', '').replace(',', '.')
    try:
        amount = Decimal(raw).quantize(Decimal('0.01'))
    except InvalidOperation:
        raise ValueError(f'«{raw}» — не сума' if raw else 'вкажіть суму')
    if amount <= 0:
        raise ValueError('сума має бути більше нуля')
    if amount >= Decimal('100000000'):
        raise ValueError('завелика сума')
    return amount


def _sums(org_id, client_ids=None):
    """{client_id: {'topped', 'refunded', 'spent', 'balance'}} — по клієнтах, що мали депозит."""
    ops = ClientDeposit._base_manager.filter(organization_id=org_id)
    pays = InvoicePayment._base_manager.filter(organization_id=org_id, method=DEPOSIT)
    if client_ids is not None:
        ops = ops.filter(client_id__in=client_ids)
        pays = pays.filter(invoice__client_id__in=client_ids)
    out = {}

    def row(cid):
        return out.setdefault(cid, {'topped': ZERO, 'refunded': ZERO, 'spent': ZERO})

    for r in ops.values('client_id').annotate(
            t_in=Sum('amount', filter=Q(kind=ClientDeposit.Kind.TOPUP)),
            t_out=Sum('amount', filter=Q(kind=ClientDeposit.Kind.REFUND))):
        d = row(r['client_id'])
        d['topped'], d['refunded'] = r['t_in'] or ZERO, r['t_out'] or ZERO
    for r in pays.values('invoice__client_id').annotate(t=Sum('amount')):
        row(r['invoice__client_id'])['spent'] = r['t'] or ZERO
    for d in out.values():
        d['balance'] = d['topped'] - d['refunded'] - d['spent']
    return out


def balance(client):
    if client is None or not client.pk:
        return ZERO
    return _sums(client.organization_id, [client.pk]).get(client.pk, {}).get('balance', ZERO)


def lock(client):
    """Блокує рядок клієнта до кінця транзакції: два одночасні списання не проскочать повз залишок."""
    from apps.clients.models import Client
    Client._base_manager.select_for_update().filter(pk=client.pk).first()


def check_rows(client, rows):
    """Рядки оплати «З депозиту» — разом не більше, ніж на депозиті клієнта. Інакше ValueError."""
    want = sum((amount for method, amount in rows if method == DEPOSIT), ZERO)
    if not want:
        return
    lock(client)
    have = balance(client)
    if want > have:
        raise ValueError(f'з депозиту {money(want)} ₴, а на депозиті клієнта {money(have)} ₴')


def top_up(client, amount, method, user=None, note=''):
    if method not in ClientDeposit.Method.values:
        raise ValueError('оберіть готівку чи картку')
    return ClientDeposit.objects.create(
        organization_id=client.organization_id, client=client, kind=ClientDeposit.Kind.TOPUP,
        amount=amount, method=method, note=(note or '').strip()[:200],
        created_by=user if getattr(user, 'is_authenticated', False) else None,
    )


def refund(client, amount, method, user=None, note=''):
    if method not in ClientDeposit.Method.values:
        raise ValueError('оберіть готівку чи картку')
    lock(client)
    have = balance(client)
    if amount > have:
        raise ValueError(f'повернути можна не більше, ніж на депозиті: {money(have)} ₴')
    return ClientDeposit.objects.create(
        organization_id=client.organization_id, client=client, kind=ClientDeposit.Kind.REFUND,
        amount=amount, method=method, note=(note or '').strip()[:200],
        created_by=user if getattr(user, 'is_authenticated', False) else None,
    )


def delete_op(op):
    """Прибрати помилковий запис. Внесення — лише якщо з нього ще не заплатили (залишок не піде в мінус)."""
    if op.kind == ClientDeposit.Kind.TOPUP:
        lock(op.client)
        have = balance(op.client)
        if have - op.amount < 0:
            raise ValueError(f'з цього внесення вже оплачено рахунки — на депозиті лише {money(have)} ₴. '
                             'Спершу приберіть ті платежі в рахунках')
    op.delete()


def _entries(ops, pays):
    """Внесення, повернення й оплати рахунків — одним списком, новіші вгорі."""
    items = [{
        'at': op.created_at, 'op': op, 'client': op.client, 'kind': op.kind, 'label': op.get_kind_display(),
        'method': op.get_method_display(), 'amount': op.amount, 'sign': 1 if op.kind == ClientDeposit.Kind.TOPUP else -1,
        'note': op.note, 'who': op.created_by,
    } for op in ops]
    items += [{
        'at': p.paid_at, 'payment': p, 'client': p.invoice.client, 'kind': 'spent',
        'label': f'Оплата рахунку #{p.invoice_id}', 'invoice_id': p.invoice_id, 'method': '', 'amount': p.amount,
        'sign': -1, 'note': '', 'who': p.created_by,
    } for p in pays]
    items.sort(key=lambda e: e['at'], reverse=True)
    return items


def history(client, limit=50):
    ops = ClientDeposit._base_manager.filter(client=client).select_related('client', 'created_by')[:limit]
    pays = (InvoicePayment._base_manager.filter(method=DEPOSIT, invoice__client=client)
            .select_related('invoice__client', 'created_by').order_by('-paid_at')[:limit])
    return _entries(ops, pays)[:limit]


def recent(org, limit=40):
    ops = ClientDeposit._base_manager.filter(organization=org).select_related('client', 'created_by')[:limit]
    pays = (InvoicePayment._base_manager.filter(organization=org, method=DEPOSIT)
            .select_related('invoice__client', 'created_by').order_by('-paid_at')[:limit])
    return _entries(ops, pays)[:limit]


def org_summary(org):
    """Клієнти з депозитом (новий залишок угорі) і скільки всього на депозитах."""
    from apps.clients.models import Client
    sums = _sums(org.pk)
    clients = {c.pk: c for c in Client._base_manager.filter(pk__in=sums.keys())}
    rows = [dict(client=clients[cid], **d) for cid, d in sums.items() if cid in clients]
    rows.sort(key=lambda r: (r['balance'] <= 0, -r['balance'], r['client'].last_name))
    on_deposit = sum((r['balance'] for r in rows if r['balance'] > 0), ZERO)
    return rows, on_deposit
