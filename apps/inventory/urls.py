from django.urls import path
from . import views

app_name = 'inventory'

urlpatterns = [
    path('', views.ProductListView.as_view(), name='list'),
    path('create/', views.ProductCreateView.as_view(), name='create'),
    path('<int:pk>/', views.ProductDetailView.as_view(), name='detail'),
    path('<int:pk>/edit/', views.ProductUpdateView.as_view(), name='edit'),
    path('<int:pk>/in/', views.stock_in, name='stock_in'),
    path('<int:pk>/adjust/', views.stock_adjust, name='stock_adjust'),
    path('<int:pk>/delete/', views.product_delete, name='delete'),
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
]
