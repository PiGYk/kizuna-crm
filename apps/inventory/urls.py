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
    path('import/', views.import_products, name='import'),
    path('template/', views.export_template, name='template'),
]
