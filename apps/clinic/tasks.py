# -*- coding: utf-8 -*-
"""Періодичні задачі клінік."""
import logging

from celery import shared_task
from django.conf import settings
from django.core.management import call_command

logger = logging.getLogger(__name__)


@shared_task(name='apps.clinic.tasks.send_trial_emails')
def send_trial_emails():
    """Щоденні листи супроводу тріалу.

    Запобіжник: поки TRIAL_EMAILS_ENABLED вимкнено, задача робить сухий прогін
    і лише пише в лог, кому пішло б. Жоден лист назовні не йде.
    """
    enabled = getattr(settings, 'TRIAL_EMAILS_ENABLED', False)
    logger.info('Листи тріалу: старт, відправка %s', 'УВІМКНЕНА' if enabled else 'вимкнена')
    call_command('send_trial_emails', send=enabled, verbosity=1)
    return 'sent' if enabled else 'dry-run'


@shared_task(name='apps.clinic.tasks.check_clinic_mail')
def check_clinic_mail():
    """Кожні пів години: нові відповіді клінік → чернетка + сповіщення Олегу.

    Нічого не відправляє клієнтам — тільки готує чернетку в пошті.
    """
    from apps.clinic import mail_replier
    n = mail_replier.process(limit=10, dry_run=False)
    logger.info('Пошта клінік: опрацьовано листів %s', n)
    return n

@shared_task(name='apps.clinic.tasks.notify_abandoned_payments')
def notify_abandoned_payments(minutes=30):
    """Хто натиснув «оплатити» і не дійшов. Раз на 15 хв.

    Обрив = запис зі статусом `initiated`, якому більше `minutes` хвилин і по
    якому не прийшов жоден колбек. Сповіщаємо ОДИН раз (notified_abandoned).
    """
    from datetime import timedelta
    from django.utils import timezone
    from apps.clinic.models import PaymentTransaction
    from apps.clinic.payment_alerts import notify_abandoned
    from apps.clinic.wayforpay import PLANS

    cutoff = timezone.now() - timedelta(minutes=minutes)
    stale = PaymentTransaction.objects.filter(
        status='initiated', notified_abandoned=False, processed_at__lt=cutoff,
    ).select_related('organization')[:50]

    sent = 0
    for tx in stale:
        try:
            age = int((timezone.now() - tx.processed_at).total_seconds() // 60)
            notify_abandoned(tx.organization,
                             PLANS.get(tx.plan_key, {}).get('label', tx.plan_key),
                             tx.amount, tx.order_ref, age)
            tx.notified_abandoned = True
            tx.save(update_fields=['notified_abandoned'])
            sent += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning('abandoned alert failed for %s: %s', tx.order_ref, exc)
    if sent:
        logger.info('abandoned payment alerts sent: %s', sent)
    return sent
