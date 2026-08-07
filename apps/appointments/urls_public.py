from django.urls import path
from . import public_api, widget

urlpatterns = [
    path('slots/', public_api.slots_view, name='public_slots'),
    path('lead/', public_api.lead_view, name='public_lead'),
    path('widget.js', widget.widget_js, name='public_widget_js'),
]
