import logging
from celery import shared_task
from django.conf import settings
from django.utils import timezone
from django.core.mail import send_mail

logger = logging.getLogger(__name__)

REMIND_DAYS_BEFORE = 10


@shared_task
def send_vaccine_reminders():
    """
    Щоденна задача: знаходить вакцини, що закінчуються через REMIND_DAYS_BEFORE днів,
    та відправляє нагадування клієнту через Telegram і/або Email.
    """
    from datetime import date, timedelta
    from apps.clients.models import Vaccine

    target_date = date.today() + timedelta(days=REMIND_DAYS_BEFORE)

    vaccines = (
        Vaccine.objects
        .filter(valid_until=target_date, reminder_sent=False)
        .select_related('patient__client', 'patient__client__organization')
    )

    sent_count = 0
    for vaccine in vaccines:
        client = vaccine.patient.client
        patient = vaccine.patient
        org = client.organization

        ok_tg = _remind_telegram(vaccine, patient, client, org)
        ok_email = _remind_email(vaccine, patient, client, org)

        if ok_tg or ok_email:
            vaccine.reminder_sent = True
            vaccine.save(update_fields=['reminder_sent'])
            sent_count += 1
            logger.info(
                'Vaccine reminder sent for %s (%s) — valid until %s',
                patient.name, vaccine.name, vaccine.valid_until,
            )
        else:
            logger.warning(
                'No channel available for vaccine reminder: client %s has no TG/email',
                client,
            )

    logger.info('send_vaccine_reminders: processed %d vaccines', sent_count)
    return sent_count


def _remind_telegram(vaccine, patient, client, org):
    """Відправити нагадування через Telegram."""
    try:
        from apps.tg.models import TelegramChat
        from apps.tg.views import _send_tg, _get_token

        token = _get_token(org)
        if not token:
            return False

        chat = TelegramChat.objects.filter(client=client, organization=org).first()
        if not chat:
            return False

        text = (
            f'💉 <b>Нагадування про вакцинацію!</b>\n\n'
            f'🐾 Тварина: <b>{patient.name}</b>\n'
            f'💊 Вакцина: {vaccine.name}\n'
            f'📅 Діє до: <b>{vaccine.valid_until:%d.%m.%Y}</b>\n\n'
            f'<i>До закінчення дії залишилось {REMIND_DAYS_BEFORE} днів.</i>\n'
            f'Запишіться на повторну вакцинацію заздалегідь!'
        )
        _send_tg(chat.tg_user_id, text, org=org)
        return True
    except Exception as e:
        logger.warning('TG vaccine reminder error: %s', e)
        return False


def _remind_email(vaccine, patient, client, org):
    """Відправити нагадування на email. Повертає True якщо відправлено."""
    try:
        if not client.email:
            return False

        clinic_name = getattr(org, 'name', 'Клініка')
        subject = f'Нагадування: вакцина {vaccine.name} для {patient.name} закінчується {vaccine.valid_until:%d.%m.%Y}'
        body = (
            f'Шановний {client.full_name},\n\n'
            f'Нагадуємо, що дія вакцини вашої тварини незабаром закінчується:\n\n'
            f'  🐾 Тварина: {patient.name}\n'
            f'  💊 Вакцина: {vaccine.name}\n'
            f'  📅 Діє до: {vaccine.valid_until:%d.%m.%Y}\n\n'
            f'До закінчення залишилось {REMIND_DAYS_BEFORE} днів.\n'
            f'Будь ласка, запишіться на повторну вакцинацію заздалегідь.\n\n'
            f'З повагою,\n{clinic_name}'
        )

        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[client.email],
            fail_silently=False,
        )
        return True
    except Exception as e:
        logger.warning('Email vaccine reminder error: %s', e)
        return False


@shared_task
def send_appointment_reminders():
    """
    Нагадування клієнтам про записи:
    - За 24 години до прийому
    - За 2 години до прийому
    """
    from apps.appointments.models import Appointment
    from apps.clinic.models import Organization
    from django.utils import timezone as tz

    now = tz.now()

    for org in Organization.objects.filter(is_active=True):
        notify_24h = getattr(org, 'notify_appointment_24h', True)
        notify_2h = getattr(org, 'notify_appointment_2h', True)

        if not notify_24h and not notify_2h:
            continue

        try:
            from apps.tg.views import _get_token
            token = _get_token(org)
            if not token:
                continue
        except Exception:
            continue

        appointments = Appointment.objects.filter(
            organization=org,
            status__in=['scheduled', 'confirmed'],
            starts_at__gt=now,
        ).select_related('client', 'patient')

        for appt in appointments:
            delta = appt.starts_at - now
            hours = delta.total_seconds() / 3600

            # 24 години (вікно 23-25 год) — тільки якщо ще не відправлено
            if notify_24h and 23 <= hours <= 25 and not appt.reminder_24h_sent:
                _send_appointment_reminder(appt, org, '24 години')
                appt.reminder_24h_sent = True
                appt.save(update_fields=['reminder_24h_sent'])

            # 2 години (вікно 1.5-2.5 год) — тільки якщо ще не відправлено
            if notify_2h and 1.5 <= hours <= 2.5 and not appt.reminder_2h_sent:
                _send_appointment_reminder(appt, org, '2 години')
                appt.reminder_2h_sent = True
                appt.save(update_fields=['reminder_2h_sent'])


def _send_appointment_reminder(appt, org, time_label):
    """Відправляє нагадування клієнту про запис."""
    from apps.tg.models import TelegramChat
    from apps.tg.views import _send_tg

    try:
        tg_chat = TelegramChat.objects.filter(
            client=appt.client, organization=org
        ).first()
        if not tg_chat:
            return

        import zoneinfo
        kyiv = zoneinfo.ZoneInfo('Europe/Kyiv')
        local_time = appt.starts_at.astimezone(kyiv)

        patient_str = f' ({appt.patient.name})' if appt.patient else ''
        time_str = local_time.strftime('%H:%M')
        date_str = local_time.strftime('%d.%m.%Y')

        clinic_name = getattr(org, 'name', 'клініку')
        clinic_phone = getattr(org, 'phone', '') or ''
        phone_line = f'\nЯкщо не можете прийти — зателефонуйте: {clinic_phone}' if clinic_phone else ''

        text = (
            f'\U0001f514 <b>Нагадування про візит</b>\n\n'
            f'Через {time_label} у вас запис у {clinic_name}.\n\n'
            f'\U0001f4c5 <b>{date_str}</b> о <b>{time_str}</b>{patient_str}{phone_line}'
        )
        _send_tg(tg_chat.tg_user_id, text, org=org)
    except Exception:
        logger.exception('Appointment reminder failed for appt=%s', appt.pk)


@shared_task
def send_followup_reminders():
    """
    Нагадування про контрольний візит (follow_up_date на Visit).
    Відправляє за 1 день до дати.
    """
    from apps.clinic.models import Organization
    from apps.tg.models import TelegramChat
    from apps.tg.views import _send_tg, _get_token
    from django.utils import timezone as tz

    from datetime import timedelta
    tomorrow = tz.localdate() + timedelta(days=1)

    from .models import Visit
    if not hasattr(Visit, 'follow_up_date'):
        return

    visits = Visit.objects.filter(
        follow_up_date=tomorrow,
        patient__client__organization__is_active=True,
    ).select_related('patient', 'patient__client', 'patient__client__organization')

    for visit in visits:
        try:
            org = visit.patient.client.organization
            token = _get_token(org)
            if not token:
                continue

            tg_chat = TelegramChat.objects.filter(
                client=visit.patient.client, organization=org
            ).first()
            if not tg_chat:
                continue

            phone = getattr(org, 'phone', '') or ''
            phone_line = f'\n\nЗапишіться: {phone}' if phone else ''
            text = (
                f'\U0001f514 <b>Нагадування</b>\n\n'
                f'Завтра контрольний візит для <b>{visit.patient.name}</b>.\n'
                f'Лікар призначив повторний огляд {visit.follow_up_date.strftime("%d.%m.%Y")}.'
                f'{phone_line}'
            )
            _send_tg(tg_chat.tg_user_id, text, org=org)
        except Exception:
            logger.exception('Follow-up reminder failed for visit=%s', visit.pk)


@shared_task
def send_health_checks():
    """
    Щоденна задача: знаходить тварин яким потрібне опитування.
    Типи:
    - post_visit: 3 дні після візиту (якщо візит мав лікування)
    - weekly: раз на тиждень для тварин з хронічними (allergies)
    """
    from datetime import date, timedelta
    from apps.clients.models import Visit, Patient
    from apps.clients.models_health import HealthCheck
    from apps.clinic.models import Organization
    from apps.tg.models import TelegramChat
    from apps.tg.views import _send_tg, _get_token

    today = date.today()

    for org in Organization.objects.filter(is_active=True):
        token = None
        try:
            token = _get_token(org)
        except Exception:
            pass
        if not token:
            continue

        # -- Post-visit (3 дні після візиту з лікуванням) --
        target_date = today - timedelta(days=3)
        visits = Visit.objects.filter(
            patient__client__organization=org,
            date__date=target_date,
        ).exclude(treatment='').select_related('patient', 'patient__client')

        for visit in visits:
            # Не дублювати
            if HealthCheck.objects.filter(patient=visit.patient, visit=visit).exists():
                continue

            chat = TelegramChat.objects.filter(
                client=visit.patient.client, organization=org
            ).first()
            if not chat:
                continue

            question = (
                f'Як почувається <b>{visit.patient.name}</b> після візиту?\n\n'
                f'Оберіть відповідь:'
            )

            hc = HealthCheck.objects.create(
                patient=visit.patient,
                organization=org,
                trigger=HealthCheck.Trigger.POST_VISIT,
                question=question,
                visit=visit,
            )

            # Inline keyboard
            keyboard = {
                'inline_keyboard': [[
                    {'text': '\u2705 Все добре', 'callback_data': f'hc_ok_{hc.pk}'},
                    {'text': '\u2753 Є питання', 'callback_data': f'hc_concern_{hc.pk}'},
                ]]
            }

            import requests
            requests.post(
                f'https://api.telegram.org/bot{token}/sendMessage',
                json={
                    'chat_id': chat.tg_user_id,
                    'text': f'\U0001fa7a <b>Як справи?</b>\n\n{question}',
                    'parse_mode': 'HTML',
                    'reply_markup': keyboard,
                },
                timeout=10,
            )

        # -- Weekly для тварин з алергіями/хронічними --
        if today.weekday() == 0:  # Понеділок
            patients_with_allergies = Patient.objects.filter(
                client__organization=org,
            ).exclude(allergies='').select_related('client')

            for patient in patients_with_allergies:
                # Не частіше ніж раз на тиждень
                last = HealthCheck.objects.filter(
                    patient=patient, trigger='weekly',
                    sent_at__date__gte=today - timedelta(days=6),
                ).exists()
                if last:
                    continue

                chat = TelegramChat.objects.filter(
                    client=patient.client, organization=org
                ).first()
                if not chat:
                    continue

                question = (
                    f'Як почувається <b>{patient.name}</b> цього тижня?\n'
                    f'<i>(хронічне: {patient.allergies[:100]})</i>'
                )

                hc = HealthCheck.objects.create(
                    patient=patient,
                    organization=org,
                    trigger=HealthCheck.Trigger.WEEKLY,
                    question=question,
                )

                keyboard = {
                    'inline_keyboard': [[
                        {'text': '\u2705 Все добре', 'callback_data': f'hc_ok_{hc.pk}'},
                        {'text': '\u2753 Є питання', 'callback_data': f'hc_concern_{hc.pk}'},
                    ]]
                }

                import requests
                requests.post(
                    f'https://api.telegram.org/bot{token}/sendMessage',
                    json={
                        'chat_id': chat.tg_user_id,
                        'text': f'\U0001fa7a <b>Щотижневе опитування</b>\n\n{question}',
                        'parse_mode': 'HTML',
                        'reply_markup': keyboard,
                    },
                    timeout=10,
                )

    logger.info('send_health_checks completed')
