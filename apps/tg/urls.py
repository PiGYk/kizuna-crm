from django.urls import path
from . import views

app_name = 'tg'

urlpatterns = [
    path('webhook/<slug:org_slug>/', views.webhook, name='webhook'),
    path('set-webhook/', views.set_webhook, name='set_webhook'),
    path('', views.chat_list, name='list'),
    path('<int:pk>/', views.chat_detail, name='detail'),
    path('<int:pk>/messages/', views.chat_messages, name='messages'),
    path('<int:pk>/send/', views.send_message, name='send'),
    path('<int:pk>/link/', views.link_client, name='link'),
    path('chats/', views.chat_list_partial, name='list_partial'),
    path('search-clients/', views.search_clients, name='search_clients'),
    path('send-invoice/<int:invoice_pk>/', views.send_invoice_pdf, name='send_invoice_pdf'),
    path('send-visit/<int:visit_pk>/', views.send_visit_pdf, name='send_visit_pdf'),
    path('send-analysis/<int:analysis_pk>/', views.send_analysis_photo, name='send_analysis_photo'),
]
