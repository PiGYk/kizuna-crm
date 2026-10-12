"""Дні прийому ЕКЗОТІВ — усіх тварин, крім собак і котів.

Екзотів у клініці приймає окремий лікар, і лише у свої дні. Народжено скаргою
Каті 12.10.2026: і бот у Telegram, і форма запису на сайті записували кроликів,
гризунів і птахів на дні, коли такого лікаря немає (кролик Чуча — на середу,
потім на четвер). Тут одне джерело правди для обох каналів запису.

Дні — за Python (пн=0 … нд=6). Клініка без рядка в EXOTIC_DAYS_BY_ORG обмеження
не має — CRM багатотенантна.
"""

EXOTIC_DAYS_BY_ORG = {1: (1, 4, 5, 6)}   # Kizuna: вівторок, п'ятниця, субота, неділя
NOT_EXOTIC = ('dog', 'cat')
WEEKDAYS = ['понеділок', 'вівторок', 'середа', 'четвер', "п'ятниця", 'субота', 'неділя']


def exotic_days(org):
    """Дні прийому екзотів для клініки або None, якщо обмеження немає."""
    return EXOTIC_DAYS_BY_ORG.get(getattr(org, 'pk', None))


def is_exotic(species):
    """Екзот = відомий вид, що не собака і не кіт. Порожній вид — НЕ екзот
    (невідомо — не блокуємо, щоб не відсікти собаку з незаповненим полем)."""
    return bool(species) and species not in NOT_EXOTIC


def exotic_days_text(org):
    return ', '.join(WEEKDAYS[d] for d in (exotic_days(org) or ()))


def blocked(org, species, day):
    """True, якщо екзота на цей день записувати не можна."""
    days = exotic_days(org)
    return bool(days) and is_exotic(species) and day.weekday() not in days


def refusal_text(org):
    return ('Кроликів, гризунів, птахів і рептилій у нас приймає окремий лікар — лише: '
            f'{exotic_days_text(org)}. Оберіть, будь ласка, один із цих днів.')
