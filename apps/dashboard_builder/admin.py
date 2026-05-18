from django.contrib import admin

from .models import Dashboard


@admin.register(Dashboard)
class DashboardAdmin(admin.ModelAdmin):
    list_display = ('name', 'organization', 'owner', 'is_default', 'sort_order', 'updated_at')
    list_filter = ('organization', 'is_default')
    search_fields = ('name', 'owner__username', 'organization__name')
    raw_id_fields = ('owner', 'organization')
    readonly_fields = ('created_at', 'updated_at')

    def get_queryset(self, request):
        # В адмінці показуємо все, без auto-tenant фільтрації.
        return Dashboard.all_objects.get_queryset()
