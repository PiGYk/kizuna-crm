from django.urls import path
from . import views

app_name = 'finance'

urlpatterns = [
    # Витрати
    path('', views.expense_list, name='expenses'),
    path('create/', views.expense_create, name='expense_create'),
    path('<int:pk>/edit/', views.expense_edit, name='expense_edit'),
    path('<int:pk>/delete/', views.expense_delete, name='expense_delete'),

    # Постачальники
    path('suppliers/', views.supplier_list, name='suppliers'),
    path('suppliers/create/', views.supplier_create, name='supplier_create'),
    path('suppliers/<int:pk>/', views.supplier_detail, name='supplier_detail'),
    path('suppliers/<int:pk>/edit/', views.supplier_edit, name='supplier_edit'),
    path('suppliers/<int:pk>/delete/', views.supplier_delete, name='supplier_delete'),

    # Касові операції
    path('cash/', views.cash_operations, name='cash_operations'),
    path('cash/create/', views.cash_operation_create, name='cash_operation_create'),
    path('cash/<int:pk>/delete/', views.cash_operation_delete, name='cash_operation_delete'),

    # Налаштування (категорії)
    path('settings/', views.settings_view, name='settings'),
    path('settings/category/create/', views.category_create, name='category_create'),
    path('settings/category/<int:pk>/delete/', views.category_delete, name='category_delete'),

    # Звіт P&L
    path('report/', views.report_view, name='report'),
    path('report/data/', views.report_data, name='report_data'),
]
