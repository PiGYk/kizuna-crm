# -*- coding: utf-8 -*-
"""Перевірка пошти: чернетки відповідей на листи клінік.

    python manage.py check_clinic_mail            # показати, нічого не робити
    python manage.py check_clinic_mail --apply    # зберегти чернетки + сповістити Олега
"""
from django.core.management.base import BaseCommand

from apps.clinic import mail_replier


class Command(BaseCommand):
    help = 'Читає відповіді клінік і готує чернетки відповідей'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                            help='зберегти чернетки в пошту і сповістити Олега')
        parser.add_argument('--limit', type=int, default=10)

    def handle(self, *args, **opts):
        n = mail_replier.process(limit=opts['limit'], dry_run=not opts['apply'])
        if not n:
            self.stdout.write('Нових відповідей від клінік немає.')
        else:
            self.stdout.write(self.style.SUCCESS(
                f'Опрацьовано листів: {n}' + ('' if opts['apply'] else ' (лише показ)')))
