from django.urls import path
from . import views

app_name = 'clients'

urlpatterns = [
    path('', views.ClientListView.as_view(), name='list'),
    path('create/', views.ClientCreateView.as_view(), name='create'),
    path('<int:pk>/', views.ClientDetailView.as_view(), name='detail'),
    path('<int:pk>/edit/', views.ClientUpdateView.as_view(), name='edit'),
    path('<int:client_pk>/patients/create/', views.patient_create, name='patient_create'),
    path('patients/<int:pk>/', views.PatientDetailView.as_view(), name='patient_detail'),
    path('patients/<int:pk>/edit/', views.patient_update, name='patient_edit'),
    path('search/', views.client_search, name='search'),
]
