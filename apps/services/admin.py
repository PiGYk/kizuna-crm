from django.contrib import admin
from .models import Service, ServiceComponent


class ComponentInline(admin.TabularInline):
    model = ServiceComponent
    extra = 0


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ('name', 'price', 'is_active')
    inlines = [ComponentInline]
