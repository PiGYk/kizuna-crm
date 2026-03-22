from django.contrib import admin
from .models import Unit, Product, StockMovement


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ('name', 'short')


class StockMovementInline(admin.TabularInline):
    model = StockMovement
    extra = 0
    readonly_fields = ('created_at', 'created_by')
    fields = ('type', 'quantity', 'price', 'reason', 'created_by', 'created_at')


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'unit', 'quantity', 'sell_price', 'is_active')
    list_filter = ('is_active', 'unit')
    search_fields = ('name',)
    inlines = [StockMovementInline]


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ('product', 'type', 'quantity', 'price', 'created_by', 'created_at')
    list_filter = ('type',)
