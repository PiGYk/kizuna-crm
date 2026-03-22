from django.urls import path
from . import views

app_name = 'billing'

urlpatterns = [
    path('', views.invoice_list, name='list'),
    path('create/', views.invoice_create, name='create'),
    path('<int:pk>/', views.invoice_detail, name='detail'),
    path('<int:pk>/edit/', views.invoice_edit, name='edit'),
    path('<int:pk>/pay/', views.pay_invoice, name='pay'),
    path('<int:pk>/cancel/', views.cancel_invoice, name='cancel'),
    path('<int:pk>/pdf/', views.invoice_pdf, name='pdf'),
    path('<int:pk>/add-line/', views.add_line, name='add_line'),
    path('<int:pk>/remove-line/<int:line_id>/', views.remove_line, name='remove_line'),
    path('<int:pk>/update-discount/', views.update_discount, name='update_discount'),
    path('client-search/', views.client_search, name='client_search'),
    path('patients/<int:client_id>/', views.patient_list, name='patient_list'),
    path('service-components/<int:service_id>/', views.service_components, name='service_components'),
]
