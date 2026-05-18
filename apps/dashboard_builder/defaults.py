"""Дефолтні layout-и для нового дашборда — за роллю користувача.

Сітка: 12 колонок (w в межах 1-12), h — кількість рядків (~80px кожен).
Ключі віджетів мають збігатися з ключами в `apps.dashboard_builder.widgets.WIDGETS`.
"""
import copy
import uuid


def _wid():
    return f'w_{uuid.uuid4().hex[:8]}'


# Базові віджети для admin/doctor (з фінансами).
_FULL_LAYOUT = [
    {'type': 'kpi_clients_total',      'widget_id': _wid(), 'x': 0, 'y': 0, 'w': 3, 'h': 2, 'config': {}},
    {'type': 'kpi_patients_total',     'widget_id': _wid(), 'x': 3, 'y': 0, 'w': 3, 'h': 2, 'config': {}},
    {'type': 'kpi_revenue_today',      'widget_id': _wid(), 'x': 6, 'y': 0, 'w': 3, 'h': 2, 'config': {}},
    {'type': 'kpi_invoices_today',     'widget_id': _wid(), 'x': 9, 'y': 0, 'w': 3, 'h': 2, 'config': {}},
    {'type': 'list_today_appointments','widget_id': _wid(), 'x': 0, 'y': 2, 'w': 6, 'h': 4, 'config': {}},
    {'type': 'list_low_stock',         'widget_id': _wid(), 'x': 6, 'y': 2, 'w': 6, 'h': 4, 'config': {}},
    {'type': 'list_top_services_revenue','widget_id': _wid(), 'x': 0, 'y': 6, 'w': 4, 'h': 4, 'config': {'period': 'month'}},
    {'type': 'list_recent_invoices',   'widget_id': _wid(), 'x': 4, 'y': 6, 'w': 8, 'h': 4, 'config': {}},
    {'type': 'chart_revenue_week',     'widget_id': _wid(), 'x': 0, 'y':10, 'w': 6, 'h': 4, 'config': {}},
    {'type': 'chart_visits_per_doctor','widget_id': _wid(), 'x': 6, 'y':10, 'w': 4, 'h': 4, 'config': {}},
    {'type': 'list_overdue_vaccines',  'widget_id': _wid(), 'x': 0, 'y':14, 'w': 6, 'h': 4, 'config': {}},
    {'type': 'list_debtors',           'widget_id': _wid(), 'x': 6, 'y':14, 'w': 6, 'h': 4, 'config': {}},
]

# Для асистента — без фінансових.
_ASSISTANT_LAYOUT = [
    {'type': 'kpi_clients_total',       'widget_id': _wid(), 'x': 0, 'y': 0, 'w': 3, 'h': 2, 'config': {}},
    {'type': 'kpi_patients_total',      'widget_id': _wid(), 'x': 3, 'y': 0, 'w': 3, 'h': 2, 'config': {}},
    {'type': 'kpi_appointments_today',  'widget_id': _wid(), 'x': 6, 'y': 0, 'w': 3, 'h': 2, 'config': {}},
    {'type': 'kpi_overdue_vaccines',    'widget_id': _wid(), 'x': 9, 'y': 0, 'w': 3, 'h': 2, 'config': {}},
    {'type': 'list_today_appointments', 'widget_id': _wid(), 'x': 0, 'y': 2, 'w': 6, 'h': 4, 'config': {}},
    {'type': 'list_low_stock',          'widget_id': _wid(), 'x': 6, 'y': 2, 'w': 6, 'h': 4, 'config': {}},
    {'type': 'list_overdue_vaccines',   'widget_id': _wid(), 'x': 0, 'y': 6, 'w': 6, 'h': 4, 'config': {}},
    {'type': 'list_top_services_month', 'widget_id': _wid(), 'x': 6, 'y': 6, 'w': 6, 'h': 4, 'config': {}},
    {'type': 'chart_appointments_week', 'widget_id': _wid(), 'x': 0, 'y':10, 'w': 8, 'h': 4, 'config': {}},
    {'type': 'shifts_who_works_now',    'widget_id': _wid(), 'x': 8, 'y':10, 'w': 4, 'h': 2, 'config': {}},
    {'type': 'quick_actions',           'widget_id': _wid(), 'x': 8, 'y':12, 'w': 4, 'h': 2, 'config': {}},
]


DEFAULT_LAYOUT_BY_ROLE = {
    'admin': _FULL_LAYOUT,
    'doctor': _FULL_LAYOUT,
    'assistant': _ASSISTANT_LAYOUT,
}


def get_default_layout(role: str) -> list:
    """Повертає копію дефолтного layout для вказаної ролі (з новими widget_id)."""
    base = DEFAULT_LAYOUT_BY_ROLE.get(role, _FULL_LAYOUT)
    layout = copy.deepcopy(base)
    # Перегенеруємо widget_id для кожного юзера, щоб не дублювалися
    for item in layout:
        item['widget_id'] = _wid()
    return layout
