# -*- coding: utf-8 -*-
"""Розсилка листів супроводу тріалу.

За замовчуванням лише показує, кому що пішло б (сухий прогін).
Реально шле тільки з --send.

    python manage.py send_trial_emails            # подивитись
    python manage.py send_trial_emails --send     # відправити
    python manage.py send_trial_emails --send --only 17,20
"""
import datetime

from django.core.mail import send_mail
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.clinic.models import Organization, TrialEmail
from apps.clinic import trial_emails as T
from apps.clinic.trial_emails_html import build_html

# Клініки з «вічним» тріалом (Ірпінь, демо) не турбуємо взагалі.
FOREVER_AFTER_DAYS = 365
SKIP_SLUG_PREFIXES = ('demo',)
SKIP_ORG_IDS = {1, 3, 4}  # власна Kizuna і старі тестові


class Command(BaseCommand):
    help = 'Листи супроводу тріалу: привітання, підказка, нагадування, підсумок'

    def add_arguments(self, parser):
        parser.add_argument('--send', action='store_true', help='реально відправити')
        parser.add_argument('--only', default='', help='лише ці id організацій через кому')

    def handle(self, *args, **opts):
        now = timezone.now()
        only = {int(x) for x in opts['only'].split(',') if x.strip().isdigit()}
        forever = now + datetime.timedelta(days=FOREVER_AFTER_DAYS)

        planned = []
        for org in Organization.objects.all().order_by('id'):
            if only and org.id not in only:
                continue
            if org.id in SKIP_ORG_IDS:
                continue
            if any((org.slug or '').startswith(p) for p in SKIP_SLUG_PREFIXES):
                continue
            if not org.trial_expires_at or org.trial_expires_at > forever:
                continue  # безстроковий доступ — не чіпаємо

            user = self._owner(org)
            if not user or not user.email:
                continue

            kind = self._pick(org, now)
            if not kind:
                continue
            if TrialEmail.objects.filter(organization=org, kind=kind, ok=True).exists():
                continue

            planned.append((org, user, kind))

        if not planned:
            self.stdout.write('Нікому слати — усе закрито або вже надіслано.')
            return

        for org, user, kind in planned:
            name = (user.first_name or '').strip()
            subject, body = T.build(kind, name=name, clinic=org.name,
                                    trial_ends=org.trial_expires_at)
            left = (org.trial_expires_at - now).days
            head = f'[{org.id}] {org.name} → {user.email} | {kind} | лишилось {left} дн.'
            if not opts['send']:
                self.stdout.write(self.style.WARNING('СУХИЙ ПРОГІН ' + head))
                self.stdout.write(f'    тема: {subject}')
                continue
            try:
                html = build_html(kind, name=name, clinic=org.name,
                                  ends=T._date(org.trial_expires_at),
                                  subject=subject, title=subject)
                send_mail(subject=subject, message=body, from_email=None,
                          recipient_list=[user.email], html_message=html, fail_silently=False)
                TrialEmail.objects.create(organization=org, kind=kind, to_email=user.email, ok=True)
                self.stdout.write(self.style.SUCCESS('НАДІСЛАНО ' + head))
            except Exception as e:  # noqa: BLE001 — лог і далі, одна помилка не валить решту
                TrialEmail.objects.create(organization=org, kind=kind, to_email=user.email,
                                          ok=False, error=str(e)[:2000])
                self.stdout.write(self.style.ERROR(f'ПОМИЛКА {head}: {e}'))

    # --- допоміжне ---

    def _owner(self, org):
        """Головна людина клініки: адмін, інакше найперший користувач."""
        from django.contrib.auth import get_user_model
        U = get_user_model()
        qs = U._base_manager.filter(organization=org, is_active=True).order_by('id')
        return qs.filter(is_staff=True).first() or qs.first()

    def _pick(self, org, now):
        """Який лист доречний саме зараз."""
        left = (org.trial_expires_at - now).total_seconds() / 86400
        age = (now - org.created_at).days if getattr(org, 'created_at', None) else None

        if left < 0:
            return T.EXPIRED if left > -4 else None
        if left <= 1.5:
            return T.BEFORE1
        if left <= 5.5:
            return T.BEFORE5
        if age is not None and age >= 3 and self._is_cold(org):
            return T.DAY3
        if age is not None and age <= 1:
            return T.WELCOME
        return T.WELCOME  # зареєструвався давно, привітання ще не отримав

    def _is_cold(self, org):
        """Клініка так і не почала працювати."""
        from apps.clients.models import Client
        return Client._base_manager.filter(organization=org).count() < 2
