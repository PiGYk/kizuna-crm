from django.contrib import admin
from .models import Invoice, InvoiceLine


class InvoiceLineInline(admin.TabularInline):
    model = InvoiceLine
    extra = 0


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('pk', 'client', 'patient', 'doctor', 'status', 'total', 'date')
    list_filter = ('status',)
    inlines = [InvoiceLineInline]
