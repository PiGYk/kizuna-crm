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

# Загальний аналіз сечі (ANVAR 08.11.2026 — бланк під аналізатор сечі UA-60V): три розділи, як на папері.
# Коди з префіксом u_ — бо glu/ca/crea вже зайняті біохімією, а норми клініки (lab_norms) ключуються кодом.
# Норма словом («негатив») — у полі «від», «до» порожнє: результат не-негатив позначається так само, як поза нормою.
# Типові норми — лише загальновизнані (pH, питома вага, уробіліноген, осад); решту клініка вписує під свій прилад.
# Одиниці хімії — як друкує сам аналізатор (ANVAR 16.11, фото роздруківки UA-60V: mg/dL, Leu/uL, Ery/uL), щоб лікар
# переписував числа без перерахунку: «300» білка в мг/дл ≠ 300 г/л. Уробіліноген 0,2–1 мг/дл = колишні 3,2–16 мкмоль/л.
_NEG = {'dog': ('негатив', ''), 'cat': ('негатив', '')}
_URINALYSIS = [
    ('u_col', 'Колір', '', {'dog': ('жовтий', ''), 'cat': ('жовтий', '')}, 'phys'),
    ('u_cla', 'Прозорість', '', {'dog': ('прозора', ''), 'cat': ('прозора', '')}, 'phys'),
    ('u_vol', "Об'єм зразка", 'мл', {}, 'phys'),
    ('u_sgr', 'Питома вага (рефрактометр)', '', {'dog': ('1.015', '1.045'), 'cat': ('1.035', '1.060')}, 'phys'),
    ('u_leu', 'Лейкоцити (LEU)', 'лейк/мкл', _NEG, 'chem'),
    ('u_uro', 'Уробіліноген (URO)', 'мг/дл', {'dog': ('0.2', '1'), 'cat': ('0.2', '1')}, 'chem'),
    ('u_alb', 'Мікроальбумін (ALB/MA)', 'мг/л', {}, 'chem'),
    ('u_pro', 'Білок (PRO)', 'мг/дл', _NEG, 'chem'),
    ('u_bil', 'Білірубін (BIL)', 'мг/дл', _NEG, 'chem'),
    ('u_glu', 'Глюкоза (GLU)', 'мг/дл', _NEG, 'chem'),
    ('u_asc', 'Аскорбінова кислота (ASC)', 'мг/дл', _NEG, 'chem'),
    ('u_sg', 'Густина, смужка (SG)', '', {}, 'chem'),
    ('u_ket', 'Кетонові тіла (KET)', 'мг/дл', _NEG, 'chem'),
    ('u_nit', 'Нітрити (NIT)', '', _NEG, 'chem'),
    ('u_cre', 'Креатинін сечі (CRE)', 'мг/дл', {}, 'chem'),
    ('u_ph', 'Кислотність (pH)', '', {'dog': ('5.5', '7.5'), 'cat': ('6.0', '7.5')}, 'chem'),
    ('u_blo', 'Кров / гемоглобін (BLO)', 'ер/мкл', _NEG, 'chem'),
    ('u_ca', 'Кальцій (CA)', 'мг/дл', {}, 'chem'),
    ('u_acr', 'Альбумін / креатинін (ACR)', 'мг/г', {}, 'chem'),
    ('u_rbc', 'Еритроцити', 'у п/з', {'dog': ('0', '5'), 'cat': ('0', '5')}, 'micro'),
    ('u_wbc', 'Лейкоцити', 'у п/з', {'dog': ('0', '5'), 'cat': ('0', '5')}, 'micro'),
    ('u_epi', 'Епітелій', '', {}, 'micro'),
    ('u_cast', 'Циліндри', '', {}, 'micro'),
    ('u_crys', 'Кристали', '', {}, 'micro'),
    ('u_bact', 'Бактерії', '', {'dog': ('відсутні', ''), 'cat': ('відсутні', '')}, 'micro'),
    ('u_muc', 'Слиз / інше', '', {}, 'micro'),
]
GROUPS = {'phys': 'Фізичні властивості', 'chem': 'Хімічні показники (тест-смужка)', 'micro': 'Мікроскопія осаду'}
_GROUP_ORDER = {'phys': 0, 'chem': 1, 'micro': 2}
# результат числом — цифрова клавіатура; решта показників сечі — словом («негатив», «1+», «солом'яний»)
_NUMERIC_URINE = {'u_vol', 'u_sgr', 'u_sg', 'u_ph', 'u_rbc', 'u_wbc'}
# рядок опису без норми (ANVAR 16.11: «в кристалах норм нема, потрібен просто рядок опису»): широке поле на
# FREE_TEXT_MAX знаків замість числа з нормою — «трипельфосфати у значній кількості» не влазило в 30
FREE_TEXT = {'u_crys', 'u_muc'}
FREE_TEXT_MAX = 150

PANELS = {
    'biochemistry': _BIOCHEMISTRY,
    'hematology': _HEMATOLOGY,
    'urinalysis': _URINALYSIS,
    'cytology': [],
    'histology': [],
    'other': [],
}
# у цих бланках головне — опис під мікроскопом і висновок, а не таблиця чисел
DESCRIPTIVE = ('cytology', 'histology')
SHORT = {'biochemistry': 'Б/Х', 'hematology': 'ЗАК', 'urinalysis': 'ЗАС', 'cytology': 'ЦИТ', 'histology': 'ГІСТ',
         'other': 'АН'}

# Поля шапки, які є лише в окремих бланках (LabResult.extra): сеча — забір, його час, прилад, виконавець
EXTRA = {'urinalysis': (('collection', 40), ('collected_at', 16), ('device', 60), ('performer', 80))}
COLLECTION = ('вільне сечовипускання', 'цистоцентез', 'катетер')

MAX_ROWS = 80
_LIMITS = {'code': 20, 'name': 80, 'unit': 20, 'value': 30, 'low': 15, 'high': 15, 'group': 10}
# слова, що означають «нічого не знайдено» — для показників із нормою словом
_NEGATIVE = {'негатив', 'негативно', 'негативний', 'neg', 'neg.', 'negative', 'не виявлено', 'не виявлені', 'немає', 'нема',
             'відсутні', 'відсутній', 'відсутня', '-', '−', '—', '–', 'норма', 'в нормі', 'нормальний', 'norm', 'normal',
             'n', 'not detected', 'nd'}


def _spec(panel):
    """(code, назва, одиниця, норми, розділ) — розділ є лише в бланках із розділами (сеча)."""
    for item in PANELS.get(panel, []):
        code, name, unit, norms, *rest = item
        yield code, name, unit, norms, (rest[0] if rest else '')


def template_rows(panel, species, clinic_norms=None, clinic_templates=None):
    """Порожні рядки бланку. Перелік показників — свій клініки (Organization.lab_templates, ANVAR 02.11:
    «у різних аналізаторів різні показники й норми»): для цього виду, інакше перелік з іншого виду;
    нема свого — типовий. Норма: збережена клінікою для виду → зі свого бланку → типова."""
    own = (clinic_norms or {}).get(species, {})
    typical = {code: norms.get(species, ('', '')) for code, _, _, norms, _ in _spec(panel)}
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
            rows.append({'code': code, 'name': r.get('name', ''), 'unit': r.get('unit', ''), 'value': '', 'low': low,
                         'high': high, 'group': r.get('group', '')})
        return rows
    rows = []
    for code, name, unit, norms, group in _spec(panel):
        low, high = own.get(code) or norms.get(species, ('', ''))
        rows.append({'code': code, 'name': name, 'unit': unit, 'value': '', 'low': low, 'high': high, 'group': group})
    return rows


def merge_rows(panel, species, saved, clinic_norms=None, clinic_templates=None):
    """Для редагування: збережені рядки + незаповнені показники бланку, щоб їх можна було дописати."""
    have = {r.get('code') or r.get('name') for r in saved}
    extra = [r for r in template_rows(panel, species, clinic_norms, clinic_templates)
             if (r['code'] or r['name']) not in have]
    rows = list(saved) + extra
    if any(r.get('group') for r in rows):   # дописані показники — у свій розділ, а не в кінець бланку
        rows.sort(key=lambda r: _GROUP_ORDER.get(r.get('group', ''), 9))
    return rows


def template_from_post(post):
    """Перелік показників для «запам'ятати як бланк клініки»: назви, одиниці, норми — без результатів."""
    return [{k: r[k] for k in ('code', 'name', 'unit', 'low', 'high', 'group')} for r in rows_from_post(post, keep_empty=True)]


def rows_from_post(post, keep_empty=False):
    """Рядки з форми. Зберігаємо лише показники зі значенням (і назвою); keep_empty — для
    повторного показу форми з помилкою, щоб не загубити жодного рядка."""
    cols = {k: post.getlist(f'row_{k}') for k in _LIMITS}
    n = min(len(cols['name']), MAX_ROWS)
    rows = []
    for i in range(n):
        raw = {k: (cols[k][i] if i < len(cols[k]) else '').strip() for k in _LIMITS}
        row = {k: raw[k][:lim] for k, lim in _LIMITS.items()}
        if row['code'] in FREE_TEXT:
            row['value'], row['low'], row['high'] = ' '.join(raw['value'].split())[:FREE_TEXT_MAX], '', ''   # Enter у полі — пробіл
        if row['name'] and (row['value'] or keep_empty):
            rows.append(row)
    return rows


def to_number(text):
    try:
        return Decimal(str(text).strip().replace(',', '.').replace(' ', ''))
    except (InvalidOperation, ValueError):
        return None


def _negative(text):
    return str(text or '').strip().lower() in _NEGATIVE


def flag(row):
    """'high' / 'low' / '' — коли і значення, і межа читаються як числа. Норма словом «негатив» (сеча):
    будь-який інший результат — і словом («1+», «слід»), і числом більше нуля («LEU 75») — 'high'.
    Рядок опису (FREE_TEXT: кристали, слиз) норми не має — не позначається."""
    if row.get('code') in FREE_TEXT:
        return ''
    value = to_number(row.get('value', ''))
    word_norm = _negative(row.get('low', '')) and not str(row.get('high') or '').strip()
    if value is None:
        raw = str(row.get('value') or '').strip()
        return 'high' if raw and word_norm and not _negative(raw) else ''
    if word_norm:
        return 'high' if value > 0 else ''
    high, low = to_number(row.get('high', '')), to_number(row.get('low', ''))
    if high is not None and value > high:
        return 'high'
    if low is not None and value < low:
        return 'low'
    return ''


def learn_norms(rows, species, clinic_norms, clinic_templates=None):
    """Норми, які лікар змінив у бланку, клініка запам'ятовує для цього виду. Повертає
    оновлений словник або None, якщо нічого не змінилось. Показник зі свого бланку клініки, якого нема серед
    типових (білірубін прямий, MID/GRA аналізатора на три популяції — Катя 22.11), запам'ятовується так само;
    рядок без коду («+ Показник») — ні: його норму несе лише бланк клініки."""
    if not species:
        return None
    defaults = {code: norms.get(species, ('', '')) for panel in PANELS for code, _, _, norms, _ in _spec(panel)}
    for by_species in (clinic_templates or {}).values():
        for tpl_rows in by_species.values():
            for t in tpl_rows:
                if t.get('code'):
                    defaults.setdefault(t['code'], ('', ''))
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


def norm_display(row):
    """Норма для друку: «4,11 – 7,94», «негатив», «… – 5»."""
    low, high = uk_number(row.get('low')), uk_number(row.get('high'))
    if low and not high and to_number(row.get('low')) is None:
        return low
    if low or high:
        return f'{low or "…"} – {high or "…"}'
    return ''


def is_textual(row):
    """Результат словом («негатив», «1+») — у полі клавіатура з літерами, а не цифрова."""
    code, low = row.get('code') or '', row.get('low') or ''
    return (code.startswith('u_') and code not in _NUMERIC_URINE) or bool(low and to_number(low) is None)


def annotate(rows):
    """Підписи розділів, тип клавіатури і рядок опису (без норми) — для форми й друку."""
    return [{**r, 'group_label': GROUPS.get(r.get('group') or '', ''), 'textual': is_textual(r),
             'free_text': r.get('code') in FREE_TEXT} for r in rows]


def extra_from_post(panel, post):
    """Поля шапки бланку (LabResult.extra) — лише ті, що є в цьому бланку; порожні не зберігаємо."""
    out = {}
    for key, limit in EXTRA.get(panel, ()):
        value = (post.get(f'x_{key}') or '').strip()[:limit]
        if key == 'collection' and value and value not in COLLECTION:
            value = ''
        if value:
            out[key] = value
    return out
