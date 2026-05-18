from django.contrib import admin
from .models import Appointment, LeadRequest


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ('starts_at', 'client', 'patient', 'doctor', 'status', 'duration')
    list_filter = ('status', 'doctor')
    search_fields = ('client__last_name', 'patient__name')


@admin.register(LeadRequest)
class LeadRequestAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'name', 'phone', 'pet_name', 'pet_type',
                    'service_note', 'preferred_date', 'preferred_time', 'status', 'source')
    list_filter = ('status', 'source', 'preferred_date')
    search_fields = ('name', 'phone', 'pet_name')
    list_editable = ('status',)
    readonly_fields = ('created_at', 'source', 'organization')
    ordering = ('-created_at',)
