from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Lookup dict по ключу в шаблоні: dict|get_item:key"""
    if dictionary is None:
        return []
    return dictionary.get(key, [])


@register.filter
def staff_label(user):
    """«Катерина С.» — ім'я і перша літера прізвища (див. views_payroll._staff_label)."""
    from apps.accounts.views_payroll import _staff_label
    return _staff_label(user)
