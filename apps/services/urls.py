from django.urls import path
from django.http import HttpResponse

app_name = 'services'

stub = lambda r: HttpResponse('Coming soon')

urlpatterns = [
    path('', stub, name='list'),
]
