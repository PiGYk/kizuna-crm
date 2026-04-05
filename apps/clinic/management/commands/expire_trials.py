"""Management command: деактивує клініки з прострочим тріалом.

Запуск вручну:
    python manage.py expire_trials

Додати в cron (щодня о 2:00):
    0 2 * * * cd /opt/kizuna-crm && docker compose exec -T web python manage.py expire_trials
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.clinic.models import Organization


class Command(BaseCommand):
    help = 'Деактивує організації з прострочим тріалом'

    def handle(self, *args, **options):
        now = timezone.now()
        expired = Organization.objects.filter(
            is_active=True,
            trial_expires_at__isnull=False,
            trial_expires_at__lt=now,
        )
        count = expired.count()
        if count:
            expired.update(is_active=False)
            self.stdout.write(self.style.SUCCESS(f'Деактивовано {count} клінік(и) з простроченим тріалом.'))
        else:
            self.stdout.write('Прострочених тріалів не знайдено.')
