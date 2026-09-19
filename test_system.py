import os
import django
import json

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "restaurant_system.settings")
django.setup()

from django.test import Client
from core.models import Branch, Employee, MenuItem, InventoryItem, Customer, Order

client = Client()

print("1. Testing unauthenticated access (should redirect to login)...")
res = client.get("/dashboard/")
assert res.status_code == 302, f"Expected 302, got {res.status_code}"
assert "/login/" in res.url, f"Expected redirect to login, got {res.url}"
print("   Unauthenticated redirect: OK")

print("2. Testing login with admin/admin123...")
res = client.post("/login/", {"username": "admin", "password": "admin123"})
assert res.status_code == 302, f"Expected 302, got {res.status_code}"
print("   Login: OK")

print("3. Testing authenticated pages...")
pages = [
    ("/dashboard/", 200),
    ("/pos/", 200),
    ("/call-center/", 200),
    ("/delivery/", 200),
    ("/inventory/", 200),
    ("/branches/", 200),
    ("/employees/", 200),
    ("/admin/", 200),
]

for url, expected in pages:
    res = client.get(url)
    assert res.status_code == expected, f"Failed {url}: expected {expected}, got {res.status_code}"
    print(f"   {url}: OK ({res.status_code})")

print("4. Testing Order Creation API...")
menu_item = MenuItem.objects.first()
branch = Branch.objects.first()
payload = {
    "type": "dine_in",
    "channel": "cashier",
    "branchId": branch.id,
    "payMethod": "cash",
    "cashier": "admin",
    "discount": 0,
    "customerName": "اختبار العميل",
    "customerPhone": "0559998877",
    "address": "الرياض، حي السليمانية",
    "items": [{"menuItemId": menu_item.id, "qty": 2}]
}
res = client.post("/api/orders/", data=json.dumps(payload), content_type="application/json")
assert res.status_code == 201, f"Expected 201, got {res.status_code}: {res.content}"
data = res.json()
created_order_id = data["order"]["id"]
print(f"   Order created successfully: {data['order']['orderNumber']} (ID: {created_order_id})")

print("5. Testing Customer search API...")
res = client.get("/api/customers/search/?q=055")
assert res.status_code == 200
cust_data = res.json()
assert len(cust_data["customers"]) > 0
print(f"   Found {len(cust_data['customers'])} customers: OK")

print("6. Testing Order Update API (advancing to preparing)...")
res = client.post(f"/api/orders/{created_order_id}/", data=json.dumps({"status": "preparing"}), content_type="application/json")
assert res.status_code == 200
assert res.json()["status"] == "preparing"
print("   Order update: OK")

print("7. Testing Menu Item toggle API...")
orig_available = menu_item.available
res = client.post(f"/api/menu/toggle/{menu_item.id}/")
assert res.status_code == 200
assert res.json()["available"] != orig_available
# toggle back
client.post(f"/api/menu/toggle/{menu_item.id}/")
print("   Menu toggle: OK")

print("8. Testing Inventory adjust API...")
inv_item = InventoryItem.objects.first()
orig_qty = inv_item.quantity
res = client.post(f"/api/inventory/adjust/{inv_item.id}/", data=json.dumps({"delta": 5}), content_type="application/json")
assert res.status_code == 200
inv_item.refresh_from_db()
assert inv_item.quantity == orig_qty + 5
print("   Inventory adjust: OK")

print("\nALL VERIFICATION TESTS PASSED SUCCESSFULLY! 100% WORKING.")
