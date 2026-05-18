"""Публічне API прайс-листа для сайтів клінік (per-org).

Раніше API було жорстко прив'язане до однієї клініки (Kizuna Clinic, org_id=1).
Тепер кожна клініка отримує свій ендпойнт через ?org=<slug>. Для multi-tenant
SaaS це must-have — інакше всі сайти клініток отримували б один і той самий
прайс.
"""
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import cache_page
from django.views.decorators.vary import vary_on_headers

from apps.clinic.models import Organization
from .models import Service, ServiceCategory

_CORS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
}

# Жорсткі ліміти для query string (anti-abuse)
_MAX_CATEGORY_NAME_LEN = 200
_MAX_CATEGORY_ID = 2_147_483_647  # PostgreSQL int32 max
_MAX_ORG_SLUG_LEN = 80


def _cors(response):
    for k, v in _CORS.items():
        response[k] = v
    return response


def _parse_category_id(raw):
    """Безпечно парсить category_id. Повертає int або None."""
    if not raw:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0 or value > _MAX_CATEGORY_ID:
        return None
    return value


def _parse_category_name(raw):
    """Безпечно нормалізує category name. Повертає рядок або None."""
    if not raw:
        return None
    # Django вже URL-decoded query params у request.GET
    name = raw.strip()
    if not name:
        return None
    if len(name) > _MAX_CATEGORY_NAME_LEN:
        name = name[:_MAX_CATEGORY_NAME_LEN]
    return name


def _parse_org_slug(raw):
    """Безпечно нормалізує org slug."""
    if not raw:
        return None
    slug = raw.strip().lower()
    if not slug or len(slug) > _MAX_ORG_SLUG_LEN:
        return None
    return slug


@cache_page(60 * 5, key_prefix='pricelist_v2')  # 5 хвилин; cache_page включає QUERY_STRING у ключ
@vary_on_headers('Accept-Encoding')
def pricelist_view(request):
    """GET /api/public/pricelist/?org=<slug>

    Повертає JSON з категоріями і послугами де `show_on_website=True`
    для заданої організації.

    Query params:
        org=SLUG           — REQUIRED. Slug організації (Organization.slug).
        category=NAME      — фільтр по точному імені ServiceCategory.name (URL-decoded).
        category_id=N      — фільтр по pk категорії (швидше).

    Якщо обидва передані — пріоритет у category_id.
    Якщо org param відсутній або клініка не активна — 400/404.
    """
    org_slug = _parse_org_slug(request.GET.get('org'))
    if not org_slug:
        return _cors(JsonResponse({'error': 'org param required'}, status=400))

    org = get_object_or_404(Organization, slug=org_slug, is_active=True)

    category_id = _parse_category_id(request.GET.get('category_id'))
    category_name = _parse_category_name(request.GET.get('category'))

    services_qs = (
        Service._base_manager
        .filter(organization=org, is_active=True, show_on_website=True)
        .select_related('category')
    )

    # Якщо запитана конкретна категорія — перевіряємо її існування першим
    if category_id is not None or category_name is not None:
        cat_filter = {'organization': org}
        if category_id is not None:
            cat_filter['pk'] = category_id
        else:
            cat_filter['name'] = category_name

        target_cat = ServiceCategory._base_manager.filter(**cat_filter).first()

        if target_cat is None:
            # Категорії нема — м'яко повертаємо порожньо
            return _cors(JsonResponse({
                'clinic': org.name,
                'currency': 'UAH',
                'count': 0,
                'categories': [],
            }))

        services_qs = services_qs.filter(category_id=target_cat.pk)

    services = services_qs.order_by('category__sort_order', 'category__name', 'name')

    # Згрупувати за категорією
    cats_data = {}
    for s in services:
        cat_name = s.category.name if s.category else 'Інше'
        cat_sort = s.category.sort_order if s.category else 9999
        if cat_name not in cats_data:
            cats_data[cat_name] = {
                'name': cat_name,
                'sort_order': cat_sort,
                'services': [],
            }
        cats_data[cat_name]['services'].append({
            'name': s.name,
            'price': float(s.price),
            'description': s.description or '',
        })

    categories = sorted(cats_data.values(), key=lambda c: c['sort_order'])

    return _cors(JsonResponse({
        'clinic': org.name,
        'currency': 'UAH',
        'count': sum(len(c['services']) for c in categories),
        'categories': categories,
    }))
