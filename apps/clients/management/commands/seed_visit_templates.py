"""Розкласти стартовий набір шаблонів прийому по клініках.

    python manage.py seed_visit_templates            # усі активні клініки
    python manage.py seed_visit_templates --org 1    # конкретна
    python manage.py seed_visit_templates --force    # і тим, хто вже має свої
"""
from django.core.management.base import BaseCommand

from apps.clients.visit_template_seed import seed_visit_templates
from apps.clinic.models import Organization


class Command(BaseCommand):
    help = 'Створює стартові шаблони протоколу прийому для клінік'

    def add_arguments(self, parser):
        parser.add_argument('--org', type=int, help='ID однієї клініки')
        parser.add_argument(
            '--force', action='store_true',
            help='додати навіть тим, хто вже має власні шаблони',
        )

    def handle(self, *args, **opts):
        qs = Organization.objects.all()
        if opts.get('org'):
            qs = qs.filter(pk=opts['org'])
        else:
            qs = qs.filter(is_active=True)

        total = 0
        for org in qs.order_by('pk'):
            n = seed_visit_templates(org, only_if_empty=not opts.get('force'))
            total += n
            self.stdout.write(f'{org.pk} {org.name}: +{n}')
        self.stdout.write(self.style.SUCCESS(f'Разом створено: {total}'))
