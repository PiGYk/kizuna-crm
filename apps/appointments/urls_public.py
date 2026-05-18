from django.urls import path
from . import public_api

urlpatterns = [
    path('slots/', public_api.slots_view, name='public_slots'),
    path('lead/', public_api.lead_view, name='public_lead'),
]
