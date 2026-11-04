"""Фон сторінок клініки (Налаштування → Дизайн): «Сірий» (ANVAR 02.11) або свій колір (ANVAR 04.11: «на моєму
моніторі сірий недостатньо сірий — мені треба самому вибрати колір»). Картки світліші за сторінку, поля ще
світліші — у тій самій пропорції, з якої вийшов «Сірий»; base.html бере кольори зі змінних --kz-*."""
import re

_HEX = re.compile(r'^#[0-9A-Fa-f]{6}$')
GRAY = {'page': '#DFE2E6', 'card': '#EEF0F2', 'muted': '#E6E8EB', 'field': '#F7F8F9'}   # «Сірий» з 02.11
# Темніший фон — сірі підписи на самій сторінці перестають читатись (контраст < ~4:1)
MIN_LUMINANCE = 0.55


def _rgb(color):
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def _toward_white(color, share):
    return '#' + ''.join(f'{round(c + (255 - c) * share):02X}' for c in _rgb(color))


def luminance(color):
    """Відносна яскравість кольору за WCAG (0 — чорний, 1 — білий)."""
    def lin(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in _rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def is_color(value):
    return bool(_HEX.match(value or ''))


def page_palette(kind, color=''):
    """{'page', 'card', 'muted', 'field'} або None — світлий фон, як був."""
    if kind == 'gray':
        return GRAY
    if kind == 'custom' and is_color(color):
        return {'page': color.upper(), 'card': _toward_white(color, 0.5),
                'muted': _toward_white(color, 0.25), 'field': _toward_white(color, 0.8)}
    return None
