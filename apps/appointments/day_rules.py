"""Правила днів запису: хто з лікарів приймає, коли беремо екзотів і операції.

Народжено 12.10.2026 (Катя): екзотів (усе, крім собак і котів) і операції веде
тільки вона — вівторок, п'ятниця, субота, неділя. Бот у Telegram і форма на сайті
записували кроликів на середу й четвер, коли такого лікаря немає (кролик Чуча).
Тут одне джерело правди для обох каналів запису.

Розклад лікарів — постійний тижневий. Підміни між собою тут не видно; Катя з цим
погодилась («інколи міняємося, це не буде видно ніде, але хай буде так»).
Дні — за Python (пн=0 … нд=6). Клініка без рядка тут обмежень не має — CRM
багатотенантна.
"""

WEEKDAYS = ['понеділок', 'вівторок', 'середа', 'четвер', "п'ятниця", 'субота', 'неділя']

_DERHACHOVA = 'Дергачова Катерина Олександрівна'
_SERHIIENKO = 'Сергієнко Катерина Денисівна'
_SUVOROVA = 'Суворова Анна Володимирівна'

DOCTOR_BY_WEEKDAY = {
    1: {0: _SERHIIENKO, 1: _DERHACHOVA, 2: _SUVOROVA, 3: _SERHIIENKO,
        4: _DERHACHOVA, 5: _DERHACHOVA, 6: _DERHACHOVA},
}
EXOTIC_DAYS_BY_ORG = {1: (1, 4, 5, 6)}    # Kizuna: вт, пт, сб, нд — дні Дергачової
SURGERY_DAYS_BY_ORG = {1: (1, 4, 5, 6)}   # операції — теж лише в її дні
NOT_EXOTIC = ('dog', 'cat')
# Значення «Причина звернення» у формі на сайті, що означають операцію.
# «Стоматологія» — теж: чистка й видалення зубів у клініці = операції (Катя, 12.10.2026).
SITE_SURGERY_SERVICES = ('Хірургія / операція', 'Стерилізація / кастрація', 'Стоматологія')


def _pk(org):
    return getattr(org, 'pk', None)


def days_text(days):
    return ', '.join(WEEKDAYS[d] for d in (days or ()))


def doctor_on(org, day):
    """Лікар, який за постійним графіком приймає цього дня, або ''."""
    return DOCTOR_BY_WEEKDAY.get(_pk(org), {}).get(day.weekday(), '')


def doctors_week_text(org):
    week = DOCTOR_BY_WEEKDAY.get(_pk(org))
    if not week:
        return ''
    return '; '.join(f'{WEEKDAYS[d]} — {week[d]}' for d in sorted(week))


def exotic_days(org):
    return EXOTIC_DAYS_BY_ORG.get(_pk(org))


def surgery_days(org):
    return SURGERY_DAYS_BY_ORG.get(_pk(org))


def is_exotic(species):
    """Екзот = відомий вид, що не собака і не кіт. Порожній вид — НЕ екзот
    (невідомо — не блокуємо, щоб не відсікти собаку з незаповненим полем)."""
    return bool(species) and species not in NOT_EXOTIC


def is_site_surgery(service):
    return (service or '').strip() in SITE_SURGERY_SERVICES


def exotic_blocked(org, species, day):
    days = exotic_days(org)
    return bool(days) and is_exotic(species) and day.weekday() not in days


def surgery_blocked(org, day):
    days = surgery_days(org)
    return bool(days) and day.weekday() not in days


def exotic_refusal(org):
    return ('Кроликів, гризунів, птахів і рептилій у нас приймає окремий лікар — лише: '
            f'{days_text(exotic_days(org))}. Оберіть, будь ласка, один із цих днів.')


def surgery_refusal(org, service=''):
    what = ('Чистку та видалення зубів' if (service or '').strip() == 'Стоматологія'
            else 'Операції')
    return (f'{what} у нас проводять лише: {days_text(surgery_days(org))}. '
            'Оберіть, будь ласка, один із цих днів.')
