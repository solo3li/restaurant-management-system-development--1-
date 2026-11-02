from django.db import migrations

def backfill_order_currencies(apps, schema_editor):
    Order = apps.get_model('core', 'Order')
    from core.currencies import get_currency_info

    orders_to_update = []
    for order in Order.objects.select_related('branch', 'tenant').iterator(chunk_size=1000):
        c = "SAR"
        sym = "ر.س"
        if order.branch and getattr(order.branch, "currency", None):
            c = order.branch.currency or "SAR"
            sym = get_currency_info(c).get("symbol_ar", "ر.س")
        elif order.tenant and getattr(order.tenant, "default_currency", None):
            c = order.tenant.default_currency or "SAR"
            sym = get_currency_info(c).get("symbol_ar", "ر.س")

        order.currency = c
        order.currency_symbol = sym
        orders_to_update.append(order)
        if len(orders_to_update) >= 1000:
            Order.objects.bulk_update(orders_to_update, ["currency", "currency_symbol"])
            orders_to_update = []
    if orders_to_update:
        Order.objects.bulk_update(orders_to_update, ["currency", "currency_symbol"])

def reverse_backfill(apps, schema_editor):
    pass

class Migration(migrations.Migration):

    dependencies = [
        ('core', '0040_order_currency_order_currency_symbol'),
    ]

    operations = [
        migrations.RunPython(backfill_order_currencies, reverse_backfill),
    ]
