from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Закрити касову зміну в Checkbox (викликається о 20:00 через cron)'

    def handle(self, *args, **options):
        from apps.billing.checkbox_service import CheckboxService
        try:
            svc = CheckboxService()
            svc.authenticate()
            svc.close_shift()
            self.stdout.write(self.style.SUCCESS('Касову зміну закрито успішно.'))
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f'Помилка закриття зміни: {exc}'))
