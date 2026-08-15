from django import template

register = template.Library()

@register.filter
def dict_get(d, key):
    return d.get(key, [])


@register.filter
def tel_href(phone):
    """Номер телефону → значення для href="tel:" (цифри + провідний плюс)."""
    raw = str(phone or '').strip()
    if not raw:
        return ''
    digits = ''.join(ch for ch in raw if ch.isdigit())
    if not digits:
        return ''
    return ('+' if raw.startswith('+') else '') + digits
