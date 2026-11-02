"""Звільнення співробітників (ANVAR 01.11.2026: «уволил — зачем они мне в списке», текучка кадрів).

Звільнений = is_active=False: не входить у CRM, не пропонується у виборі лікаря/виконавця
(User.practitioners), не займає місце в тарифі. Його ім'я лишається в минулих прийомах,
рахунках, змінах і зарплатах. Видалити назавжди можна лише того, за ким нема жодної історії
(створений помилково): Shift і PayrollPeriod видаляються каскадом, а в прийомах і рахунках
лікар став би порожнім.
"""
from .models import User

# Не історія: технічні зв'язки й налаштування (лікар за замовчуванням знімається окремо)
_NOT_HISTORY = {
    'admin.logentry', 'accounts.user_groups', 'accounts.user_user_permissions',
    'accounts.emailverification', 'dashboard_builder.dashboard', 'carddav.carddavtoken',
    'clinic.organization',
}
_LABELS = {'tg.telegrammessage': 'Повідомлення Telegram'}


def user_history(user):
    """[(що, скільки)] — записи клініки, що посилаються на людину. Порожньо → можна видалити."""
    found = {}
    for rel in User._meta.get_fields(include_hidden=True):
        if not (rel.auto_created and not rel.concrete and (rel.one_to_many or rel.one_to_one)):
            continue
        model = rel.related_model
        label = model._meta.label_lower
        if label in _NOT_HISTORY:
            continue
        n = model._base_manager.filter(**{rel.field.name: user}).count()
        if n:
            name = _LABELS.get(label, str(model._meta.verbose_name_plural))
            found[name] = found.get(name, 0) + n
    return sorted(found.items(), key=lambda kv: -kv[1])


def fired_users(org):
    """Звільнені клініки з позначкою, чи є за ними історія (history_total)."""
    fired = list(User.objects.filter(organization=org, is_active=False).order_by('last_name', 'first_name'))
    for u in fired:
        u.history_total = sum(n for _, n in user_history(u))
    return fired


def seats_left(org):
    """Скільки ще активних користувачів дозволяє тариф (None — без обмеження)."""
    limit = org.max_doctors if org else None
    if limit is None:
        return None
    return limit - User.objects.filter(organization=org, is_active=True).count()
