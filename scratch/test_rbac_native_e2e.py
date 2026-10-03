import os
import sys
import json
from decimal import Decimal

# Ensure /app is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "restaurant_system.settings")

import django
django.setup()

from django.test import Client
from django.contrib.auth.models import User, Group, Permission
from core.models import (
    Tenant, Branch, JobRole, Employee, UserProfile,
    MenuItem, Order, OrderItem, InventoryItem, DeliveryArea,
    SubscriptionPlan
)
from core.views import user_has_perm
from core.context_processors import normalize_plan_features

print("======================================================================")
print("       RUNNING COMPREHENSIVE END-TO-END RBAC NATIVE VERIFICATION      ")
print("======================================================================")

passed_tests = 0
failed_tests = 0

def assert_test(condition, description):
    global passed_tests, failed_tests
    if condition:
        print(f" [PASS] {description}")
        passed_tests += 1
    else:
        print(f"❌ [FAIL] {description}")
        failed_tests += 1

# Setup test fixtures
tenant = Tenant.objects.filter(slug="diyafa").first() or Tenant.objects.first()
branch = tenant.branches.first()
owner_user = User.objects.filter(profile__tenant=tenant, profile__role="owner").first()
if not owner_user:
    owner_user = User.objects.filter(is_superuser=True).first()

# -----------------------------------------------------------------------------
# TEST SUITE 1: Multi-Tenant & Group Permissions Architecture
# -----------------------------------------------------------------------------
print("\n--- SUITE 1: Multi-Tenant & Django Group Architecture ---")
job_roles = JobRole.objects.filter(tenant=tenant)
assert_test(job_roles.count() >= 8, f"Tenant has {job_roles.count()} configured JobRoles")

for r in job_roles:
    assert_test(r.group is not None, f"JobRole '{r.name}' is bound to Group '{r.group.name if r.group else None}'")
    assert_test(r.group.name == f"t{tenant.id}_role_{r.id}", f"Group naming strictly multi-tenant isolated: {r.group.name}")
    # Verify group.permissions matches role permissions
    group_perms = set(r.group.permissions.values_list("codename", flat=True))
    role_perms = set(r.get_permissions_list())
    assert_test(group_perms == role_perms, f"Role '{r.name}': Django Group permissions strictly match role definitions ({len(group_perms)} perms)")

# -----------------------------------------------------------------------------
# TEST SUITE 2: Dynamic Permission Addition & Real-Time Sync
# -----------------------------------------------------------------------------
print("\n--- SUITE 2: Dynamic Role Permissions Update (Zero Lag / Immediate Sync) ---")
# Create a dedicated test role and test employee
test_role_name = "E2E Test Cashier Role"
JobRole.objects.filter(tenant=tenant, name=test_role_name).delete()

test_role = JobRole.objects.create(
    tenant=tenant,
    name=test_role_name,
    scope="branch",
)
test_role.sync_with_django_group()
test_role.set_permissions(["pos_access", "pos_create_order", "view_orders"])

test_emp_code = "9988"
Employee.objects.filter(tenant=tenant, employee_code=test_emp_code).delete()
User.objects.filter(username=f"emp_diyafa_{test_emp_code}").delete()

test_user = User.objects.create(username=f"emp_diyafa_{test_emp_code}", first_name="E2E Cashier")
test_user.set_password("pass123")
test_user.save()

test_emp = Employee.objects.create(
    tenant=tenant,
    name="E2E Cashier",
    employee_code=test_emp_code,
    role="cashier",
    job_role=test_role,
    branch=branch,
    salary=Decimal("4500"),
    status="active",
    user=test_user
)
test_emp.save()

# Verify employee has user assigned to role's group
assert_test(test_emp.user.groups.filter(id=test_role.group.id).exists(), "Employee's Django User is assigned to Role's Django Group")
assert_test(test_user.has_perm("core.pos_access"), "Native user.has_perm('core.pos_access') is True")
assert_test(user_has_perm(test_user, "pos_access"), "user_has_perm(test_user, 'pos_access') is True")
assert_test(not test_user.has_perm("core.pos_apply_discount"), "Native user lacks 'pos_apply_discount' initially")
assert_test(not user_has_perm(test_user, "pos_apply_discount"), "user_has_perm(test_user, 'pos_apply_discount') is False initially")

client = Client()
client.force_login(test_user)
session = client.session
session["active_tenant_id"] = tenant.id
session["active_branch_id"] = branch.id
session.save()

# Attempt to create order with discount -> Must return 403 Forbidden!
menu_item = MenuItem.objects.filter(tenant=tenant, available=True).first()
if not menu_item:
    menu_item = MenuItem.objects.create(
        tenant=tenant,
        name="Test Item E2E",
        price=Decimal("20.00"),
        category="عام",
        available=True
    )
order_payload = {
    "branchId": branch.id,
    "items": [{"menuItemId": menu_item.id, "qty": 1}],
    "type": "dine_in",
    "channel": "cashier",
    "discount": 15.00
}
res = client.post("/api/orders/", data=json.dumps(order_payload), content_type="application/json")
assert_test(res.status_code == 403, f"api_create_order with unauthorized discount was blocked (HTTP 403): {res.json().get('error')}")

# NOW: Update the role dynamically via api_job_role_detail as the owner
owner_client = Client()
owner_client.force_login(owner_user)
owner_session = owner_client.session
owner_session["active_tenant_id"] = tenant.id
owner_session["active_branch_id"] = branch.id
owner_session.save()

update_payload = {
    "permissions": ["pos_access", "pos_create_order", "view_orders", "pos_apply_discount"]
}
role_res = owner_client.post(f"/api/job-roles/{test_role.id}/", data=json.dumps(update_payload), content_type="application/json")
assert_test(role_res.status_code == 200, "Owner successfully updated JobRole permissions via API")

# IMMEDIATELY verify: test_user now has pos_apply_discount WITHOUT re-login!
test_user.refresh_from_db()
for cache_field in ["_perm_cache", "_group_perm_cache", "_user_perm_cache"]:
    if hasattr(test_user, cache_field):
        delattr(test_user, cache_field)

assert_test(test_user.has_perm("core.pos_apply_discount"), "Immediately after role update: user.has_perm('core.pos_apply_discount') is TRUE!")
assert_test(user_has_perm(test_user, "pos_apply_discount"), "Immediately after role update: user_has_perm(test_user, 'pos_apply_discount') is TRUE!")

# Attempt to create order with discount again -> Must succeed with 201 Created!
res_after = client.post("/api/orders/", data=json.dumps(order_payload), content_type="application/json")
assert_test(res_after.status_code == 201, f"api_create_order with discount now succeeds immediately (HTTP 201): Order {res_after.json().get('order', {}).get('orderNumber')}")

# NOW: Dynamically remove pos_apply_discount again
remove_payload = {
    "permissions": ["pos_access", "pos_create_order", "view_orders"]
}
role_res2 = owner_client.post(f"/api/job-roles/{test_role.id}/", data=json.dumps(remove_payload), content_type="application/json")
assert_test(role_res2.status_code == 200, "Owner removed pos_apply_discount from role")

for cache_field in ["_perm_cache", "_group_perm_cache", "_user_perm_cache"]:
    if hasattr(test_user, cache_field):
        delattr(test_user, cache_field)

res_revoked = client.post("/api/orders/", data=json.dumps(order_payload), content_type="application/json")
assert_test(res_revoked.status_code == 403, f"Immediately after revocation: api_create_order with discount blocked again (HTTP 403): {res_revoked.json().get('error')}")

# -----------------------------------------------------------------------------
# TEST SUITE 3: Gap Verification across all System Endpoints
# -----------------------------------------------------------------------------
print("\n--- SUITE 3: Verification of Closed Permission Gaps Across Endpoints ---")

# 1. Menu item toggle availability
res_toggle_menu = client.post(f"/api/branch-menu/toggle/{menu_item.id}/")
assert_test(res_toggle_menu.status_code == 403, f"Cashier lacking menu_toggle_availability blocked from toggle-branch (HTTP 403): {res_toggle_menu.json().get('error')}")

# 2. Menu item creation
menu_payload = {"name": "Test Burger", "price": 25.0, "category": "برجر"}
res_create_menu = client.post("/api/menu/create/", data=json.dumps(menu_payload), content_type="application/json")
assert_test(res_create_menu.status_code == 403, f"Cashier lacking menu_create_item blocked from menu creation (HTTP 403): {res_create_menu.json().get('error')}")

# 3. Inventory adjustment
inv_item = InventoryItem.objects.filter(tenant=tenant).first()
if not inv_item:
    inv_item = InventoryItem.objects.create(tenant=tenant, branch=branch, name="طماطم", quantity=10, min_quantity=2)

res_inv_adj = client.post(f"/api/inventory/adjust/{inv_item.id}/", data=json.dumps({"delta": 5}), content_type="application/json")
assert_test(res_inv_adj.status_code == 403, f"Cashier lacking inventory_adjust_stock blocked from inventory adjust (HTTP 403): {res_inv_adj.json().get('error')}")

# 4. Inventory creation
inv_create_payload = {"name": "خس طازج", "branchId": branch.id, "quantity": 10, "minQuantity": 3}
res_inv_create = client.post("/api/inventory/create/", data=json.dumps(inv_create_payload), content_type="application/json")
assert_test(res_inv_create.status_code == 403, f"Cashier lacking inventory_add_stock blocked from inventory create (HTTP 403): {res_inv_create.json().get('error')}")

# 5. Branch Creation
branch_payload = {"name": "فرع غير مصرح"}
res_branch_create = client.post("/api/branches/create/", data=json.dumps(branch_payload), content_type="application/json")
assert_test(res_branch_create.status_code == 403, f"Cashier lacking branch_manage_branches blocked from branch create (HTTP 403): {res_branch_create.json().get('error')}")

# 6. Branch Toggle
res_branch_toggle = client.post(f"/api/branches/toggle/{branch.id}/")
assert_test(res_branch_toggle.status_code == 403, f"Cashier lacking branch_manage_branches blocked from branch toggle (HTTP 403): {res_branch_toggle.json().get('error')}")

# 7. Delivery Area modification
area_payload = {"action": "add", "name": "حي الملقا الجديد", "delivery_fee": 10.0}
res_delivery_area = client.post(f"/api/branches/{branch.id}/areas/", data=json.dumps(area_payload), content_type="application/json")
assert_test(res_delivery_area.status_code == 403, f"Cashier lacking delivery_manage_zones blocked from delivery area modify (HTTP 403): {res_delivery_area.json().get('error')}")

# 8. Order Cancellation via api_update_order
active_order = Order.objects.filter(tenant=tenant).exclude(status="cancelled").first()
if not active_order:
    active_order = Order.objects.create(
        tenant=tenant,
        branch=branch,
        order_number="TEST-9999",
        order_type="dine_in",
        status="pending",
        total=Decimal("50.00")
    )
res_cancel = client.post(f"/api/orders/{active_order.id}/", data=json.dumps({"status": "cancelled"}), content_type="application/json")
assert_test(res_cancel.status_code == 403, f"Cashier lacking cancel_orders blocked from cancelling order (HTTP 403): {res_cancel.json().get('error')}")

# 9. Manual Price Override in Order
order_payload_override = {
    "branchId": branch.id,
    "items": [{"menuItemId": menu_item.id, "qty": 1, "customPrice": 999.0}],
    "type": "dine_in"
}
res_override = client.post("/api/orders/", data=json.dumps(order_payload_override), content_type="application/json")
assert_test(res_override.status_code == 403, f"Cashier lacking pos_override_price blocked from custom price (HTTP 403): {res_override.json().get('error')}")

# 10. Order Refund
res_refund = client.post(f"/api/orders/{active_order.id}/", data=json.dumps({"action": "refund"}), content_type="application/json")
assert_test(res_refund.status_code == 403, f"Cashier lacking pos_refund_order blocked from refund (HTTP 403): {res_refund.json().get('error')}")

# 11. Menu Price Update
res_menu_price = client.post(f"/api/menu/{menu_item.id}/", data=json.dumps({"price": 50.0}), content_type="application/json")
assert_test(res_menu_price.status_code == 403, f"Cashier lacking menu_change_price blocked from updating price (HTTP 403): {res_menu_price.json().get('error')}")

# 12. Menu Item Delete
res_menu_del = client.post(f"/api/menu/{menu_item.id}/delete/")
assert_test(res_menu_del.status_code == 403, f"Cashier lacking menu_delete_item blocked from deleting item (HTTP 403): {res_menu_del.json().get('error')}")

# 13. AI Call Center modifications
res_callcenter = client.post("/api/ai-callcenter/profiles/create/", data=json.dumps({"name": "Unauthorized Voice Agent"}), content_type="application/json")
assert_test(res_callcenter.status_code == 403, f"Cashier lacking call_center_manage_ai blocked from AI voice agent creation (HTTP 403)")

# 14. Employee detail API security & crash prevention
res_emp_detail_unauth = client.get(f"/api/employees/{test_emp.id}/detail/")
assert_test(res_emp_detail_unauth.status_code == 403, f"Cashier lacking hr_view_employees blocked from employee detail API (HTTP 403)")

res_emp_detail_owner = owner_client.get(f"/api/employees/{test_emp.id}/detail/")
assert_test(res_emp_detail_owner.status_code == 200, f"Owner can view employee detail API without crash (HTTP 200)")
emp_detail_json = res_emp_detail_owner.json()
assert_test("employee" in emp_detail_json and emp_detail_json["employee"]["can_view_salary"] is True, "Owner can view employee salary in detail")

# 15. Customer Search Protection
chef_user = User.objects.create_user(username="temp_chef_test", password="password123")
chef_role = JobRole.objects.get(tenant=tenant, name="طاهٍ رئيسي / مطبخ")
chef_user.groups.add(chef_role.group)
chef_client = Client()
chef_client.login(username="temp_chef_test", password="password123")
res_cust_search_chef = chef_client.get("/api/customers/search/?q=050")
assert_test(res_cust_search_chef.status_code == 403, "Chef lacking pos_access and call_center_access blocked from searching customers (HTTP 403)")
chef_user.delete()

# 16. FastMCP & AI Call Center Unauthenticated Endpoint Security
anon_client = Client()
res_mcp_test = anon_client.post("/api/ai-callcenter/mcp/test-tool/", data=json.dumps({"tool_name": "get_menu"}), content_type="application/json")
assert_test(res_mcp_test.status_code == 401, "Unauthenticated request to test_mcp_tool blocked (HTTP 401)")

res_mcp_sync = anon_client.post("/api/ai-callcenter/mcp/sync/")
assert_test(res_mcp_sync.status_code == 401, "Unauthenticated request to sync_mcp blocked (HTTP 401)")

res_mcp_url = anon_client.post("/api/ai-callcenter/mcp/update-url/", data=json.dumps({"server_url": "https://evil.com"}), content_type="application/json")
assert_test(res_mcp_url.status_code == 401, "Unauthenticated request to update_mcp_url blocked (HTTP 401)")

# 17. AI Live Context APIs permission checks
res_live_ctx_sync = client.post("/api/ai-callcenter/sync-live-context/")
assert_test(res_live_ctx_sync.status_code == 403, "Cashier lacking call_center_manage_ai blocked from live context sync (HTTP 403)")

res_live_ctx_get = client.get("/api/ai-callcenter/get-live-context/")
assert_test(res_live_ctx_get.status_code == 403, "Cashier lacking call_center_manage_ai blocked from get live context (HTTP 403)")

res_add_queue_member = client.post("/api/ai-callcenter/queues/1/members/add/", data=json.dumps({"employee_id": test_emp.id}), content_type="application/json")
assert_test(res_add_queue_member.status_code == 403, "Cashier lacking call_center_manage_ai blocked from queue member add (HTTP 403)")

# 18. Django Admin JobRoleAdmin.permissions_count crash prevention
from core.admin import JobRoleAdmin
from django.contrib.admin.sites import AdminSite
admin_inst = JobRoleAdmin(JobRole, AdminSite())
count = admin_inst.permissions_count(test_role)
assert_test(count == len(test_role.get_permissions_list()), f"JobRoleAdmin.permissions_count correctly executes without AttributeError (Count: {count})")

# 19. Granular UI page access gates (Read-only / specialized roles)
# A. menu_view grants access to branch_menu_view
test_role.set_permissions(["menu_view"])
client_res_menu = client.get("/branch/menu/")
assert_test(client_res_menu.status_code == 200, "User with granular 'menu_view' allowed to access branch_menu_view (HTTP 200)")

# B. inventory_view grants access to inventory_view
test_role.set_permissions(["inventory_view"])
client_res_inv = client.get("/inventory/")
assert_test(client_res_inv.status_code == 200, "User with granular 'inventory_view' allowed to access inventory_view (HTTP 200)")

# C. hr_view_employees grants access to employees_view
test_role.set_permissions(["hr_view_employees"])
client_res_emp = client.get("/employees/")
assert_test(client_res_emp.status_code == 200, "User with granular 'hr_view_employees' allowed to access employees_view (HTTP 200)")

# D. system_manage_billing grants access to owner_subscription_view
test_role.set_permissions(["system_manage_billing"])
client_res_sub = client.get("/subscription/")
assert_test(client_res_sub.status_code == 200, "User with granular 'system_manage_billing' allowed to access owner_subscription_view (HTTP 200)")

# E. call_center_manage_ai grants access to ai_callcenter_management_view
test_role.set_permissions(["call_center_manage_ai"])
client_res_ai = client.get("/ai-callcenter/")
assert_test(client_res_ai.status_code == 200, "User with granular 'call_center_manage_ai' allowed to access ai_callcenter_management_view (HTTP 200)")

# -----------------------------------------------------------------------------
# TEST SUITE 4: Subscription Plan Feature Normalization
# -----------------------------------------------------------------------------
print("\n--- SUITE 4: Subscription Plan Feature Normalization ---")
features_raw = ["inventory_mgmt", "delivery_zones", "kds_kitchen", "pos_billing"]
normalized = normalize_plan_features(features_raw)
assert_test("inventory" in normalized, "Normalized 'inventory_mgmt' -> 'inventory' recognized")
assert_test("delivery_management" in normalized, "Normalized 'delivery_zones' -> 'delivery_management' recognized")
assert_test("kds" in normalized, "Normalized 'kds_kitchen' -> 'kds' recognized")
assert_test("pos" in normalized, "Normalized 'pos_billing' -> 'pos' recognized")

# -----------------------------------------------------------------------------
# TEST SUITE 5: Employee Lifecycle & Account Status Sync
# -----------------------------------------------------------------------------
print("\n--- SUITE 5: Employee Lifecycle & User Account Status Sync ---")

# 1. Toggle status to inactive
test_emp.status = "inactive"
test_emp.save()
test_user.refresh_from_db()
assert_test(test_user.is_active is False, "Deactivating employee automatically sets User.is_active = False")

# 2. Toggle status back to active
test_emp.status = "active"
test_emp.save()
test_user.refresh_from_db()
assert_test(test_user.is_active is True, "Reactivating employee automatically sets User.is_active = True")

# Clean up test artifacts
test_emp.delete()
test_user.delete()
test_role.delete()

print("\n======================================================================")
print(f"  VERIFICATION FINISHED: {passed_tests} PASSED, {failed_tests} FAILED")
print("======================================================================")

if failed_tests > 0:
    sys.exit(1)
