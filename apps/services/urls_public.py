from django.urls import path
from . import public_api

urlpatterns = [
    path('pricelist/', public_api.pricelist_view, name='public_pricelist'),
]
