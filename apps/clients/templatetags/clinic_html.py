"""Безпечний показ текстів прийому, які редактор зберігає як HTML.

Причина: з 18.05.2026 (коміт e6668b8) тексти візиту виводились через
`|linebreaksbr` без `|safe`, тому лікар бачив на екрані сиру розмітку
(«<p>Млявість…</p>»). 338 із 398 прийомів клініки містять теги.

Просто повернути `|safe` не можна — у полі лежить те, що ввів користувач.
Тому лишаємо вузький набір тегів форматування і вирізаємо все інше разом
з атрибутами (onclick, style, src тощо) — скрипт у картку не потрапить.
"""
from html.parser import HTMLParser
from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()

# Те, що реально ставить редактор прийому (Quill): абзаци, списки, наголоси.
ALLOWED = {
    'p', 'br', 'ul', 'ol', 'li', 'strong', 'b', 'em', 'i', 'u', 's',
    'blockquote', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'div', 'span',
}
VOID = {'br'}


class _Sanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self._open = []
        self._mute = 0          # вміст script/style не показуємо навіть текстом

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self._mute += 1
            return
        if tag not in ALLOWED:
            return
        if tag in VOID:
            self.out.append('<br>')
            return
        self.out.append('<%s>' % tag)   # атрибути відкидаємо всі
        self._open.append(tag)

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self._mute = max(0, self._mute - 1)
            return
        if tag not in ALLOWED or tag in VOID:
            return
        if tag in self._open:
            # закриваємо все, що лишилось відкритим усередині
            while self._open:
                last = self._open.pop()
                self.out.append('</%s>' % last)
                if last == tag:
                    break

    def handle_data(self, data):
        if self._mute:
            return
        self.out.append(escape(data))

    def result(self):
        while self._open:
            self.out.append('</%s>' % self._open.pop())
        return ''.join(self.out)


@register.filter(name='rich')
def rich(value):
    """HTML прийому → безпечний HTML; звичайний текст → з перенесеннями рядків."""
    if not value:
        return ''
    text = str(value)
    if '<' not in text:
        return mark_safe(escape(text).replace('\n', '<br>'))
    parser = _Sanitizer()
    parser.feed(text)
    parser.close()
    return mark_safe(parser.result())
