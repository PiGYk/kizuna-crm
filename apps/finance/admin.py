from django.contrib import admin
from .models import ExpenseCategory, Supplier, Expense, CashOperation

admin.site.register(ExpenseCategory)
admin.site.register(Supplier)
admin.site.register(Expense)
admin.site.register(CashOperation)
