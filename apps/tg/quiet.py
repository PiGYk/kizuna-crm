"""Неробочий час (Олег 19.11.2026): уночі персонал не смикаємо — сповіщення про повідомлення клієнтів приходять зранку,
а клієнт одразу отримує відповідь «опрацюємо у робочий час».

Вікно — `Organization.quiet_from` … `quiet_until`, може йти через північ (Kizuna: 18:00 → 08:00). Не задано — усе як
раніше. Уночі `broadcast_tasks.notify_staff_new_message_task` мовчить, а зранку `deliver_night_messages` шле персоналу
по сповіщенню на кожен чат, що писав уночі."""
import datetime as dt

from django.utils import timezone


def _at(day, t):
    return timezone.make_aware(dt.datetime.combine(day, t))


def window(org, now=None):
    """(початок, кінець) нічного вікна, у якому зараз `now`; None — зараз не ніч або вікно не задано."""
    qf, qu = getattr(org, 'quiet_from', None), getattr(org, 'quiet_until', None)
    if not qf or not qu or qf == qu:
        return None
    now = timezone.localtime(now)
    day, t = now.date(), now.time()
    if qf > qu:   # через північ
        if t >= qf:
            return _at(day, qf), _at(day + dt.timedelta(days=1), qu)
        if t < qu:
            return _at(day - dt.timedelta(days=1), qf), _at(day, qu)
        return None
    return (_at(day, qf), _at(day, qu)) if qf <= t < qu else None


def is_quiet(org, now=None):
    return window(org, now) is not None


def last_window(org, now=None):
    """Нічне вікно, що скінчилося останнім перед `now` — його повідомлення персонал отримує зранку."""
    qf, qu = org.quiet_from, org.quiet_until
    now = timezone.localtime(now)
    end_day = now.date() if now.time() >= qu else now.date() - dt.timedelta(days=1)
    start_day = end_day - dt.timedelta(days=1) if qf > qu else end_day
    return _at(start_day, qf), _at(end_day, qu)


def reply_text(org):
    hours = (getattr(org, 'work_hours', '') or '').strip()
    text = 'Дякуємо за повідомлення! Ми опрацюємо ваше звернення у робочий час'
    return f'{text} ({hours[:1].lower()}{hours[1:]}).' if hours else f'{text}.'


def maybe_autoreply(chat, now=None):
    """Клієнт написав уночі — раз за ніч відповідаємо, що опрацюємо у робочий час. True — відповіли."""
    org = chat.organization
    w = window(org, now)
    if not w or chat.is_staff:
        return False
    from .models import TelegramMessage
    text = reply_text(org)
    if TelegramMessage._base_manager.filter(chat=chat, direction=TelegramMessage.Direction.OUT, text=text,
                                            created_at__gte=w[0]).exists():
        return False
    from .views import _send_tg
    _send_tg(chat.tg_user_id, text, org=org)
    TelegramMessage._base_manager.create(chat=chat, direction=TelegramMessage.Direction.OUT, text=text, is_read=True)
    return True
