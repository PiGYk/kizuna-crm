"""Прибирає «клініки», яких ніхто не підтвердив і в яких нема жодних даних.

Народжено 31.10.2026: боти з 15.10 нареєстрували 102 порожні організації з
чужими адресами. Захист на вході тепер відсікає їх, а це — щоденне прибирання
того, що все ж проскочить: організація старша за --days, жоден її користувач не
підтвердив пошту і не заходив, і видалення не зачепить нічого, крім того, що
створює сама реєстрація.

  python manage.py cleanup_unverified            # лише показати
  python manage.py cleanup_unverified --apply    # видалити
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models.deletion import Collector
from django.utils import timezone

# Що створює реєстрація сама — лише це дозволено знести разом з організацією.
# Будь-що інше в збирачі видалення = справжні дані → організацію не чіпаємо.
SAFE_MODELS = {
    'clinic.Organization', 'clinic.TrialEmail',
    'clients.VisitTemplate', 'finance.FinanceSettings',
    'accounts.User', 'accounts.EmailVerification',
}


def deletion_models(groups):
    """Які моделі зачепить видалення. Збирач приймає об'єкти ОДНІЄЇ моделі за раз."""
    collector = Collector(using='default')
    for objs in groups:
        if objs:
            collector.collect(objs)
    labels = {m._meta.label for m in collector.data}
    for qs in collector.fast_deletes:
        if qs.exists():
            labels.add(qs.model._meta.label)
    return labels


def org_is_disposable(org):
    """(так/ні, причина). Користувачі: FK на клініку — SET_NULL, тож їх рахуємо окремо."""
    from apps.accounts.models import User
    users = list(User._base_manager.filter(organization=org))
    extra = deletion_models([users, [org]]) - SAFE_MODELS
    if extra:
        return False, 'є дані: ' + ', '.join(sorted(extra))
    return True, ''


def delete_org(org):
    from apps.accounts.models import User
    with transaction.atomic():
        User._base_manager.filter(organization=org).delete()
        org.delete()


class Command(BaseCommand):
    help = 'Видаляє непідтверджені порожні клініки (боти, покинуті реєстрації)'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=7)
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **opts):
        from apps.accounts.models import User
        from apps.clinic.models import Organization

        cutoff = timezone.now() - timedelta(days=opts['days'])
        confirmed = User._base_manager.filter(is_active=True).values('organization_id')
        logged_in = User._base_manager.filter(last_login__isnull=False).values('organization_id')
        candidates = (Organization._base_manager
                      .filter(created_at__lt=cutoff, users__isnull=False)
                      .exclude(pk__in=confirmed).exclude(pk__in=logged_in)
                      .exclude(plan__gt='').distinct().order_by('pk'))
        removed = kept = 0
        for org in candidates:
            ok, why = org_is_disposable(org)
            if not ok:
                kept += 1
                self.stdout.write(f'  лишаю [{org.pk}] {org.slug}: {why}')
                continue
            self.stdout.write(f'  {"видаляю" if opts["apply"] else "видалив би"} [{org.pk}] {org.slug} ({org.created_at:%d.%m})')
            if opts['apply']:
                delete_org(org)
            removed += 1
        self.stdout.write(f'Непідтверджених порожніх клінік: {removed}'
                          f'{" — видалено" if opts["apply"] else " (сухий прогін)"}; лишено з даними: {kept}')
