from django.contrib import admin
from .models import Customer, Order, OrderItem


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "tenant", "phone", "address", "created_at")
    list_filter = ("tenant",)
    search_fields = ("name", "phone", "address")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("order_number", "tenant", "order_type", "channel", "branch", "customer_name", "total", "status", "created_at")
    list_filter = ("tenant", "order_type", "channel", "status", "branch")
    search_fields = ("order_number", "customer_name", "customer_phone")
    inlines = [OrderItemInline]
