from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Закрити касову зміну у Checkbox для всіх організацій (cron щодня о 20:00)'

    def handle(self, *args, **options):
        from apps.billing.checkbox_service import CheckboxService
        from apps.clinic.models import Organization

        orgs = Organization._base_manager.filter(is_active=True).exclude(
            checkbox_pin=''
        ).exclude(checkbox_license_key='')

        if not orgs.exists():
            self.stdout.write('Немає організацій з налаштованим Checkbox.')
            return

        ok, failed = 0, 0
        for org in orgs:
            try:
                svc = CheckboxService(org)
                svc.authenticate()
                svc.close_shift()
                ok += 1
                self.stdout.write(self.style.SUCCESS(f'[{org.slug}] зміну закрито'))
            except Exception as exc:
                failed += 1
                self.stderr.write(self.style.ERROR(f'[{org.slug}] помилка: {exc}'))

        self.stdout.write(f'Готово: {ok} OK / {failed} помилок.')
