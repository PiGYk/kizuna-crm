from django.urls import path
from . import views

app_name = 'appointments'

urlpatterns = [
    path('', views.calendar_view, name='calendar'),
    path('day/', views.calendar_day_view, name='calendar_day'),
    path('create/', views.appointment_create, name='create'),
    path('<int:pk>/edit/', views.appointment_edit, name='edit'),
    path('<int:pk>/status/', views.appointment_status, name='status'),
    path('<int:pk>/visit/', views.appointment_visit, name='visit'),
    path('<int:pk>/delete/', views.appointment_delete, name='delete'),
    path('patient-options/', views.patient_options, name='patient_options'),
    path('<int:pk>/move/', views.appointment_move, name='move'),
    path('client-by-phone/', views.client_by_phone, name='client_by_phone'),
    path('quick-client/', views.quick_create_client_patient, name='quick_client'),
    path('patient-search/', views.patient_search, name='patient_search'),
    path('client-search/', views.client_search, name='client_search'),
]
