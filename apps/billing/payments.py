"""Платежі за рахунками (ANVAR 01.11.2026): частинами, змішано, борг. Усі місця, де рахунок стає
оплаченим, записують платіж тут — каса (finance.calculate_balances) рахує саме платежі."""
from decimal import Decimal, InvalidOperation

from django.db import transaction

from .models import Invoice, InvoicePayment


def add_payment(invoice, amount, method, user=None, paid_at=None):
    amount = Decimal(amount).quantize(Decimal('0.01'))
    if amount <= 0:
        raise ValueError('сума має бути більше нуля')
    if method not in Invoice.PaymentMethod.values:
        raise ValueError('невідомий спосіб оплати')
    kwargs = {'paid_at': paid_at} if paid_at else {}
    payment = InvoicePayment.objects.create(
        invoice=invoice, organization_id=invoice.organization_id, amount=amount, method=method,
        created_by=user if getattr(user, 'is_authenticated', False) else None, **kwargs,
    )
    invoice.refresh_paid()
    return payment


def pay_rest(invoice, method, user=None):
    """Старі потоки «оплатити одним способом» і Checkbox: платіж на весь залишок."""
    invoice.refresh_paid()
    due = invoice.balance_due
    if due > 0:
        add_payment(invoice, due, method, user)


def parse_payment_rows(post):
    """Рядки «спосіб + сума» з вікна оплати. Повертає [(method, Decimal)] або кидає ValueError."""
    methods, amounts = post.getlist('pay_method'), post.getlist('pay_amount')
    rows = []
    for method, raw in zip(methods, amounts):
        raw = (raw or '').strip().replace(' ', '').replace(',', '.')
        if not raw:
            continue
        try:
            amount = Decimal(raw).quantize(Decimal('0.01'))
        except InvalidOperation:
            raise ValueError(f'«{raw}» — не сума')
        if amount <= 0:
            raise ValueError('сума має бути більше нуля')
        if method not in Invoice.PaymentMethod.values:
            raise ValueError('невідомий спосіб оплати')
        rows.append((method, amount))
    return rows


@transaction.atomic
def backfill_missing(org=None):
    """Оплаченим рахункам без жодного платежу — один платіж на всю суму їхнім способом
    (демо-дані, будь-який старий шлях). Повертає кількість створених платежів."""
    qs = Invoice._base_manager.filter(status=Invoice.Status.PAID, total__gt=0, payments__isnull=True)
    if org is not None:
        qs = qs.filter(organization=org)
    n = 0
    for inv in qs.only('pk', 'organization_id', 'total', 'payment_method', 'date', 'created_by_id'):
        InvoicePayment.objects.create(
            invoice_id=inv.pk, organization_id=inv.organization_id, amount=inv.total,
            method=inv.payment_method or Invoice.PaymentMethod.CASH, paid_at=inv.date,
            created_by_id=inv.created_by_id,
        )
        Invoice._base_manager.filter(pk=inv.pk).update(amount_paid=inv.total)
        n += 1
    return n
