from django.contrib import admin
from .models import Appointment

@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ('starts_at', 'client', 'patient', 'doctor', 'status', 'duration')
    list_filter = ('status', 'doctor')
    search_fields = ('client__last_name', 'patient__name')
