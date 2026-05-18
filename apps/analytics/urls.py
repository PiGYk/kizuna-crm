from django.urls import path
from . import views

app_name = 'analytics'

urlpatterns = [
    path('', views.analytics_view, name='index'),
    path('data/', views.analytics_data, name='data'),
    path('payroll/', views.payroll_view, name='payroll'),
    path('debtors/', views.debtors_view, name='debtors'),
    path('services/', views.services_view, name='services'),
    path('profit/', views.profit_view, name='profit'),
    path('profit/data/', views.profit_data, name='profit_data'),
    path('usage/', views.usage_view, name='usage'),
    path('usage/data/', views.usage_data, name='usage_data'),
]
