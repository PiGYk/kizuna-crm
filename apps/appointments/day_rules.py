"""Правила днів запису: хто з лікарів приймає, коли беремо екзотів, що робимо з операціями.

12.10.2026, Катя, по черзі:
- екзотів (усе, крім собак і котів) веде тільки вона — вівторок, п'ятниця, субота,
  неділя; бот і форма на сайті записували кролика Чучу на середу й четвер;
- на сайті людина має бачити, хто з лікарів приймає;
- ОПЕРАЦІЇ люди самі НЕ записують узагалі — ні на сайті, ні в боті: спершу консультація
  й діагностика, а час операції лікар підбирає сам (стерилізація кішки й собаки тривають
  по-різному, 30-хвилинний слот брехав). Замість операції — запис на консультацію.
Тут одне джерело правди для обох каналів запису.

Розклад лікарів — постійний тижневий; підміни між собою тут не видно, і Катя з цим
погодилась. Дні — за Python (пн=0 … нд=6). Клініка без рядка тут обмежень не має.
"""

WEEKDAYS = ['понеділок', 'вівторок', 'середа', 'четвер', "п'ятниця", 'субота', 'неділя']
WEEKDAYS_SHORT = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'нд']

_DERHACHOVA = 'Дергачова Катерина Олександрівна'
_SERHIIENKO = 'Сергієнко Катерина Денисівна'
_SUVOROVA = 'Суворова Анна Володимирівна'

DOCTOR_BY_WEEKDAY = {
    1: {0: _SERHIIENKO, 1: _DERHACHOVA, 2: _SUVOROVA, 3: _SERHIIENKO,
        4: _DERHACHOVA, 5: _DERHACHOVA, 6: _DERHACHOVA},
}
EXOTIC_DAYS_BY_ORG = {1: (1, 4, 5, 6)}    # Kizuna: вт, пт, сб, нд — дні Дергачової
SURGERY_DAYS_BY_ORG = {1: (1, 4, 5, 6)}   # коли проводимо операції — лише довідка клієнту
NOT_EXOTIC = ('dog', 'cat')
# «Причина звернення» на сайті, що означає операцію (чистка й видалення зубів — теж).
SITE_SURGERY_SERVICES = ('Хірургія / операція', 'Стерилізація / кастрація', 'Стоматологія')

SURGERY_CONSULT_NOTE = ('🩺 КОНСУЛЬТАЦІЯ ПЕРЕД ОПЕРАЦІЄЮ — людина хоче операцію; '
                        'час операції підберіть після огляду')
# Коротка версія — для живого сигналу бота: прев'ю там ріжеться на 150 символах.
SURGERY_CONSULT_SHORT = '🩺 Консультація перед операцією.'


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


def doctors_week_groups(org):
    """[{'days': 'пн, чт', 'name': …, 'exotic': bool}, …] — для графіка на сайті."""
    week = DOCTOR_BY_WEEKDAY.get(_pk(org))
    if not week:
        return []
    groups, order = {}, []
    for d in sorted(week):
        name = week[d]
        if name not in groups:
            groups[name] = []
            order.append(name)
        groups[name].append(d)
    ex = set(exotic_days(org) or ())
    return [{'days': ', '.join(WEEKDAYS_SHORT[d] for d in groups[n]), 'name': n,
             'exotic': bool(ex) and set(groups[n]) == ex} for n in order]


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


def exotic_refusal(org):
    return ('Кроликів, гризунів, птахів і рептилій у нас приймає окремий лікар — лише: '
            f'{days_text(exotic_days(org))}. Оберіть, будь ласка, один із цих днів.')


def surgery_consult_hint(org):
    days = days_text(surgery_days(org))
    tail = f' Самі операції проводимо: {days}.' if days else ''
    return ('На операцію спершу записуємо на консультацію: лікар огляне, за потреби '
            'призначить діагностику й разом із вами підбере час операції.' + tail)
