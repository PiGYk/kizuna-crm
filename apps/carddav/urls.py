from django.urls import path
from . import views, setup_views

app_name = 'carddav'

urlpatterns = [
    # CardDAV protocol endpoints
    path('<str:username>/', views.carddav_root, name='root'),
    path('<str:username>/addressbooks/', views.carddav_home, name='home'),
    path('<str:username>/addressbooks/clients/', views.carddav_addressbook, name='addressbook'),
    path('<str:username>/addressbooks/clients/<int:client_pk>.vcf', views.carddav_vcard, name='vcard'),
]

# UI urls (включаємо окремо у config/urls.py під /carddav-setup/)
setup_urlpatterns = [
    path('', setup_views.setup_page, name='setup'),
    path('regenerate/', setup_views.regenerate_token, name='regenerate'),
]
