from django.urls import path
from django.http import HttpResponse

app_name = 'clients'

stub = lambda r: HttpResponse('Coming soon')

urlpatterns = [
    path('', stub, name='list'),
    path('create/', stub, name='create'),
]
