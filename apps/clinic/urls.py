from django.urls import path
from .views import (
    BookingWidgetView,
    ClinicSettingsView,
    superadmin_dashboard,
    superadmin_toggle_active,
    superadmin_extend_trial,
    superadmin_remove_trial,
    subscribe_checkout,
    subscribe_success,
    subscribe_callback,
)

app_name = 'clinic'

urlpatterns = [
    path('settings/', ClinicSettingsView.as_view(), name='settings'),
    path('booking-widget/', BookingWidgetView.as_view(), name='booking_widget'),
]
