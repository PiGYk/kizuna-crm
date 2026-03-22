from django.contrib import admin
from .models import Client, Patient


class PatientInline(admin.TabularInline):
    model = Patient
    extra = 0
    fields = ('name', 'species', 'breed', 'sex', 'date_of_birth')


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ('last_name', 'first_name', 'phone', 'email', 'created_at')
    search_fields = ('last_name', 'first_name', 'phone')
    inlines = [PatientInline]


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ('name', 'species', 'breed', 'client', 'assigned_doctor')
    list_filter = ('species', 'sex')
    search_fields = ('name', 'client__last_name')
