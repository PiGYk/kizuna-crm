"""Закриття розділів за налаштуванням «Доступ до меню» (01.11.2026).

Вимкнений для ролі пункт ховався лише з бічного меню, а сторінка відкривалась за прямим
посиланням: перевірка на вході була тільки в «Графіку роботи». Тут — сторінки кожного пункту
за іменем адреси. Дії, якими користуються з інших сторінок (надіслати протокол чи рахунок у
Telegram з картки, вебхук бота), не закриваємо — інакше лікар без «Telegram чатів» не надіслав
би власнику протокол прийому. «Рахунки (всі)» сторінку не закривають, а звужують список до
своїх рахунків (apps/billing/views.py).
"""
from django.core.exceptions import PermissionDenied

_SECTIONS = {
    'telegram': ('tg:list', 'tg:list_partial', 'tg:detail', 'tg:messages', 'tg:send', 'tg:edit_message',
                 'tg:delete_message', 'tg:link', 'tg:search_clients', 'tg:search_lead_chats',
                 'tg:toggle_staff', 'tg:invite_register'),
    'broadcast': ('tg:broadcast_list', 'tg:broadcast_create', 'tg:broadcast_detail', 'tg:broadcast_send'),
    'analytics': ('analytics:index', 'analytics:data', 'analytics:profit', 'analytics:profit_data',
                  'analytics:usage', 'analytics:usage_data', 'analytics:payroll'),
    'revenue': ('analytics:services',),
    'debtors': ('analytics:debtors',),
    'finance': ('finance:expenses', 'finance:expense_create', 'finance:expense_edit', 'finance:expense_delete',
                'finance:suppliers', 'finance:supplier_create', 'finance:supplier_detail', 'finance:supplier_edit',
                'finance:supplier_delete', 'finance:cash_operations', 'finance:cash_operation_create',
                'finance:cash_operation_delete', 'finance:settings', 'finance:settings_balance_update',
                'finance:category_create', 'finance:category_delete', 'finance:report', 'finance:report_data'),
}
SECTION_BY_VIEW = {view: item for item, views in _SECTIONS.items() for view in views}


class MenuAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        match = getattr(request, 'resolver_match', None)
        item = SECTION_BY_VIEW.get(match.view_name) if match else None
        if item is None:
            return None
        user = getattr(request, 'user', None)
        org = getattr(request, 'organization', None)
        if not user or not user.is_authenticated or user.is_superuser or org is None:
            return None
        if not org.can_see_menu(getattr(user, 'role', None), item):
            raise PermissionDenied
        return None
