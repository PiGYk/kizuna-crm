"""Розхідники (рукавички, шприци, вата) у звітах прибутку (ANVAR 02.11.2026).

Відсоток задає клініка: FinanceSettings.consumables_percent (типово 0; Kizuna — 5). Береться лише з виручки
ПОСЛУГ БЕЗ СКЛАДУ: у послуги із заповненим складом матеріали вже в собівартості, вдруге їх не віднімаємо.
Товари не беруть участі — їхня собівартість відома з ціни закупівлі.
"""
from decimal import Decimal

from django.db.models import Exists, OuterRef, Sum
from django.db.models.functions import TruncDate


def consumables_pct(org):
    from .models import FinanceSettings
    return FinanceSettings.get_for_org(org).consumables_percent if org else Decimal('0')


def _bare_service_lines(invoices):
    from apps.billing.models import InvoiceLine
    from apps.services.models import ServiceComponent
    has_comp = Exists(ServiceComponent.objects.filter(service=OuterRef('service')))
    return InvoiceLine.objects.filter(invoice__in=invoices, line_type='service').annotate(
        has_comp=has_comp).filter(has_comp=False)


def consumables_for(org, invoices, pct=None):
    """(сума, база, скільки різних проданих послуг без складу, відсоток) для оплачених рахунків."""
    pct = consumables_pct(org) if pct is None else Decimal(pct)
    lines = _bare_service_lines(invoices)
    base = lines.aggregate(t=Sum('total'))['t'] or Decimal('0')
    bare = lines.exclude(service__isnull=True).values('service').distinct().count()
    return (base * pct / 100).quantize(Decimal('0.01')), base, bare, pct


def consumables_per_day(org, invoices, pct=None):
    """{дата: сума розхідників} — для щоденних графіків прибутку."""
    pct = consumables_pct(org) if pct is None else Decimal(pct)
    if not pct:
        return {}
    rows = (_bare_service_lines(invoices).annotate(d=TruncDate('invoice__created_at'))
            .values('d').annotate(t=Sum('total')).values_list('d', 't'))
    return {d: ((t or Decimal('0')) * pct / 100).quantize(Decimal('0.01')) for d, t in rows}
