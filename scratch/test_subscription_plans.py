import os
import sys
import django
import json
from decimal import Decimal
from datetime import timedelta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "restaurant_system.settings")
django.setup()

from django.test import Client
from django.utils import timezone
from django.contrib.auth.models import User
from core.models import Tenant, Branch, Employee, UserProfile, SubscriptionPlan, SAAS_FEATURES_CATALOG

print("=== Starting SaaS Subscription Plans & Limits Enforcement Tests ===")

admin_client = Client()
res = admin_client.post("/login/", {"username": "admin", "password": "admin123"})
assert res.status_code == 302, "Superadmin login failed"
print("✓ Superadmin logged in successfully")

# 1. Test GET Subscription Plans
res = admin_client.get("/api/platform/plans/")
assert res.status_code == 200
data = res.json()
assert data["ok"] is True
assert len(data["plans"]) >= 4
assert len(data["catalog"]) == len(SAAS_FEATURES_CATALOG)
print(f"✓ Retrieved {len(data['plans'])} plans and {len(data['catalog'])} feature flags: OK")

# 2. Test Creating a Custom Restricted Plan
test_plan_code = "starter-test"
SubscriptionPlan.objects.filter(code=test_plan_code).delete()

new_plan_payload = {
    "name": "باقة المبتدئين الاختبارية",
    "code": test_plan_code,
    "description": "باقة فرع واحد وموظف واحد فقط بدون كول سنتر أو مخزون",
    "price_monthly": 150.0,
    "price_yearly": 1500.0,
    "max_branches": 1,
    "max_employees": 1,
    "features": ["pos", "kds", "menu_management"],
    "trial_days": 7,
    "is_active": True,
    "is_popular": False,
    "ordering": 10,
}
res = admin_client.post("/api/platform/plans/", data=json.dumps(new_plan_payload), content_type="application/json")
assert res.status_code == 200, f"Plan creation failed: {res.content}"
plan_data = res.json()["plan"]
test_plan_id = plan_data["id"]
assert plan_data["max_branches"] == 1
assert plan_data["max_employees"] == 1
print(f"✓ Created custom test plan (ID: {test_plan_id}) with limits: 1 branch, 1 employee")

# 3. Test Updating Plan
update_plan_payload = {
    "name": "باقة المبتدئين المعدلة",
    "price_monthly": 199.0,
    "max_branches": 1,
    "max_employees": 1,
    "features": ["pos", "kds", "menu_management"],
}
res = admin_client.post(f"/api/platform/plans/{test_plan_id}/", data=json.dumps(update_plan_payload), content_type="application/json")
assert res.status_code == 200
print("✓ Updated plan successfully via API")

# 4. Setup Isolated Test Tenant
test_tenant_slug = "sub-test-tenant"
Tenant.objects.filter(slug=test_tenant_slug).delete()
User.objects.filter(username=f"owner_{test_tenant_slug}").delete()

test_tenant = Tenant.objects.create(
    name="مطعم التجربة المحدود",
    slug=test_tenant_slug,
    logo_emoji="☕",
    subscription_plan_id=test_plan_id,
    subscription_status="active",
    billing_cycle="monthly",
    subscription_start=timezone.now(),
    subscription_end=timezone.now() + timedelta(days=30),
    is_active=True,
)
owner_user = User.objects.create_user(
    username=f"owner_{test_tenant_slug}",
    password="password123",
    first_name="مالك التجربة"
)
UserProfile.objects.create(
    user=owner_user,
    tenant=test_tenant,
    role="owner",
    is_platform_admin=False
)
print(f"✓ Created test tenant [{test_tenant.name}] linked to restricted plan")

# 5. Non-Superadmin Security: Tenant Owner cannot edit or create platform plans
tenant_client = Client()
tenant_client.post("/login/", {"username": f"owner_{test_tenant_slug}", "password": "password123"})
sec_res = tenant_client.post("/api/platform/plans/", data=json.dumps(new_plan_payload), content_type="application/json")
assert sec_res.status_code == 403, "Regular tenant owner must NOT be allowed to create SaaS plans"
print("✓ Platform plan creation forbidden to non-superadmin: OK (403)")

# 6. Test Branch Limit Enforcement
# Add 1st branch -> Allowed (0 -> 1)
assert test_tenant.can_add_branch() is True
b1 = Branch.objects.create(tenant=test_tenant, name="فرع 1 الرئيسي", status="active")
print("✓ Added 1st branch (current: 1 / limit: 1)")

# Try to add 2nd branch via API -> Must be rejected
assert test_tenant.can_add_branch() is False
branch_payload = {"name": "فرع 2 الزائد عن الباقة"}
res = tenant_client.post("/api/branches/create/", data=json.dumps(branch_payload), content_type="application/json")
assert res.status_code == 400
assert "استنفدت الحد الأقصى للفروع" in res.json()["error"]
print("✓ Branch limit enforced: blocked adding 2nd branch (HTTP 400 with upgrade prompt)")

# 7. Test Employee Limit Enforcement
# Add 1st employee -> Allowed (0 -> 1)
assert test_tenant.can_add_employee() is True
emp1 = Employee.objects.create(tenant=test_tenant, name="موظف 1", employee_code="801", branch=b1, role="cashier")
print("✓ Added 1st employee (current: 1 / limit: 1)")

# Try to add 2nd employee via API -> Must be rejected
assert test_tenant.can_add_employee() is False
emp_payload = {
    "name": "موظف 2 الزائد عن الباقة",
    "employeeCode": "802",
    "role": "cashier",
    "branchId": b1.id,
    "salary": 3000
}
res = tenant_client.post("/api/employees/create/", data=json.dumps(emp_payload), content_type="application/json")
assert res.status_code == 400
assert "استنفدت الحد الأقصى للموظفين" in res.json()["error"]
print("✓ Employee limit enforced: blocked adding 2nd employee (HTTP 400 with upgrade prompt)")

# 8. Test Feature Gating (Call Center & Inventory NOT in starter-test plan)
assert test_tenant.has_feature("call_center") is False
assert test_tenant.has_feature("inventory") is False

cc_res = tenant_client.get("/call-center/")
assert cc_res.status_code == 403
assert "غير مفعلة في باقة اشتراك هذا المطعم" in cc_res.content.decode("utf-8")
print("✓ Call Center view blocked because plan lacks 'call_center' feature: OK (403)")

inv_res = tenant_client.get("/inventory/")
assert inv_res.status_code == 403
assert "غير مفعلة في باقة اشتراك هذا المطعم" in inv_res.content.decode("utf-8")
print("✓ Inventory view blocked because plan lacks 'inventory' feature: OK (403)")

# 9. Test Plan Upgrade via Superadmin API
pro_plan = SubscriptionPlan.objects.get(code="pro")
sub_upgrade_payload = {
    "plan_id": pro_plan.id,
    "status": "active",
    "billing_cycle": "yearly",
    "extend_days": 365,
}
res = admin_client.post(f"/api/platform/tenants/{test_tenant.id}/subscription/", data=json.dumps(sub_upgrade_payload), content_type="application/json")
assert res.status_code == 200, f"Upgrade failed: {res.content}"
test_tenant.refresh_from_db()
assert test_tenant.subscription_plan_id == pro_plan.id
print(f"✓ Upgraded tenant [{test_tenant.name}] to Pro Plan via Superadmin API")

# 10. Verify that after upgrade, limits & features are instantly unlocked
assert test_tenant.can_add_branch() is True
assert test_tenant.can_add_employee() is True
assert test_tenant.has_feature("call_center") is True
assert test_tenant.has_feature("inventory") is True

# Adding 2nd branch now succeeds
b2_payload = {"name": "فرع 2 بعد الترقية"}
res = tenant_client.post("/api/branches/create/", data=json.dumps(b2_payload), content_type="application/json")
assert res.status_code == 200
print("✓ Successfully added 2nd branch after plan upgrade: OK")

# Accessing Call center and Inventory now succeeds (200 OK)
assert tenant_client.get("/call-center/").status_code == 200
assert tenant_client.get("/inventory/").status_code == 200
print("✓ Call Center and Inventory immediately accessible after plan upgrade: OK (200)")

# 11. Test Plan Deletion Protection when a tenant is linked
res = admin_client.post(f"/api/platform/plans/{pro_plan.id}/", data=json.dumps({"action": "delete"}), content_type="application/json")
assert res.status_code == 400
assert "لوجود" in res.json()["error"]
print("✓ Deletion of plan with active subscribers safely blocked: OK (400)")

# 12. Clean up test tenant & delete custom starter plan
test_tenant.delete()
owner_user.delete()
res = admin_client.post(f"/api/platform/plans/{test_plan_id}/", data=json.dumps({"action": "delete"}), content_type="application/json")
assert res.status_code == 200
assert not SubscriptionPlan.objects.filter(id=test_plan_id).exists()
print("✓ Cleaned up test tenant and deleted custom plan successfully")

print("\n=== ALL SAAS SUBSCRIPTION PLANS & LIMITS TESTS PASSED 100%! ===")
