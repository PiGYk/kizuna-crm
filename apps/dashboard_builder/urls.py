from django.urls import path

from .views import (
    dashboard_create_view,
    dashboard_delete,
    dashboard_rename_view,
    dashboard_save_layout,
    dashboard_set_default,
    dashboard_view,
    widget_catalog_view,
    widget_data_view,
    widget_settings_view,
)

app_name = 'dashboard_builder'

urlpatterns = [
    # Index
    path('', dashboard_view, name='dashboard'),
    path('', dashboard_view, name='index'),
    # Detail by pk
    path('<int:pk>/', dashboard_view, name='dashboard_detail'),
    # CRUD operations
    path('create/', dashboard_create_view, name='dashboard_create'),
    path('create/', dashboard_create_view, name='create'),
    path('<int:pk>/layout/', dashboard_save_layout, name='dashboard_save_layout'),
    path('<int:pk>/layout/', dashboard_save_layout, name='save_layout'),
    path('<int:pk>/delete/', dashboard_delete, name='dashboard_delete'),
    path('<int:pk>/delete/', dashboard_delete, name='delete'),
    path('<int:pk>/default/', dashboard_set_default, name='dashboard_set_default'),
    path('<int:pk>/default/', dashboard_set_default, name='set_default'),
    path('<int:pk>/rename/', dashboard_rename_view, name='dashboard_rename'),
    # Widgets
    path('widget/<str:widget_key>/', widget_data_view, name='widget_data'),
    path('widget/<str:widget_key>/settings/', widget_settings_view, name='widget_settings'),
    path('widgets/catalog/', widget_catalog_view, name='widget_catalog'),
]
