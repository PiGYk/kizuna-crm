from django.urls import path
from . import views

app_name = 'tg'

urlpatterns = [
    path('broadcast/', views.broadcast_list, name='broadcast_list'),
    path('broadcast/new/', views.broadcast_create, name='broadcast_create'),
    path('broadcast/<int:pk>/', views.broadcast_detail, name='broadcast_detail'),
    path('broadcast/<int:pk>/send/', views.broadcast_send, name='broadcast_send'),
    path('webhook/<slug:org_slug>/', views.webhook, name='webhook'),
    path('set-webhook/', views.set_webhook, name='set_webhook'),
    path('', views.chat_list, name='list'),
    path('<int:pk>/', views.chat_detail, name='detail'),
    path('<int:pk>/messages/', views.chat_messages, name='messages'),
    path('<int:pk>/send/', views.send_message, name='send'),
    path('<int:pk>/link/', views.link_client, name='link'),
    path('<int:pk>/invite-register/', views.invite_register, name='invite_register'),
    path('chats/', views.chat_list_partial, name='list_partial'),
    path('search-clients/', views.search_clients, name='search_clients'),
    path('search-lead-chats/', views.search_lead_chats, name='search_lead_chats'),
    path('send-invoice/<int:invoice_pk>/', views.send_invoice_pdf, name='send_invoice_pdf'),
    path('send-visit/<int:visit_pk>/', views.send_visit_pdf, name='send_visit_pdf'),
    path('send-analysis/<int:analysis_pk>/', views.send_analysis_photo, name='send_analysis_photo'),
    path('<int:pk>/avatar/', views.chat_avatar, name='avatar'),
    path('<int:pk>/toggle-staff/', views.chat_toggle_staff, name='toggle_staff'),
    path('send-ultrasound/<int:report_pk>/', views.send_ultrasound_pdf, name='send_ultrasound_pdf'),
]
