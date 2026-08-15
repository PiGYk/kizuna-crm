from django.urls import path
from django.views.generic import RedirectView
from . import views

app_name = 'services'

urlpatterns = [
    path('', views.ServiceListView.as_view(), name='list'),
    path('create/', views.service_create, name='create'),
    path('import/', views.service_import, name='import'),
    path('import/execute/', views.service_import_execute, name='import_execute'),
    path('import/template/', views.service_import_template, name='import_template'),
    # Старий /<pk>/ редиректить на edit (зберігаємо для існуючих посилань / закладок)
    path('<int:pk>/', RedirectView.as_view(pattern_name='services:edit', permanent=False), name='detail'),
    path('<int:pk>/edit/', views.service_update, name='edit'),
    path('<int:pk>/delete/', views.service_delete, name='delete'),
]
