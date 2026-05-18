from django.urls import path
from . import views
from . import views_suppliers
from . import views_analytics

app_name = 'inventory'

urlpatterns = [
    path('', views.ProductListView.as_view(), name='list'),
    path('create/', views.ProductCreateView.as_view(), name='create'),
    path('<int:pk>/', views.ProductDetailView.as_view(), name='detail'),
    path('<int:pk>/edit/', views.ProductUpdateView.as_view(), name='edit'),
    path('<int:pk>/in/', views.stock_in, name='stock_in'),
    path('<int:pk>/adjust/', views.stock_adjust, name='stock_adjust'),
    path('<int:pk>/delete/', views.product_delete, name='delete'),
    path('bulk-delete/', views.product_bulk_delete, name='bulk_delete'),
    path('import/', views.import_upload, name='import'),
    path('import/execute/', views.import_execute, name='import_execute'),
    path('import/prices/', views.price_review, name='price_review'),
    path('template/', views.export_template, name='template'),
    path('export/', views.export_page, name='export_page'),
    path('export/download/', views.export_inventory, name='export'),
    path('settings/', views.inventory_settings, name='settings'),
    path('settings/category/create/', views.category_create, name='category_create'),
    path('settings/category/<int:pk>/delete/', views.category_delete, name='category_delete'),
    path('settings/unit/create/', views.unit_create, name='unit_create'),
    path('settings/unit/<int:pk>/delete/', views.unit_delete, name='unit_delete'),
    path('reorder/', views.reorder_view, name='reorder'),
    path('reorder/export/', views.reorder_export, name='reorder_export'),
    path('batch-intake/', views.batch_intake, name='batch_intake'),
    path('product-search/', views.product_search_json, name='product_search'),
    path('movements/', views.movements_list, name='movements'),
    path('stocktake/', views.stocktake, name='stocktake'),
    path('<int:pk>/writeoff/', views.stock_writeoff, name='writeoff'),
    path('suppliers/', views_suppliers.supplier_list, name='supplier_list'),
    path('suppliers/create/', views_suppliers.supplier_create, name='supplier_create'),
    path('suppliers/<int:pk>/', views_suppliers.supplier_detail, name='supplier_detail'),
    path('suppliers/<int:pk>/edit/', views_suppliers.supplier_edit, name='supplier_edit'),
    path('suppliers/<int:pk>/delete/', views_suppliers.supplier_delete, name='supplier_delete'),
    path('<int:pk>/quick-intake/', views.quick_intake_modal, name='quick_intake'),
    path('analytics/', views_analytics.inventory_analytics, name='analytics'),
]
