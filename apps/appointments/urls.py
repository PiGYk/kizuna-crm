from django.urls import path
from . import views

app_name = 'appointments'

urlpatterns = [
    path('', views.calendar_view, name='calendar'),
    path('create/', views.appointment_create, name='create'),
    path('<int:pk>/edit/', views.appointment_edit, name='edit'),
    path('<int:pk>/status/', views.appointment_status, name='status'),
    path('<int:pk>/delete/', views.appointment_delete, name='delete'),
    path('patient-options/', views.patient_options, name='patient_options'),
]
