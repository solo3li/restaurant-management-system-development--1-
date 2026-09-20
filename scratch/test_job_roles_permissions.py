import os
import sys
import django
import json

# Ensure utf-8 output on Windows console
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "restaurant_system.settings")
django.setup()

from django.test import Client
from django.contrib.auth.models import User
from core.models import Tenant, Branch, JobRole, Employee, UserProfile, Order, PERMISSIONS_CATALOG

print("=== Starting Job Roles & Permissions Comprehensive Verification ===")

admin_client = Client()
res = admin_client.post("/login/", {"username": "admin", "password": "admin123"})
assert res.status_code == 302, "Admin login failed"
print("✓ Admin logged in successfully")

# 1. Setup tenant & branch matching admin
admin_user = User.objects.get(username="admin")
tenant = admin_user.profile.tenant if hasattr(admin_user, "profile") and admin_user.profile.tenant else Tenant.objects.first()
assert tenant is not None, "Tenant not found"
branch = Branch.objects.filter(tenant=tenant).first()
assert branch is not None, "Branch not found"

# 2. Test GET job roles API
res = admin_client.get("/api/job-roles/")
assert res.status_code == 200, f"Failed GET /api/job-roles/: {res.status_code}"
data = res.json()
assert data["ok"] is True
assert "roles" in data
assert "catalog" in data
print(f"✓ Retrieved {len(data['roles'])} roles and {len(data['catalog'])} permission categories")

# 3. Test POST create custom Job Role
custom_role_name = "مساعد كاشير اختباري"
# Cleanup if exists
JobRole.objects.filter(tenant=tenant, name=custom_role_name).delete()

payload = {
    "name": custom_role_name,
    "scope": "branch",
    "description": "صلاحيات محدودة للكاشير فقط بدون تعديل أو حذف أو مخزون",
    "permissions": ["pos_access", "view_orders"]
}
res = admin_client.post("/api/job-roles/", data=json.dumps(payload), content_type="application/json")
assert res.status_code == 200, f"Failed creating job role: {res.content}"
role_data = res.json()["role"]
role_id = role_data["id"]
assert role_data["name"] == custom_role_name
assert role_data["permissions_count"] == 2
print(f"✓ Created custom role: {custom_role_name} (ID: {role_id}) with permissions: {role_data['permissions']}")

# 4. Test updating Job Role permissions
update_payload = {
    "name": custom_role_name,
    "scope": "branch",
    "description": "تحديث الوصف والصلاحيات",
    "permissions": ["pos_access", "view_orders", "view_branch_dashboard"]
}
res = admin_client.post(f"/api/job-roles/{role_id}/", data=json.dumps(update_payload), content_type="application/json")
assert res.status_code == 200
role_data = res.json()["role"]
assert role_data["permissions_count"] == 3
print("✓ Updated job role permissions successfully")

# 5. Test System Role Deletion Protection
cashier_role = JobRole.objects.filter(tenant=tenant, is_system=True).first()
if cashier_role:
    res = admin_client.post(f"/api/job-roles/{cashier_role.id}/", data=json.dumps({"action": "delete"}), content_type="application/json")
    assert res.status_code == 400
    assert "لا يمكن حذف هذا المسمى الأساسي" in res.json()["error"]
    print("✓ Protected system role from deletion: OK")

# 6. Test Assigning an Employee to Custom Job Role
emp_code = "9901"
Employee.objects.filter(tenant=tenant, employee_code=emp_code).delete()
User.objects.filter(username=f"emp_{tenant.slug}_{emp_code}").delete()

emp_payload = {
    "name": "سالم الكاشير المحدود",
    "employeeCode": emp_code,
    "phone": "0550009999",
    "jobRoleId": role_id,
    "branchId": branch.id,
    "salary": 3500,
    "pin": "5566"
}
res = admin_client.post("/api/employees/create/", data=json.dumps(emp_payload), content_type="application/json")
assert res.status_code == 200, f"Failed creating employee: {res.content}"
emp_id = res.json()["id"]
emp = Employee.objects.get(id=emp_id)
assert emp.job_role_id == role_id
print(f"✓ Created employee '{emp.name}' and linked to JobRole ID {role_id}")

# 7. Test Role Deletion Protection when employees are linked
res = admin_client.post(f"/api/job-roles/{role_id}/", data=json.dumps({"action": "delete"}), content_type="application/json")
assert res.status_code == 400
assert "لوجود 1 موظف" in res.json()["error"]
print("✓ Prevented deletion of Job Role with active assigned employee: OK")

# 8. Test Employee Login & Enforced Permissions
emp_username = f"emp_{tenant.slug}_{emp_code}"
emp_client = Client()
login_res = emp_client.post("/login/", {"username": emp_username, "password": "admin123"})
assert login_res.status_code == 302, "Employee login failed"
print(f"✓ Logged in as employee user: {emp_username}")

# Check Allowed Pages (pos_access, view_orders, view_branch_dashboard)
assert emp_client.get("/pos/").status_code == 200, "POS should be accessible"
assert emp_client.get("/branch/orders/").status_code == 200, "Branch orders should be accessible"
assert emp_client.get("/branch/").status_code == 200, "Branch dashboard should be accessible"
print("✓ Allowed pages (/pos/, /branch/orders/, /branch/) returned HTTP 200: OK")

# Check Denied Pages (inventory, branches, employees, call-center, kitchen, hq)
assert emp_client.get("/inventory/").status_code == 403, "Inventory should be FORBIDDEN"
assert emp_client.get("/branches/").status_code == 403, "Branches should be FORBIDDEN"
assert emp_client.get("/employees/").status_code == 403, "Employees should be FORBIDDEN"
assert emp_client.get("/call-center/").status_code == 403, "Call center should be FORBIDDEN"
assert emp_client.get("/kitchen/").status_code == 403, "Kitchen should be FORBIDDEN"
print("✓ Blocked pages (/inventory/, /branches/, /employees/, /call-center/, /kitchen/) returned HTTP 403: OK")

# Check Denied Action (Order deletion)
order = Order.objects.filter(tenant=tenant).first()
if order:
    del_res = emp_client.post(f"/api/orders/{order.id}/delete/")
    assert del_res.status_code == 403, "Order deletion should be FORBIDDEN"
    print("✓ Sensitive action (order deletion) blocked with HTTP 403: OK")

# 9. Test dynamically expanding role permissions and immediate effect
update_payload["permissions"].append("manage_inventory")
res = admin_client.post(f"/api/job-roles/{role_id}/", data=json.dumps(update_payload), content_type="application/json")
assert res.status_code == 200
print("✓ Dynamically added 'manage_inventory' to role permissions")

# Check that the employee can now access inventory immediately
assert emp_client.get("/inventory/").status_code == 200, "Inventory should now be accessible"
print("✓ Employee instantly granted access to /inventory/ after role update: OK")

# 10. Clean up employee and delete custom role
emp.delete()
res = admin_client.post(f"/api/job-roles/{role_id}/", data=json.dumps({"action": "delete"}), content_type="application/json")
assert res.status_code == 200
assert not JobRole.objects.filter(id=role_id).exists()
print(f"✓ Custom Job Role deleted successfully after unlinking employees")

print("\n=== ALL JOB ROLES & PERMISSIONS TESTS PASSED 100%! ===")
