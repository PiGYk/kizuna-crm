# -*- coding: utf-8 -*-
"""HTML-версія листів супроводу тріалу.

Верстка — : таблична (вимога поштових клієнтів),
темна гама Kizuna (#12100F / #DEAA01), шрифт Fixel з фолбеком на системний.
Текстова версія лишається в trial_emails.py і йде тим самим листом як alternative —
поштові клієнти без HTML показують її.
"""
from django.template.loader import render_to_string

CRM = 'https://crm.kizuna.com.ua'
GOLD = '#DEAA01'
FG = '#FFF7F3'
BODY = '#e6ded6'

def _p(text, last=False):
    m = '0' if last else '0 0 16px 0'
    return f'<p style="margin:{m};">{text}</p>'

def _b(text):
    return f'<b style="color:{FG};">{text}</b>'

def _steps(items):
    rows = []
    for i, t in enumerate(items, 1):
        rows.append(
            f'<tr>'
            f'<td width="28" valign="top" style="font-family:\'Fixel Display\',\'Fixel\',sans-serif;'
            f'font-size:15px;font-weight:600;color:{GOLD};line-height:26px;">{i}</td>'
            f'<td style="font-size:16px;line-height:26px;color:{BODY};">{t}</td>'
            f'</tr>'
        )
    return ('<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
            'style="margin:0 0 16px 0;">' + ''.join(rows) + '</table>')


def _plans():
    """Тарифи таблицею — у листі про гроші ціни мають читатись, а не губитись у рядку."""
    rows = []
    for label, price, note in (('Старт', '990', 'до 2 лікарів'),
                               ('Клініка', '1 990', 'звичайна клініка'),
                               ('Мережа', '3 990', 'кілька філій')):
        rows.append(
            f'<tr>'
            f'<td style="padding:8px 0;border-bottom:1px solid #2b2723;font-size:16px;'
            f'line-height:22px;color:{FG};">{label}'
            f'<span style="color:#9a9488;font-size:14px;">&nbsp;&nbsp;{note}</span></td>'
            f'<td align="right" style="padding:8px 0;border-bottom:1px solid #2b2723;'
            f"font-family:'Fixel Display','Fixel',sans-serif;font-size:16px;font-weight:600;"
            f'line-height:22px;color:{GOLD};white-space:nowrap;">{price} грн/міс</td>'
            f'</tr>'
        )
    return ('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            'border="0" style="margin:0 0 16px 0;">' + ''.join(rows) + '</table>')


def build_html(kind, *, name, clinic, ends, subject, title):
    hello = f'Вітаю, {name}!' if name else 'Вітаю!'
    c = _b(clinic)
    cta_url, cta_text, pre = CRM, 'Відкрити CRM', ''

    if kind == 'welcome':
        pre = 'Три кроки, щоб система почала бути корисною.'
        body = (_p(hello)
                + _p(f'Ви завели {c} в Kizuna CRM. Дякую, що спробували.')
                + _p('Щоб система почала бути корисною, вистачить трьох кроків:')
                + _steps(['Додайте лікарів — Налаштування, розділ Користувачі',
                          'Заведіть кількох клієнтів з тваринами',
                          'Поставте перший запис у розкладі'])
                + _p('Далі підтягнеться решта: картка тварини з історією, каса, склад ліків, '
                     'нагадування клієнтам у Телеграм.')
                + _p(f'Доступ відкритий повністю до {_b(ends)}. Нічого не обрізано — це вся система.')
                + _p('Якщо десь застрягнете, просто відповідайте на цей лист.', last=True))
        cta_text = 'Почати роботу'
    elif kind == 'day3':
        pre = 'Пʼять хвилин — і буде видно, як працює система.'
        body = (_p(hello)
                + _p(f'Ви заводили {c} в Kizuna CRM. Якщо ще не встигли розібратись — це звична '
                     'річ, на старті незрозуміло, за що хапатись.')
                + _p('Найшвидший спосіб відчути систему:')
                + _steps(['Заведіть одного клієнта з твариною',
                          'Поставте йому запис на завтра',
                          'Відкрийте картку — там уже все підтягнулось'])
                + _p('Хвилин пʼять, і стане видно, як працює решта.')
                + _p('Якщо у вас уже є база в Excel або в іншій програмі — напишіть, перенесемо. '
                     'Це безкоштовно і зазвичай займає день. Що саме не виходить? Відповідайте '
                     'прямо на цей лист.', last=True))
    elif kind == 'before5':
        pre = f'Безкоштовний доступ діє до {ends}.'
        body = (_p(hello)
                + _p(f'Безкоштовний доступ для {c} діє ще пʼять днів, до {_b(ends)}.')
                + _p('Далі система закриється, але дані нікуди не подінуться — усе, що ви завели, '
                     'лишається. Продовжите — працюєте з того самого місця.')
                + _p('Тарифи:')
                + _plans()
                + _p('Функціонал у всіх однаковий — уся система цілком. Різниця в тому, наскільки '
                     'щільно ми на звʼязку.')
                + _p('Якщо потрібні інші умови — напишіть у відповідь, домовимось.', last=True))
        cta_text = 'Продовжити доступ'
        cta_url = CRM + '/subscribe/clinic/'
    elif kind == 'before1':
        pre = f'Завтра, {ends}, доступ закриється.'
        body = (_p(hello)
                + _p(f'Нагадую: завтра, {_b(ends)}, безкоштовний період для {c} закінчується.')
                + _p('Дані залишаються на місці. Щоб не було паузи в роботі, продовжте зараз.')
                + _p('Якщо Kizuna не підійшла — напишіть одним рядком чому. Це справді допомагає.',
                     last=True))
        cta_text = 'Продовжити доступ'
        cta_url = CRM + '/subscribe/clinic/'
    elif kind == 'expired':
        pre = 'Дані збережені, доступ вмикається одразу після оплати.'
        body = (_p(hello)
                + _p(f'Безкоштовний період для {c} завершився, доступ закрито. Усе, що ви завели, '
                     'збережене — вмикається назад одразу після оплати.')
                + _p('Якщо передумали, теж нормально. Напишіть, що не зайшло: ціна, функціонал, '
                     'не той момент. Відповім на будь-яке питання.', last=True))
        cta_text = 'Поновити доступ'
        cta_url = CRM + '/subscribe/clinic/'
    else:
        raise ValueError(kind)

    return render_to_string('emails/trial_base.html', {
        'subject': subject, 'preheader': pre, 'title': title,
        'body_html': body, 'cta_url': cta_url, 'cta_text': cta_text,
    })
