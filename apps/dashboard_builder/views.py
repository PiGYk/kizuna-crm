"""Views для редагованого дашборда.

WIDGETS registry (інший агент пише `apps/dashboard_builder/widgets.py`)
очікувана структура запису:

    WIDGETS[widget_key] = {
        'label': str,                 # людська назва віджета
        'icon': str,                  # SVG-path або emoji
        'category': str,              # 'KPI', 'Списки', 'Графіки', 'Системне'
        'default_w': int,             # ширина у клітинках 12-колоночної сітки
        'default_h': int,             # висота у клітинках
        'min_w': int,
        'min_h': int,
        'roles_allowed': List[str],   # default ['admin','doctor','assistant']
        'render': Callable[[request, config: dict], str],  # повертає HTML
        'config_fields': List[dict],  # поля для модалки налаштувань
    }
"""

import json

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .defaults import get_default_layout
from .models import Dashboard


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _user_role(user) -> str:
    return getattr(user, 'role', 'admin') or 'admin'


def _extract_name(request) -> str:
    """Дістати поле `name` з form-data АБО JSON body, без RawPostDataException."""
    # Form-data POST уже зчитав body — пробуємо POST спочатку
    name = (request.POST.get('name') or '').strip()
    if name:
        return name
    # JSON: безпечно — якщо POST пустий, body ще не торкався
    try:
        payload = json.loads(request.body or b'{}')
        return (payload.get('name') or '').strip()
    except (json.JSONDecodeError, ValueError, Exception):
        return ''


def _accessible_dashboards(user):
    """QuerySet дашбордів, доступних користувачу: власні + спільні організації.

    Завдяки OrgManager автоматично відфільтровані по поточній організації.
    """
    return Dashboard.objects.filter(Q(owner=user) | Q(owner__isnull=True))


def _resolve_default_dashboard(user):
    """Повертає дашборд за замовчуванням для юзера: власний → спільний → None."""
    own_default = (
        Dashboard.objects
        .filter(owner=user, is_default=True)
        .order_by('sort_order', 'id')
        .first()
    )
    if own_default:
        return own_default
    shared_default = (
        Dashboard.objects
        .filter(owner__isnull=True, is_default=True)
        .order_by('sort_order', 'id')
        .first()
    )
    return shared_default


def _ensure_dashboard_for_user(user, organization):
    """Якщо у юзера немає жодного — створює; інакше повертає існуючий."""
    role = _user_role(user)
    # Спершу пробуємо знайти ЛЮБИЙ власний дашборд (на випадок якщо is_default
    # був зкинутий вручну в адмінці, або колізія імені).
    existing = (
        Dashboard.objects
        .filter(owner=user)
        .order_by('sort_order', 'id')
        .first()
    )
    if existing:
        return existing
    # Створюємо з get_or_create щоб не падати на UniqueConstraint.
    dashboard, _ = Dashboard.objects.get_or_create(
        organization=organization,
        owner=user,
        name='Мій дашборд',
        defaults={
            'layout': get_default_layout(role),
            'is_default': True,
            'sort_order': 0,
        },
    )
    return dashboard


def _load_widget_registry():
    """Лазі-імпорт WIDGETS, бо файл пише інший агент і його може ще не бути."""
    try:
        from apps.dashboard_builder.widgets import WIDGETS  # type: ignore
    except ImportError:
        WIDGETS = {}
    return WIDGETS


def _widget_allowed_for(role: str, widget_meta: dict) -> bool:
    allowed_roles = widget_meta.get('roles_allowed') or ['admin', 'doctor', 'assistant']
    return role in allowed_roles


# ---------------------------------------------------------------------------
# Main views
# ---------------------------------------------------------------------------

@login_required
def dashboard_view(request, pk=None):
    """Головна сторінка дашборда. Підтримує `?id=N` або URL `/<pk>/`."""
    organization = getattr(request, 'organization', None)
    if organization is None:
        return render(request, 'dashboard_builder/main.html', {
            'dashboards': [],
            'current': None,
            'current_dashboard': None,
            'layout': [],
            'widgets_registry': {},
            'is_owner': False,
            'no_organization': True,
        })

    dashboard = None
    requested_id = pk or request.GET.get('id')
    if requested_id and str(requested_id).isdigit():
        dashboard = (
            _accessible_dashboards(request.user)
            .filter(pk=int(requested_id))
            .first()
        )
        if dashboard is None:
            return HttpResponseForbidden('Дашборд не знайдено або немає доступу')

    if dashboard is None:
        dashboard = _resolve_default_dashboard(request.user)

    if dashboard is None:
        dashboard = _ensure_dashboard_for_user(request.user, organization)

    dashboards = list(
        _accessible_dashboards(request.user).order_by('sort_order', 'name')
    )

    role = _user_role(request.user)
    widgets_registry = _load_widget_registry()
    # Метадані віджетів для фронта (без callable!) — JSON-серіалізабельні.
    widgets_meta = {
        key: {
            'label': meta.get('label', key),
            'icon': meta.get('icon', ''),
            'category': meta.get('category', ''),
            'default_w': meta.get('default_w', 3),
            'default_h': meta.get('default_h', 2),
            'min_w': meta.get('min_w', 1),
            'min_h': meta.get('min_h', 1),
            'allowed': _widget_allowed_for(role, meta),
        }
        for key, meta in widgets_registry.items()
    }

    can_edit = dashboard.can_edit(request.user)

    # Збагачуємо layout полями для frontend (config_json, config_qs, label, has_settings)
    enriched_layout = []
    for item in (dashboard.layout or []):
        widget_key = item.get('type') or item.get('widget_key')
        meta = widgets_registry.get(widget_key, {}) if widget_key else {}
        config = item.get('config') if isinstance(item.get('config'), dict) else {}
        try:
            from urllib.parse import urlencode
            config_qs = urlencode({k: v for k, v in config.items() if v is not None})
        except Exception:
            config_qs = ''
        enriched_layout.append({
            **item,
            'widget_key': widget_key,
            'config': config,
            'config_json': json.dumps(config),
            'config_qs': config_qs,
            'label': meta.get('label', widget_key or ''),
            'has_settings': bool(meta.get('config_fields')),
        })

    return render(request, 'dashboard_builder/main.html', {
        'dashboards': dashboards,
        'current': dashboard,
        'current_dashboard': dashboard,
        'layout': enriched_layout,
        'layout_json': json.dumps(enriched_layout),
        'widgets_registry': widgets_meta,
        'widgets_registry_json': json.dumps(widgets_meta),
        'can_edit': can_edit,
        'is_owner': can_edit,
        'role': role,
    })


@login_required
@require_POST
def dashboard_create_view(request):
    """Створити новий пустий дашборд для поточного юзера."""
    organization = getattr(request, 'organization', None)
    if organization is None:
        return JsonResponse({'ok': False, 'error': 'no_organization'}, status=400)

    name = _extract_name(request)
    if not name:
        return JsonResponse({'ok': False, 'error': 'name_required'}, status=400)
    if len(name) > 100:
        return JsonResponse({'ok': False, 'error': 'name_too_long'}, status=400)

    # Унікальність (org, owner, name).
    if Dashboard.objects.filter(owner=request.user, name=name).exists():
        return JsonResponse({'ok': False, 'error': 'name_exists'}, status=409)

    dashboard = Dashboard.objects.create(
        organization=organization,
        owner=request.user,
        name=name,
        layout=[],
        is_default=False,
        sort_order=0,
    )
    return JsonResponse({
        'ok': True,
        'id': dashboard.id,
        'url': f"{reverse('dashboard_builder:index')}?id={dashboard.id}",
    })


@login_required
@require_POST
def dashboard_save_layout(request, pk):
    """Зберегти layout (PATCH-style POST з JSON body)."""
    dashboard = get_object_or_404(_accessible_dashboards(request.user), pk=pk)
    if not dashboard.can_edit(request.user):
        return JsonResponse({'ok': False, 'error': 'forbidden'}, status=403)

    try:
        payload = json.loads(request.body or b'{}')
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'invalid_json'}, status=400)

    layout = payload.get('layout')
    if not isinstance(layout, list):
        return JsonResponse({'ok': False, 'error': 'layout_must_be_list'}, status=400)

    # Базова валідація елементів.
    import uuid
    cleaned = []
    for item in layout:
        if not isinstance(item, dict):
            continue
        widget_type = item.get('type') or item.get('widget_key')
        if not isinstance(widget_type, str) or not widget_type:
            continue
        widget_id = item.get('widget_id')
        if not isinstance(widget_id, str) or not widget_id:
            widget_id = f'w_{uuid.uuid4().hex[:8]}'
        cleaned.append({
            'type': widget_type,
            'widget_id': widget_id,
            'x': int(item.get('x', 0) or 0),
            'y': int(item.get('y', 0) or 0),
            'w': max(1, int(item.get('w', 3) or 3)),
            'h': max(1, int(item.get('h', 2) or 2)),
            'config': item.get('config') if isinstance(item.get('config'), dict) else {},
        })

    dashboard.layout = cleaned
    dashboard.save(update_fields=['layout', 'updated_at'])

    return JsonResponse({'ok': True, 'count': len(cleaned)})


@login_required
@require_POST
def dashboard_delete(request, pk):
    """Видалити дашборд. Власник або admin для спільних."""
    dashboard = get_object_or_404(_accessible_dashboards(request.user), pk=pk)
    if not dashboard.can_edit(request.user):
        return JsonResponse({'ok': False, 'error': 'forbidden'}, status=403)
    dashboard.delete()
    return JsonResponse({'ok': True})


@login_required
@require_POST
def dashboard_set_default(request, pk):
    """Зробити дашборд дефолтним. Знімає is_default з інших цього ж юзера."""
    dashboard = get_object_or_404(_accessible_dashboards(request.user), pk=pk)
    if not dashboard.can_edit(request.user):
        return JsonResponse({'ok': False, 'error': 'forbidden'}, status=403)

    with transaction.atomic():
        # Знімаємо is_default з власних або зі спільних — залежно від типу.
        if dashboard.owner_id is None:
            Dashboard.objects.filter(owner__isnull=True, is_default=True).update(is_default=False)
        else:
            Dashboard.objects.filter(owner=dashboard.owner, is_default=True).update(is_default=False)
        dashboard.is_default = True
        dashboard.save(update_fields=['is_default', 'updated_at'])

    return JsonResponse({'ok': True})


# ---------------------------------------------------------------------------
# Widget rendering
# ---------------------------------------------------------------------------

@login_required
def widget_data_view(request, widget_key):
    """Рендерить HTML віджета (HTMX-friendly).

    Конфіг приймає з GET-параметрів; кожен параметр стає ключем у dict `config`.
    """
    widgets = _load_widget_registry()
    meta = widgets.get(widget_key)
    if meta is None:
        return HttpResponse(
            f'<div class="text-sm text-red-500 p-3">Віджет «{widget_key}» не знайдено</div>',
            status=404,
        )

    role = _user_role(request.user)
    if not _widget_allowed_for(role, meta):
        return HttpResponse(
            '<div class="text-sm text-white/50 p-3">Доступ обмежено</div>',
            status=403,
        )

    render_fn = meta.get('render')
    if not callable(render_fn):
        return HttpResponse(
            f'<div class="text-sm text-red-500 p-3">Віджет «{widget_key}» не має render-функції</div>',
            status=500,
        )

    config = {k: v for k, v in request.GET.items()}

    try:
        html = render_fn(request, config)
    except Exception as exc:  # noqa: BLE001 — віджет може кинути будь-що, ловимо
        return HttpResponse(
            f'<div class="text-sm text-red-500 p-3">Помилка віджета: {exc.__class__.__name__}</div>',
            status=500,
        )

    if not isinstance(html, str):
        html = str(html)
    return HttpResponse(html)


@login_required
def widget_catalog_view(request):
    """Модалка каталогу віджетів — фільтр по `roles_allowed` для поточної ролі."""
    widgets = _load_widget_registry()
    role = _user_role(request.user)

    available = []
    for key, meta in widgets.items():
        if not _widget_allowed_for(role, meta):
            continue
        available.append({
            'key': key,
            'label': meta.get('label', key),
            'icon': meta.get('icon', ''),
            'category': meta.get('category', 'Інше'),
            'default_w': meta.get('default_w', 3),
            'default_h': meta.get('default_h', 2),
            'min_w': meta.get('min_w', 1),
            'min_h': meta.get('min_h', 1),
        })

    # Групуємо по категоріях для зручності рендера.
    by_category = {}
    for w in available:
        by_category.setdefault(w['category'], []).append(w)

    # Конвертуємо в list-of-dicts формат який очікує шаблон ([{name, widgets: [...]}, ...])
    # Сортуємо категорії: KPI → Списки → Графіки → Системне → Інше
    cat_order = {'KPI': 1, 'Списки': 2, 'Графіки': 3, 'Системне': 4}
    catalog_list = [
        {'name': name, 'widgets': sorted(ws, key=lambda x: x['label'])}
        for name, ws in sorted(by_category.items(), key=lambda kv: cat_order.get(kv[0], 99))
    ]

    return render(request, 'dashboard_builder/_widget_catalog.html', {
        'widgets': available,
        'catalog': catalog_list,
        'widgets_by_category': by_category,
        'role': role,
    })


@login_required
def widget_settings_view(request, widget_key):
    """Форма налаштувань віджета — повертає HTML модалки."""
    widgets = _load_widget_registry()
    meta = widgets.get(widget_key)
    if meta is None:
        return HttpResponse(
            f'<div class="text-sm text-red-500 p-3">Віджет «{widget_key}» не знайдено</div>',
            status=404,
        )
    role = _user_role(request.user)
    if not _widget_allowed_for(role, meta):
        return HttpResponse(
            '<div class="text-sm text-white/50 p-3">Доступ обмежено</div>',
            status=403,
        )

    config_fields = meta.get('config_fields', [])
    current_config = {k: v for k, v in request.GET.items() if k != 'widget_id'}
    widget_id = request.GET.get('widget_id', '')

    return render(request, 'dashboard_builder/_widget_settings.html', {
        'widget_key': widget_key,
        'widget_id': widget_id,
        'label': meta.get('label', widget_key),
        'icon': meta.get('icon', ''),
        'config_fields': config_fields,
        'current_config': current_config,
    })


@login_required
@require_POST
def dashboard_rename_view(request, pk):
    """Перейменування дашборда (POST з полем `name`)."""
    dashboard = get_object_or_404(_accessible_dashboards(request.user), pk=pk)
    if not dashboard.can_edit(request.user):
        return JsonResponse({'ok': False, 'error': 'forbidden'}, status=403)

    name = _extract_name(request)
    if not name:
        return JsonResponse({'ok': False, 'error': 'name_required'}, status=400)
    if len(name) > 100:
        return JsonResponse({'ok': False, 'error': 'name_too_long'}, status=400)

    dashboard.name = name
    dashboard.save(update_fields=['name', 'updated_at'])
    return JsonResponse({'ok': True, 'name': name})
