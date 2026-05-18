from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Lookup dict по ключу в шаблоні: dict|get_item:key"""
    if dictionary is None:
        return []
    return dictionary.get(key, [])
