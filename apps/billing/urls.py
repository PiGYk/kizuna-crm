from django.urls import path
from django.http import HttpResponse

app_name = 'billing'

stub = lambda r: HttpResponse('Coming soon')

urlpatterns = [
    path('create/', stub, name='create'),
]
