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
