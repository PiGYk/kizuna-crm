"""Бланки лабораторних аналізів (ANVAR 01.11.2026: «хоча б бланки під біохімію, гематологію,
цитологію, гістологію — вносити дані й друкувати з програми»).

Норми — типові референтні інтервали аналізаторів IDEXX (Catalyst, ProCyte Dx), переведені в
одиниці СІ. Вони орієнтовні: у кожного аналізатора й лабораторії свої. Тому норму можна змінити
прямо в бланку, і клініка її запам'ятовує (Organization.lab_norms) — наступний бланк для того ж
виду тварини підставить уже норму клініки. Для видів, крім собаки й кота, норм за замовчуванням
нема — лікар вписує сам.
"""
from decimal import Decimal, InvalidOperation

# code, назва, одиниця, {вид: (від, до)}
_BIOCHEMISTRY = [
    ('glu', 'Глюкоза', 'ммоль/л', {'dog': ('4.11', '7.94'), 'cat': ('3.94', '8.83')}),
    ('urea', 'Сечовина', 'ммоль/л', {'dog': ('2.5', '9.6'), 'cat': ('5.7', '12.9')}),
    ('crea', 'Креатинін', 'мкмоль/л', {'dog': ('44', '159'), 'cat': ('71', '212')}),
    ('tp', 'Загальний білок', 'г/л', {'dog': ('52', '82'), 'cat': ('57', '89')}),
    ('alb', 'Альбумін', 'г/л', {'dog': ('23', '40'), 'cat': ('22', '40')}),
    ('glob', 'Глобуліни', 'г/л', {'dog': ('25', '45'), 'cat': ('28', '51')}),
    ('alt', 'АЛТ', 'Од/л', {'dog': ('10', '125'), 'cat': ('12', '130')}),
    ('ast', 'АСТ', 'Од/л', {'dog': ('0', '50'), 'cat': ('0', '48')}),
    ('alkp', 'Лужна фосфатаза', 'Од/л', {'dog': ('23', '212'), 'cat': ('14', '111')}),
    ('ggt', 'ГГТ', 'Од/л', {'dog': ('0', '11'), 'cat': ('0', '4')}),
    ('tbil', 'Білірубін загальний', 'мкмоль/л', {'dog': ('0', '15'), 'cat': ('0', '15')}),
    ('chol', 'Холестерин', 'ммоль/л', {'dog': ('2.84', '8.26'), 'cat': ('1.68', '5.81')}),
    ('trig', 'Тригліцериди', 'ммоль/л', {'dog': ('0.11', '1.13'), 'cat': ('0.11', '1.13')}),
    ('amyl', 'Амілаза', 'Од/л', {'dog': ('500', '1500'), 'cat': ('500', '1500')}),
    ('lipa', 'Ліпаза', 'Од/л', {'dog': ('200', '1800'), 'cat': ('100', '1400')}),
    ('ca', 'Кальцій', 'ммоль/л', {'dog': ('1.98', '3.00'), 'cat': ('1.95', '2.83')}),
    ('phos', 'Фосфор', 'ммоль/л', {'dog': ('0.81', '2.20'), 'cat': ('1.00', '2.42')}),
    ('na', 'Натрій', 'ммоль/л', {'dog': ('144', '160'), 'cat': ('150', '165')}),
    ('k', 'Калій', 'ммоль/л', {'dog': ('3.5', '5.8'), 'cat': ('3.5', '5.8')}),
    ('cl', 'Хлор', 'ммоль/л', {'dog': ('109', '122'), 'cat': ('112', '129')}),
]

_HEMATOLOGY = [
    ('wbc', 'Лейкоцити (WBC)', '×10⁹/л', {'dog': ('5.05', '16.76'), 'cat': ('2.87', '17.02')}),
    ('rbc', 'Еритроцити (RBC)', '×10¹²/л', {'dog': ('5.65', '8.87'), 'cat': ('6.54', '12.20')}),
    ('hgb', 'Гемоглобін (HGB)', 'г/л', {'dog': ('131', '205'), 'cat': ('98', '162')}),
    ('hct', 'Гематокрит (HCT)', '%', {'dog': ('37.3', '61.7'), 'cat': ('30.3', '52.3')}),
    ('mcv', 'Середній об\'єм еритроцита (MCV)', 'фл', {'dog': ('61.6', '73.5'), 'cat': ('35.9', '53.1')}),
    ('mch', 'Вміст гемоглобіну в еритроциті (MCH)', 'пг', {'dog': ('21.2', '25.9'), 'cat': ('11.8', '17.3')}),
    ('mchc', 'Концентрація гемоглобіну (MCHC)', 'г/л', {'dog': ('320', '379'), 'cat': ('281', '358')}),
    ('rdw', 'Ширина розподілу еритроцитів (RDW)', '%', {'dog': ('13.6', '21.7'), 'cat': ('15.0', '27.0')}),
    ('retic', 'Ретикулоцити', '×10⁹/л', {'dog': ('10', '110'), 'cat': ('3', '50')}),
    ('neu', 'Нейтрофіли', '×10⁹/л', {'dog': ('2.95', '11.64'), 'cat': ('2.30', '10.29')}),
    ('lym', 'Лімфоцити', '×10⁹/л', {'dog': ('1.05', '5.10'), 'cat': ('0.92', '6.88')}),
    ('mono', 'Моноцити', '×10⁹/л', {'dog': ('0.16', '1.12'), 'cat': ('0.05', '0.67')}),
    ('eos', 'Еозинофіли', '×10⁹/л', {'dog': ('0.06', '1.23'), 'cat': ('0.17', '1.57')}),
    ('baso', 'Базофіли', '×10⁹/л', {'dog': ('0.00', '0.10'), 'cat': ('0.01', '0.26')}),
    ('plt', 'Тромбоцити (PLT)', '×10⁹/л', {'dog': ('148', '484'), 'cat': ('151', '600')}),
]

PANELS = {
    'biochemistry': _BIOCHEMISTRY,
    'hematology': _HEMATOLOGY,
    'cytology': [],
    'histology': [],
    'other': [],
}
# у цих бланках головне — опис під мікроскопом і висновок, а не таблиця чисел
DESCRIPTIVE = ('cytology', 'histology')
SHORT = {'biochemistry': 'Б/Х', 'hematology': 'ЗАК', 'cytology': 'ЦИТ', 'histology': 'ГІСТ', 'other': 'АН'}

MAX_ROWS = 80
_LIMITS = {'code': 20, 'name': 80, 'unit': 20, 'value': 30, 'low': 15, 'high': 15}


def template_rows(panel, species, clinic_norms=None, clinic_templates=None):
    """Порожні рядки бланку. Перелік показників — свій клініки (Organization.lab_templates, ANVAR 02.11:
    «у різних аналізаторів різні показники й норми»): для цього виду, інакше перелік з іншого виду;
    нема свого — типовий. Норма: збережена клінікою для виду → зі свого бланку → типова."""
    own = (clinic_norms or {}).get(species, {})
    typical = {code: norms.get(species, ('', '')) for code, _, _, norms in PANELS.get(panel, [])}
    tpl = (clinic_templates or {}).get(panel) or {}
    if tpl:
        base = tpl.get(species)
        same_species = base is not None
        if not same_species:
            base = next(iter(tpl.values()))
        rows = []
        for r in base:
            code = r.get('code', '')
            stored = (r.get('low', ''), r.get('high', '')) if same_species else ('', '')
            low, high = own.get(code) or (stored if any(stored) else typical.get(code, ('', '')))
            rows.append({'code': code, 'name': r.get('name', ''), 'unit': r.get('unit', ''), 'value': '', 'low': low, 'high': high})
        return rows
    rows = []
    for code, name, unit, norms in PANELS.get(panel, []):
        low, high = own.get(code) or norms.get(species, ('', ''))
        rows.append({'code': code, 'name': name, 'unit': unit, 'value': '', 'low': low, 'high': high})
    return rows


def merge_rows(panel, species, saved, clinic_norms=None, clinic_templates=None):
    """Для редагування: збережені рядки + незаповнені показники бланку, щоб їх можна було дописати."""
    have = {r.get('code') or r.get('name') for r in saved}
    extra = [r for r in template_rows(panel, species, clinic_norms, clinic_templates)
             if (r['code'] or r['name']) not in have]
    return list(saved) + extra


def template_from_post(post):
    """Перелік показників для «запам'ятати як бланк клініки»: назви, одиниці, норми — без результатів."""
    return [{k: r[k] for k in ('code', 'name', 'unit', 'low', 'high')} for r in rows_from_post(post, keep_empty=True)]


def rows_from_post(post, keep_empty=False):
    """Рядки з форми. Зберігаємо лише показники зі значенням (і назвою); keep_empty — для
    повторного показу форми з помилкою, щоб не загубити жодного рядка."""
    cols = {k: post.getlist(f'row_{k}') for k in _LIMITS}
    n = min(len(cols['name']), MAX_ROWS)
    rows = []
    for i in range(n):
        row = {k: (cols[k][i] if i < len(cols[k]) else '').strip()[:lim] for k, lim in _LIMITS.items()}
        if row['name'] and (row['value'] or keep_empty):
            rows.append(row)
    return rows


def to_number(text):
    try:
        return Decimal(str(text).strip().replace(',', '.').replace(' ', ''))
    except (InvalidOperation, ValueError):
        return None


def flag(row):
    """'high' / 'low' / '' — лише коли і значення, і межа читаються як числа."""
    value = to_number(row.get('value', ''))
    if value is None:
        return ''
    high, low = to_number(row.get('high', '')), to_number(row.get('low', ''))
    if high is not None and value > high:
        return 'high'
    if low is not None and value < low:
        return 'low'
    return ''


def learn_norms(rows, species, clinic_norms):
    """Норми, які лікар змінив у бланку, клініка запам'ятовує для цього виду. Повертає
    оновлений словник або None, якщо нічого не змінилось."""
    if not species:
        return None
    defaults = {code: norms.get(species, ('', '')) for panel in PANELS.values() for code, _, _, norms in panel}
    norms = {k: dict(v) for k, v in (clinic_norms or {}).items()}
    own = norms.setdefault(species, {})
    changed = False
    for r in rows:
        code = r.get('code')
        if code not in defaults:
            continue
        pair = [r.get('low', ''), r.get('high', '')]
        current = own.get(code) or list(defaults[code])
        if list(current) != pair:
            if pair == list(defaults[code]):
                own.pop(code, None)
            else:
                own[code] = pair
            changed = True
    return norms if changed else None


def uk_number(text):
    """Для друку: десяткова кома в усіх числах бланку (лікар пише і «6,1», і «18.4»)."""
    text = str(text or '')
    return text.replace('.', ',') if to_number(text) is not None else text
