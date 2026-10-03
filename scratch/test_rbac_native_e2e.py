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

# -----------------------------------------------------------------------------
# TEST SUITE 6: Deep Security & Granular API Hardening
# -----------------------------------------------------------------------------
print("\n--- SUITE 6: Deep Security & Granular API Hardening ---")

# 1. Salary masking in CSV export for HR viewer lacking hr_manage_salaries
test_role.set_permissions(["hr_view_employees"])
csv_res = client.get("/api/employees/export-csv/")
assert_test(csv_res.status_code == 200, "HR viewer can export CSV (HTTP 200)")
csv_content = csv_res.content.decode("utf-8-sig")
assert_test("••••" in csv_content, "Employee salary is masked with '••••' in CSV for user lacking hr_manage_salaries")

# Owner gets unmasked salary in CSV
owner_csv_res = owner_client.get("/api/employees/export-csv/")
assert_test(owner_csv_res.status_code == 200, "Owner can export CSV (HTTP 200)")
owner_csv_content = owner_csv_res.content.decode("utf-8-sig")
assert_test(str(test_emp.salary) in owner_csv_content, "Owner receives unmasked salary in CSV")

# 2. Prevent order cancellation via order_edit_view without cancel_orders
test_order = Order.objects.create(
    tenant=tenant,
    order_number="SEC-TEST-999",
    status="new",
    total=Decimal("100.00")
)
test_role.set_permissions(["edit_orders"])  # has edit_orders, lacks cancel_orders
res_cancel_bypass = client.post(f"/orders/{test_order.id}/edit/", data={"status": "cancelled"})
assert_test(res_cancel_bypass.status_code == 403, "User with edit_orders but lacking cancel_orders blocked from cancelling via order_edit_view (HTTP 403)")

# 3. Granular employee update checks: salary, jobRoleId, PIN
res_update_salary = client.post(f"/api/employees/{test_emp.id}/", data=json.dumps({"salary": "99999"}), content_type="application/json")
assert_test(res_update_salary.status_code == 403, "User lacking hr_manage_salaries blocked from modifying salary (HTTP 403)")

res_update_role = client.post(f"/api/employees/{test_emp.id}/", data=json.dumps({"jobRoleId": 1}), content_type="application/json")
assert_test(res_update_role.status_code == 403, "User lacking manage_roles blocked from modifying job_role (HTTP 403)")

res_update_pin = client.post(f"/api/employees/{test_emp.id}/", data=json.dumps({"pin": "9999"}), content_type="application/json")
assert_test(res_update_pin.status_code == 403, "User lacking hr_manage_credentials blocked from modifying PIN (HTTP 403)")

# 4. Status update to out_for_delivery / delivered requires delivery permissions
test_role.set_permissions(["kds_access", "kds_update_status"])  # chef
res_chef_delivery = client.post(f"/api/orders/{test_order.id}/", data=json.dumps({"status": "delivered"}), content_type="application/json")
assert_test(res_chef_delivery.status_code == 403, "Chef lacking delivery permissions blocked from marking order as delivered (HTTP 403)")

test_order.delete()

# 5. GET /api/job-roles/ is restricted to HR / Role managers
res_roles_chef = client.get("/api/job-roles/")
assert_test(res_roles_chef.status_code == 403, "Chef lacking HR/Role management blocked from GET /api/job-roles/ (HTTP 403)")

# 6. Orphaned Group cleanup on JobRole.delete()
from django.contrib.auth.models import Group
orphan_role = JobRole.objects.create(tenant=tenant, name="Temp Orphan Test Role")
orphan_grp = orphan_role.group
orphan_grp_id = orphan_grp.id
assert_test(Group.objects.filter(id=orphan_grp_id).exists(), "Temporary group created for test role")
orphan_role.delete()
assert_test(not Group.objects.filter(id=orphan_grp_id).exists(), "Deleting JobRole cleanly deletes linked Django Group (No orphaned groups)")

# 7. Context processor synonym expansion
from core.context_processors import branch_context
from django.test import RequestFactory
factory = RequestFactory()
rf_req = factory.get("/branch/menu/")
rf_req.user = test_user
rf_req.tenant = tenant
rf_req.session = {}
test_role.set_permissions(["branch_manage_branches"])
ctx = branch_context(rf_req)
assert_test("manage_branches" in ctx["user_perms"], "context_processors branch_context expands 'branch_manage_branches' -> 'manage_branches'")

print("\n--- SUITE 7: Cross-Branch Authority, Inactive PIN Security, and HQ Visibility ---")

# 8. Inactive user fails PIN login
test_emp.set_pin("1234")
test_emp.save()
test_user.is_active = False
test_user.save()
pin_client = Client()
res_pin_inactive = pin_client.post("/login/", data={"auth_type": "pin", "employee_code": test_emp.employee_code, "pin": "1234"})
assert_test("كود الموظف أو رمز PIN غير صحيح" in res_pin_inactive.content.decode("utf-8"), "Inactive employee account fails PIN login with generic error message")
test_user.is_active = True
test_user.save()

# 9. Branch-locked user cannot switch branches
client.force_login(test_user)
test_role.set_permissions(["pos_access"])  # basic cashier without cross-branch perms
res_switch_blocked = client.get(f"/branch/switch/{branch.id}/", follow=False)
assert_test(res_switch_blocked.status_code == 302 and res_switch_blocked.url == "/branch/", "Branch-locked cashier blocked from switching branches (redirected to branch_dashboard)")

# 10. Cross-branch user can switch branches
test_role.set_permissions(["branch_switch_branches"])
second_branch = Branch.objects.create(tenant=tenant, name="Secondary Test Branch", status="active")
res_switch_allowed = client.get(f"/branch/switch/{second_branch.id}/", follow=False)
assert_test(res_switch_allowed.status_code == 302 and res_switch_allowed.url == "/branch/", "Authorized user can switch branch")
# Session should now have second_branch.id
session = client.session
assert_test(session.get("active_branch_id") == second_branch.id, "Session correctly records switched active_branch_id")

# 11. HQ Dashboard Access: user with view_hq_dashboard can access HQ dashboard
test_role.set_permissions(["view_hq_dashboard"])
# Switch to 'all'
res_switch_hq = client.get("/branch/switch/all/", follow=False)
assert_test(res_switch_hq.status_code == 302 and res_switch_hq.url == "/dashboard/", "HQ authorized staff can switch to HQ all-branches view")
res_hq_dash = client.get("/dashboard/")
assert_test(res_hq_dash.status_code == 200, "HQ staff with view_hq_dashboard can access HQ consolidated dashboard (HTTP 200)")

# 12. Non-HQ staff accessing /dashboard/ redirected to their designated operational screen
test_role.set_permissions(["pos_access"])
res_dash_redirect = client.get("/dashboard/", follow=False)
assert_test(res_dash_redirect.status_code == 302 and res_dash_redirect.url in ["/pos/", "/branch/"], "Operational staff accessing /dashboard/ redirected to designated operational screen (HTTP 302)")

second_branch.delete()

print("\n--- SUITE 8: Deep Operational Integrity & Multi-Branch Hardenings ---")
second_branch = Branch.objects.create(tenant=tenant, name="Suite8 Extra Branch", status="active")

# 1. KDS Cross-Branch Leakage Prevention
test_role.set_permissions(["kds_access"])
res_kds_leak = client.get(f"/api/kitchen/live/?branch_id={second_branch.id}")
assert_test(res_kds_leak.status_code == 200 and res_kds_leak.json().get("target_branch_id") == branch.id, "Branch-locked chef blocked from viewing foreign branch KDS (target_branch_id locked to assigned branch)")

# 2. Inventory Cross-Branch Isolation & Delete Protection
inv_branch2 = InventoryItem.objects.create(tenant=tenant, branch=second_branch, name="Branch2 Rice", quantity=50, min_quantity=10)
test_role.set_permissions(["inventory_adjust_stock"])
res_inv_cross_adjust = client.post(f"/api/inventory/adjust/{inv_branch2.id}/", data=json.dumps({"quantity": 100}), content_type="application/json")
assert_test(res_inv_cross_adjust.status_code == 403, "Staff blocked from adjusting inventory of another branch (HTTP 403)")

res_inv_delete_adjust_stock = client.post(f"/api/inventory/delete/{inv_branch2.id}/")
assert_test(res_inv_delete_adjust_stock.status_code == 403, "Staff with only inventory_adjust_stock blocked from deleting inventory items (HTTP 403, requires manage_inventory)")

test_role.set_permissions(["manage_inventory"])
res_inv_delete_cross = client.post(f"/api/inventory/delete/{inv_branch2.id}/")
assert_test(res_inv_delete_cross.status_code == 403, "Branch-locked manager blocked from deleting inventory of another branch (HTTP 403)")

inv_branch2.delete()

# 3. Global Menu Toggle Protection
test_role.set_permissions(["menu_toggle_availability", "branch_switch_branches"])
client_hq = Client()
client_hq.force_login(test_user)
s_hq = client_hq.session
s_hq["active_branch_id"] = None
s_hq.save()
test_menu_item = MenuItem.objects.filter(tenant=tenant).first()
res_global_menu = client_hq.post(f"/api/branch-menu/toggle/{test_menu_item.id}/")
assert_test(res_global_menu.status_code == 403, "Staff with menu_toggle_availability blocked from globally toggling item across all branches (HTTP 403)")

# 4. Cashier Spoofing Prevention
test_role.set_permissions(["pos_access", "pos_create_order"])
order_spoof_payload = {
    "branchId": branch.id,
    "items": [{"menuItemId": test_menu_item.id, "qty": 1}],
    "type": "dine_in",
    "channel": "cashier",
    "cashier": "MaliciousSpoofedCashierName"
}
res_spoof_order = client.post("/api/orders/", data=json.dumps(order_spoof_payload), content_type="application/json")
assert_test(res_spoof_order.status_code == 201, "Order created successfully (HTTP 201)")
created_order_id = res_spoof_order.json()["order"]["id"]
created_order = Order.objects.get(id=created_order_id)
assert_test(created_order.cashier == test_emp.name, f"Cashier field strictly bound to authenticated employee ({created_order.cashier} == {test_emp.name}), spoofed name rejected")

# 5. Cross-Branch Order Deletion Protection
test_role.set_permissions(["delete_orders"])
order_branch2 = Order.objects.create(tenant=tenant, branch=second_branch, order_number="B2-DEL-TEST", total=50)
res_del_cross_order = client.post(f"/api/orders/{order_branch2.id}/delete/")
assert_test(res_del_cross_order.status_code == 403, "Branch-locked user blocked from deleting order belonging to another branch (HTTP 403)")
order_branch2.delete()

# 6. KDS Recall Protection
test_role.set_permissions(["kds_access", "kds_update_status"])  # lacks kds_recall_order
created_order.status = "ready"
created_order.save()
res_recall_blocked = client.post(f"/api/orders/{created_order.id}/", data=json.dumps({"status": "preparing"}), content_type="application/json")
assert_test(res_recall_blocked.status_code == 403, "Chef lacking kds_recall_order blocked from recalling ready order back to preparing (HTTP 403)")

test_role.set_permissions(["kds_access", "kds_recall_order"])
res_recall_allowed = client.post(f"/api/orders/{created_order.id}/", data=json.dumps({"status": "preparing"}), content_type="application/json")
assert_test(res_recall_allowed.status_code == 200, "Chef with kds_recall_order successfully recalls ready order back to preparing (HTTP 200)")

# 7. Forced Employee Deletion Protection
hist_user = User.objects.create_user(username="hist_user_s8", password="password123")
hist_emp = Employee.objects.create(tenant=tenant, branch=branch, user=hist_user, name="History Emp S8", employee_code="555")
hist_order = Order.objects.create(tenant=tenant, branch=branch, order_number="ORD-HIST-001", cashier="History Emp S8", subtotal=Decimal("10.00"), total=Decimal("10.00"))

test_role.set_permissions(["manage_employees", "hr_deactivate_employee"])
res_force_del = client.post(f"/api/employees/{hist_emp.id}/delete/", data=json.dumps({"force": True}), content_type="application/json")
assert_test(res_force_del.status_code == 200 and res_force_del.json().get("action") == "archived", "Non-owner passing force=True on employee with order history safely archived instead of hard deleted")
hist_order.delete()
hist_emp.delete()
hist_user.delete()

# Clean up test artifacts
created_order.delete()
second_branch.delete()

# --- SUITE 9: Financial Expansion, Multi-Tenant PIN Isolation, Discount Cap & SaaS Gating ---
print("\n--- SUITE 9: Financial Expansion, Multi-Tenant PIN Isolation, Discount Cap & SaaS Gating ---")

# 1. Financial Implied Expansion
test_role.set_permissions(["finance_view_sales"])
assert_test(user_has_perm(test_user, "finance_view_sales"), "User has finance_view_sales")
assert_test(user_has_perm(test_user, "view_financials"), "Implied: finance_view_sales grants user_has_perm('view_financials')")

# Check template context expansion
factory = RequestFactory()
req = factory.get("/branch/")
req.user = test_user
ctx = branch_context(req)
assert_test("view_financials" in ctx.get("user_perms", set()), "Template context user_perms expands finance_view_sales to view_financials")

# 2. Multi-Tenant PIN Collision Protection
Tenant.objects.filter(slug="collision-tenant-b").delete()
Employee.objects.filter(employee_code="999").delete()
tenant_b = Tenant.objects.create(name="Collision Tenant B", slug="collision-tenant-b", is_active=True)
branch_b = Branch.objects.create(tenant=tenant_b, name="Collision Branch B")

emp_a = Employee.objects.create(tenant=tenant, branch=branch, name="Emp A", employee_code="999", status="active")
emp_a.set_pin("5555")
emp_a.save()

emp_b = Employee.objects.create(tenant=tenant_b, branch=branch_b, name="Emp B", employee_code="999", status="active")
emp_b.set_pin("5555")
emp_b.save()

# PIN login without restaurant identifier when collision exists -> blocked!
c_anon = Client()
res_coll = c_anon.post("/login/", data={"auth_type": "pin", "employee_code": "999", "pin": "5555"})
assert_test(res_coll.status_code == 200 and "أكثر من حساب" in res_coll.content.decode("utf-8"), "Ambiguous cross-tenant PIN collision detected and blocked from leaking")

# PIN login with restaurant identifier -> logs into exact tenant
res_tenant_a = c_anon.post("/login/", data={"auth_type": "pin", "employee_code": "999", "pin": "5555", "restaurant": tenant.slug})
assert_test(res_tenant_a.status_code == 302 and c_anon.session.get("active_tenant_id") == tenant.id, "Scoped PIN login correctly authenticated into Tenant A")

c_anon.logout()
res_tenant_b = c_anon.post("/login/", data={"auth_type": "pin", "employee_code": "999", "pin": "5555", "restaurant": tenant_b.slug})
assert_test(res_tenant_b.status_code == 302 and c_anon.session.get("active_tenant_id") == tenant_b.id, "Scoped PIN login correctly authenticated into Tenant B")

emp_a.delete()
emp_b.delete()
branch_b.delete()
tenant_b.delete()

# Reactivate test_user & test_emp for order testing
test_emp.status = "active"
test_emp.save()
test_user.is_active = True
test_user.save()
client.force_login(test_user)

# 3. Discount Cap Protection (> 50% requires supervisor)
test_role.set_permissions(["pos_access", "pos_create_order", "pos_apply_discount"])
menu_item_100, _ = MenuItem.objects.get_or_create(tenant=tenant, name="Test Item 100", defaults={"price": Decimal("100.00"), "category": "main"})
res_disc_20 = client.post("/api/orders/", data=json.dumps({
    "type": "dine_in",
    "items": [{"menuItemId": menu_item_100.id, "qty": 1}],
    "discount": 20.00
}), content_type="application/json")
assert_test(res_disc_20.status_code == 201, "Cashier with pos_apply_discount allowed 20% discount (<= 50%)")
order_20_id = res_disc_20.json().get("order", {}).get("id")
if order_20_id:
    Order.objects.filter(id=order_20_id).delete()

# Order item: price = 100. discount = 70 (70%) -> Blocked for regular cashier!
res_disc_70 = client.post("/api/orders/", data=json.dumps({
    "type": "dine_in",
    "items": [{"menuItemId": menu_item_100.id, "qty": 1}],
    "discount": 70.00
}), content_type="application/json")
assert_test(res_disc_70.status_code == 403, "Cashier lacking supervisor authority blocked from > 50% discount (HTTP 403)")

# User with edit_orders (supervisor) -> Allowed 70% discount
test_role.set_permissions(["pos_access", "pos_create_order", "pos_apply_discount", "edit_orders"])
res_disc_70_sup = client.post("/api/orders/", data=json.dumps({
    "type": "dine_in",
    "items": [{"menuItemId": menu_item_100.id, "qty": 1}],
    "discount": 70.00
}), content_type="application/json")
assert_test(res_disc_70_sup.status_code == 201, "Supervisor with edit_orders allowed > 50% discount (HTTP 201)")
order_70_id = res_disc_70_sup.json().get("order", {}).get("id")
if order_70_id:
    Order.objects.filter(id=order_70_id).delete()
menu_item_100.delete()

# 4. SaaS Plan Feature Gating on APIs
User.objects.filter(username="gated_user").delete()
Tenant.objects.filter(slug="gated-tenant").delete()
SubscriptionPlan.objects.filter(name="Test Basic Plan").delete()

basic_plan = SubscriptionPlan.objects.create(
    name="Test Basic Plan",
    features=["pos", "menu"],  # NO inventory, NO custom_roles
    max_branches=1,
    max_employees=5
)
gated_tenant = Tenant.objects.create(name="Gated Tenant", slug="gated-tenant", subscription_plan=basic_plan, is_active=True)
gated_branch = Branch.objects.create(tenant=gated_tenant, name="Gated Branch")
gated_role = JobRole.objects.create(tenant=gated_tenant, name="Gated Manager", scope="branch")
gated_role.set_permissions(["manage_inventory", "inventory_add_stock", "manage_roles"])
gated_user = User.objects.create_user(username="gated_user", password="password123")
gated_emp = Employee.objects.create(tenant=gated_tenant, branch=gated_branch, user=gated_user, job_role=gated_role, name="Gated Emp", employee_code="888")
UserProfile.objects.update_or_create(user=gated_user, defaults={"tenant": gated_tenant, "branch": gated_branch, "job_role": gated_role, "role": "manager"})
gated_user.groups.set([gated_role.group])

c_gated = Client()
c_gated.login(username="gated_user", password="password123")
session_gated = c_gated.session
session_gated["active_tenant_id"] = gated_tenant.id
session_gated["active_branch_id"] = gated_branch.id
session_gated.save()

# Try calling api_create_inventory on plan lacking inventory -> 403 Forbidden!
res_inv_gated = c_gated.post("/api/inventory/create/", data=json.dumps({"name": "Flour", "branchId": gated_branch.id}), content_type="application/json")
assert_test(res_inv_gated.status_code == 403, "API rejects inventory creation when plan lacks 'inventory' feature (HTTP 403)")

# Try creating custom role on plan lacking custom_roles -> 403 Forbidden!
res_role_gated = c_gated.post("/api/job-roles/", data=json.dumps({"name": "Custom Cashier", "scope": "branch"}), content_type="application/json")
assert_test(res_role_gated.status_code == 403, "API rejects custom role creation when plan lacks 'custom_roles' feature (HTTP 403)")

# ----------------------------------------------------------------------------------
# SUITE 10: Advanced Security: Salary Masking, Owner Protection, Cross-Branch & Plan Gating
# ----------------------------------------------------------------------------------
print("\n--- SUITE 10: Advanced Security: Salary Masking, Owner Protection, Cross-Branch & Plan Gating ---")

# 1. Salary Masking in HTML View
test_role.set_permissions(["hr_view_employees"])
test_emp.salary = Decimal("7500.00")
test_emp.save()

client.force_login(test_user)
res_emp_html = client.get("/employees/")
assert_test(res_emp_html.status_code == 200, "HR Viewer accesses /employees/ (HTTP 200)")
content_emp_html = res_emp_html.content.decode("utf-8")
assert_test("7500" not in content_emp_html and "••••" in content_emp_html, "Salary strictly masked with '••••' in HTML table for user lacking hr_manage_salaries")

# Owner accesses /employees/ -> unmasked salary
client.force_login(owner_user)
res_owner_html = client.get("/employees/")
content_owner_html = res_owner_html.content.decode("utf-8")
assert_test("7500" in content_owner_html, "Owner sees unmasked salary in /employees/ HTML table")

# 2. Owner Account Protection & Self-Lockout Prevention
owner_emp, _ = Employee.objects.get_or_create(
    tenant=tenant,
    user=owner_user,
    defaults={"name": "Owner Emp", "employee_code": "001", "role": "manager", "status": "active"}
)

# Manager user with manage_employees
mgr_user = User.objects.create_user(username="mgr_user_suite10", password="password123")
mgr_role = JobRole.objects.create(tenant=tenant, name="Branch Manager Suite10", scope="branch")
mgr_role.set_permissions(["manage_employees", "hr_edit_employee", "hr_deactivate_employee", "delivery_manage_zones", "edit_orders"])
mgr_emp = Employee.objects.create(tenant=tenant, branch=branch, user=mgr_user, job_role=mgr_role, name="Manager Suite10", employee_code="777")
UserProfile.objects.update_or_create(user=mgr_user, defaults={"tenant": tenant, "branch": branch, "job_role": mgr_role, "role": "manager"})
mgr_user.groups.set([mgr_role.group])

c_mgr = Client()
c_mgr.login(username="mgr_user_suite10", password="password123")
s_mgr = c_mgr.session
s_mgr["active_tenant_id"] = tenant.id
s_mgr["active_branch_id"] = branch.id
s_mgr.save()

# Manager tries self-deletion -> HTTP 400
res_self_del = c_mgr.post(f"/api/employees/{mgr_emp.id}/delete/")
assert_test(res_self_del.status_code == 400 and "شخصي" in res_self_del.json().get("error", ""), "Self-deletion blocked with HTTP 400")

# Manager tries self-toggle -> HTTP 400
res_self_tog = c_mgr.post(f"/api/employees/{mgr_emp.id}/toggle-status/")
assert_test(res_self_tog.status_code == 400 and "شخصي" in res_self_tog.json().get("error", ""), "Self-toggle blocked with HTTP 400")

# Manager tries to delete Owner -> HTTP 403
res_del_owner = c_mgr.post(f"/api/employees/{owner_emp.id}/delete/")
assert_test(res_del_owner.status_code == 403 and "مالك" in res_del_owner.json().get("error", ""), "Subordinate blocked from deleting owner account (HTTP 403)")

# Manager tries to toggle Owner -> HTTP 403
res_tog_owner = c_mgr.post(f"/api/employees/{owner_emp.id}/toggle-status/")
assert_test(res_tog_owner.status_code == 403 and "مالك" in res_tog_owner.json().get("error", ""), "Subordinate blocked from toggling owner account (HTTP 403)")

# Manager tries to edit Owner -> HTTP 403
res_edit_owner = c_mgr.post(f"/api/employees/{owner_emp.id}/", data=json.dumps({"name": "Hacked Owner"}), content_type="application/json")
assert_test(res_edit_owner.status_code == 403 and "مالك" in res_edit_owner.json().get("error", ""), "Subordinate blocked from modifying owner account (HTTP 403)")

# 3. Cross-Branch Boundary Isolation
branch_secondary = Branch.objects.create(tenant=tenant, name="Secondary Branch Suite10")

# Manager locked to branch tries to modify delivery areas of branch_secondary -> HTTP 403!
res_cross_area = c_mgr.post(f"/api/branches/{branch_secondary.id}/areas/", data=json.dumps({"action": "add", "name": "Zone B"}), content_type="application/json")
assert_test(res_cross_area.status_code == 403 and "آخر" in res_cross_area.json().get("error", ""), "Branch-locked manager blocked from modifying delivery areas of foreign branch (HTTP 403)")

# Manager locked to branch tries to toggle branch_secondary -> HTTP 403!
res_cross_toggle = c_mgr.post(f"/api/branches/toggle/{branch_secondary.id}/")
assert_test(res_cross_toggle.status_code == 403, "Branch-locked manager blocked from toggling foreign branch (HTTP 403)")

# Manager locked to branch tries to reassign order branch via order_edit_view
order_branch_test = Order.objects.create(
    tenant=tenant,
    branch=branch,
    order_number="TEST-SW-001",
    subtotal=Decimal("50.00"),
    total=Decimal("50.00")
)
c_mgr.post(f"/orders/{order_branch_test.id}/edit/", data={
    "branch_id": str(branch_secondary.id),
    "status": "new",
    "order_type": "dine_in",
    "customer_name": "Test Customer",
    "cashier": "Mgr"
})
order_branch_test.refresh_from_db()
assert_test(order_branch_test.branch == branch, "Branch-locked staff blocked from transferring order branch in order_edit_view (stays locked to assigned branch)")
order_branch_test.delete()
branch_secondary.delete()
mgr_emp.delete()
mgr_user.delete()
mgr_role.delete()
owner_emp.delete()

# 4. SaaS Plan Feature Gating for KDS, Call Center & Delivery
# Basic plan has features=["pos", "menu"], NO kds, NO call_center, NO delivery
c_gated_client = Client()
c_gated_client.login(username="gated_user", password="password123")
session_g = c_gated_client.session
session_g["active_tenant_id"] = gated_tenant.id
session_g["active_branch_id"] = gated_branch.id
session_g.save()

# Gated tenant accesses kitchen_view -> 403!
res_gated_kds = c_gated_client.get("/kitchen/")
assert_test(res_gated_kds.status_code == 403, "KDS screen rejected when plan lacks 'kds' feature (HTTP 403)")

# Gated tenant accesses delivery_view -> 403!
res_gated_del = c_gated_client.get("/delivery/")
assert_test(res_gated_del.status_code == 403, "Delivery screen rejected when plan lacks 'delivery' feature (HTTP 403)")

# Gated tenant accesses ai-callcenter -> 403!
res_gated_ai = c_gated_client.get("/ai-callcenter/")
assert_test(res_gated_ai.status_code == 403, "AI Call Center studio rejected when plan lacks 'call_center' feature (HTTP 403)")

# Gated tenant calls api_ai_callcenter_create_profile -> 403!
res_gated_ai_api = c_gated_client.post("/api/ai-callcenter/profiles/create/", data=json.dumps({"name": "Test"}), content_type="application/json")
assert_test(res_gated_ai_api.status_code == 403, "AI Call Center API rejected when plan lacks 'call_center' feature (HTTP 403)")

# Gated tenant calls api_branch_delivery_areas POST -> 403!
res_gated_del_api = c_gated_client.post(f"/api/branches/{gated_branch.id}/areas/", data=json.dumps({"action": "add", "name": "Compound 1"}), content_type="application/json")
assert_test(res_gated_del_api.status_code == 403, "Delivery areas API rejected when plan lacks 'delivery' feature (HTTP 403)")

# Context processor discards all sub-permissions when parent feature missing
req_gated = factory.get("/branch/")
req_gated.user = gated_user
req_gated.session = session_g
req_gated.tenant = gated_tenant
ctx_gated = branch_context(req_gated)
gated_perms = ctx_gated.get("user_perms", set())
assert_test("kds_access" not in gated_perms, "Context processor discards 'kds_access' when plan lacks KDS")
assert_test("delivery_access" not in gated_perms, "Context processor discards 'delivery_access' when plan lacks delivery")
assert_test("call_center_manage_ai" not in gated_perms, "Context processor discards 'call_center_manage_ai' when plan lacks call center")
assert_test("system_manage_roles" not in gated_perms, "Context processor discards 'system_manage_roles' when plan lacks custom roles")

gated_emp.delete()
gated_user.delete()
gated_role.delete()
gated_branch.delete()
gated_tenant.delete()
basic_plan.delete()

# Clean up test artifacts
test_emp.delete()
test_user.delete()
test_role.delete()

# ----------------------------------------------------------------------------------
# SUITE 11: Deep Hardening: Privilege Escalation, Password Security, Takeover, HQ Scoping
# ----------------------------------------------------------------------------------
print("\n--- SUITE 11: Deep Hardening: Privilege Escalation, Password Security, Takeover, HQ Scoping ---")

# 1. Privilege Escalation Prevention on Employee Creation
hr_creator_user = User.objects.create_user(username="hr_creator_user", password="password123")
hr_creator_role = JobRole.objects.create(tenant=tenant, name="HR Creator Role", scope="branch")
hr_creator_role.set_permissions(["hr_create_employee"])
hr_creator_emp = Employee.objects.create(tenant=tenant, branch=branch, user=hr_creator_user, job_role=hr_creator_role, name="HR Creator", employee_code="901")
UserProfile.objects.update_or_create(user=hr_creator_user, defaults={"tenant": tenant, "branch": branch, "job_role": hr_creator_role, "role": "cashier"})
hr_creator_user.groups.set([hr_creator_role.group])

c_hr = Client()
c_hr.login(username="hr_creator_user", password="password123")
s_hr = c_hr.session
s_hr["active_tenant_id"] = tenant.id
s_hr["active_branch_id"] = branch.id
s_hr.save()

high_role = JobRole.objects.create(tenant=tenant, name="Super Role Suite11", scope="branch")
high_role.set_permissions(["system_manage_billing", "manage_roles", "manage_employees"])

# Attempt to assign high_role without manage_roles -> 403 Forbidden!
res_esc_role = c_hr.post("/api/employees/create/", data=json.dumps({
    "name": "Escalated User",
    "employeeCode": "902",
    "jobRoleId": high_role.id
}), content_type="application/json")
assert_test(res_esc_role.status_code == 403, "Subordinate lacking manage_roles blocked from assigning job role on creation (HTTP 403)")

# Attempt to assign custom salary (15000) without hr_manage_salaries -> 403 Forbidden!
res_esc_sal = c_hr.post("/api/employees/create/", data=json.dumps({
    "name": "Overpaid User",
    "employeeCode": "903",
    "salary": 15000
}), content_type="application/json")
assert_test(res_esc_sal.status_code == 403, "Subordinate lacking hr_manage_salaries blocked from setting custom salary on creation (HTTP 403)")

# Attempt to set password without hr_manage_credentials -> 403 Forbidden!
res_esc_pwd = c_hr.post("/api/employees/create/", data=json.dumps({
    "name": "Passworded User",
    "employeeCode": "904",
    "password": "mypassword123"
}), content_type="application/json")
assert_test(res_esc_pwd.status_code == 403, "Subordinate lacking hr_manage_credentials blocked from setting password on creation (HTTP 403)")

# Normal creation: User account created with UNUSABLE password (no default admin123)
res_norm_create = c_hr.post("/api/employees/create/", data=json.dumps({
    "name": "Safe PIN User",
    "employeeCode": "905",
    "pin": "5555"
}), content_type="application/json")
assert_test(res_norm_create.status_code == 200, "Normal employee created successfully (HTTP 200)")
created_emp = Employee.objects.filter(employee_code="905", tenant=tenant).select_related("user").first()
assert_test(created_emp and created_emp.user and not created_emp.user.has_usable_password(), "New PIN employee created with strictly unusable password (No default admin123)")

# 2. Account Takeover Protection in api_create_tenant
platform_super = User.objects.filter(is_superuser=True).first()
if not platform_super:
    platform_super = User.objects.create_superuser(username="admin_super", password="password123", email="admin@motaem.local")
c_super = Client()
c_super.force_login(platform_super)

# Attempt to create tenant with already taken owner username
Tenant.objects.filter(slug="takeover-tenant").delete()
res_takeover = c_super.post("/api/tenants/create/", data=json.dumps({
    "name": "Takeover Tenant",
    "slug": "takeover-tenant",
    "owner_username": owner_user.username,
    "owner_password": "newpassword123"
}), content_type="application/json")
assert_test(res_takeover.status_code == 400 and "محجوز مسبقاً" in res_takeover.json().get("error", ""), "Tenant creation rejects colliding owner username with HTTP 400")

# 3. Global Menu Tampering Protection in api_toggle_menu_item
menu_item_test = MenuItem.objects.create(tenant=tenant, name="Global Test Item", price=Decimal("25.00"), available=True)
cashier_user = User.objects.create_user(username="cashier_suite11", password="password123")
cashier_role = JobRole.objects.create(tenant=tenant, name="Cashier Suite11", scope="branch")
cashier_role.set_permissions(["menu_toggle_availability"]) # Lacks manage_menu
cashier_emp = Employee.objects.create(tenant=tenant, branch=branch, user=cashier_user, job_role=cashier_role, name="Cashier Suite11", employee_code="906")
UserProfile.objects.update_or_create(user=cashier_user, defaults={"tenant": tenant, "branch": branch, "job_role": cashier_role, "role": "cashier"})
cashier_user.groups.set([cashier_role.group])

c_cashier = Client()
c_cashier.login(username="cashier_suite11", password="password123")
s_cashier = c_cashier.session
s_cashier["active_tenant_id"] = tenant.id
s_cashier["active_branch_id"] = branch.id
s_cashier.save()

# Cashier tries to globally toggle menu item -> HTTP 403
res_global_menu = c_cashier.post(f"/api/menu/toggle/{menu_item_test.id}/")
assert_test(res_global_menu.status_code == 403, "Staff lacking manage_menu blocked from global menu toggle via api_toggle_menu_item (HTTP 403)")

# 4. KDS & POS Plan Feature Gating
plan_no_kds_pos = SubscriptionPlan.objects.create(name="No KDS POS Plan", features=["menu_management"], max_branches=1, max_employees=5)
tenant_gated2 = Tenant.objects.create(name="No KDS Tenant", slug="no-kds-tenant", subscription_plan=plan_no_kds_pos, is_active=True)
branch_gated2 = Branch.objects.create(tenant=tenant_gated2, name="No KDS Branch")
role_gated2 = JobRole.objects.create(tenant=tenant_gated2, name="Full Op Role", scope="branch")
role_gated2.set_permissions(["kds_access", "pos_access"])
user_gated2 = User.objects.create_user(username="user_gated2", password="password123")
emp_gated2 = Employee.objects.create(tenant=tenant_gated2, branch=branch_gated2, user=user_gated2, job_role=role_gated2, name="Gated2 Emp", employee_code="907")
UserProfile.objects.update_or_create(user=user_gated2, defaults={"tenant": tenant_gated2, "branch": branch_gated2, "job_role": role_gated2, "role": "cashier"})
user_gated2.groups.set([role_gated2.group])

c_gated2 = Client()
c_gated2.login(username="user_gated2", password="password123")
s_g2 = c_gated2.session
s_g2["active_tenant_id"] = tenant_gated2.id
s_g2["active_branch_id"] = branch_gated2.id
s_g2.save()

# Check /api/kitchen/live/ on plan lacking kds -> 403
res_kds_live = c_gated2.get("/api/kitchen/live/")
assert_test(res_kds_live.status_code == 403, "Kitchen live snapshot API rejected when plan lacks 'kds' (HTTP 403)")

# Check /pos/ on plan lacking pos -> 403
res_pos_gated = c_gated2.get("/pos/")
assert_test(res_pos_gated.status_code == 403, "POS screen rejected when plan lacks 'pos' (HTTP 403)")

# 5. Cross-Branch Delivery Area & Driver Enforcement
branch_b = Branch.objects.create(tenant=tenant, name="Branch B Suite11")
area_b = DeliveryArea.objects.create(branch=branch_b, name="Area B", delivery_fee=Decimal("12.00"))
driver_b = Employee.objects.create(tenant=tenant, branch=branch_b, name="Driver B", role="driver")

# Cashier in branch trying to create order with deliveryAreaId from branch_b -> 403!
cashier_role.set_permissions(["pos_access", "pos_create_order"])
res_cross_order = c_cashier.post("/api/orders/", data=json.dumps({
    "type": "delivery",
    "deliveryAreaId": area_b.id,
    "items": [{"menuItemId": menu_item_test.id, "qty": 1}]
}), content_type="application/json")
assert_test(res_cross_order.status_code == 403, "Branch-locked cashier blocked from creating order in foreign delivery area (HTTP 403)")

# Order in branch: trying to assign driver_b (from branch_b) -> 403!
order_in_a = Order.objects.create(tenant=tenant, branch=branch, order_number="ORD-A-101", subtotal=Decimal("25.00"), total=Decimal("25.00"), order_type="delivery")
cashier_role.set_permissions(["edit_orders", "delivery_assign_driver"])
res_cross_driver = c_cashier.post(f"/api/orders/{order_in_a.id}/", data=json.dumps({
    "driverId": driver_b.id
}), content_type="application/json")
assert_test(res_cross_driver.status_code == 403, "Staff blocked from assigning driver from foreign branch to order (HTTP 403)")

# 6. HQ Scoped Manager Cross-Branch Authority
hq_user = User.objects.create_user(username="hq_auditor_suite11", password="password123")
hq_role = JobRole.objects.create(tenant=tenant, name="HQ Auditor", scope="hq")
hq_role.set_permissions(["view_orders", "edit_orders", "manage_inventory", "inventory_adjust_stock"])
hq_emp = Employee.objects.create(tenant=tenant, branch=branch, user=hq_user, job_role=hq_role, name="HQ Auditor", employee_code="908")
UserProfile.objects.update_or_create(user=hq_user, defaults={"tenant": tenant, "branch": branch, "job_role": hq_role, "role": "manager"})
hq_user.groups.set([hq_role.group])

c_hq = Client()
c_hq.login(username="hq_auditor_suite11", password="password123")
s_hq = c_hq.session
s_hq["active_tenant_id"] = tenant.id
s_hq["active_branch_id"] = branch.id
s_hq.save()

order_in_b = Order.objects.create(tenant=tenant, branch=branch_b, order_number="ORD-B-102", subtotal=Decimal("30.00"), total=Decimal("30.00"))
inv_in_b = InventoryItem.objects.create(tenant=tenant, branch=branch_b, name="Coffee Beans B", quantity=Decimal("10.00"))

# HQ auditor views order_detail_view for order_in_b -> 200 OK!
res_hq_view = c_hq.get(f"/orders/{order_in_b.id}/")
assert_test(res_hq_view.status_code == 200, "HQ scoped auditor with assigned home branch allowed to view foreign branch order (HTTP 200)")

# HQ auditor views order_edit_view for order_in_b -> 200 OK!
res_hq_edit = c_hq.get(f"/orders/{order_in_b.id}/edit/")
assert_test(res_hq_edit.status_code == 200, "HQ scoped auditor allowed to access foreign branch order edit (HTTP 200)")

# HQ auditor adjusts inventory in branch_b -> 200 OK!
res_hq_adj = c_hq.post(f"/api/inventory/adjust/{inv_in_b.id}/", data=json.dumps({"delta": 5}), content_type="application/json")
assert_test(res_hq_adj.status_code == 200, "HQ scoped auditor allowed to adjust foreign branch inventory (HTTP 200)")

# 7. Anti-Self-Lockout and User Status Sync in api_update_employee
# Cashier tries to deactivate self -> 400 Bad Request!
cashier_role.set_permissions(["hr_edit_employee", "manage_employees"])
res_self_inact = c_cashier.post(f"/api/employees/{cashier_emp.id}/", data=json.dumps({"status": "inactive"}), content_type="application/json")
assert_test(res_self_inact.status_code == 400 and "شخصي" in res_self_inact.json().get("error", ""), "Self-deactivation via api_update_employee blocked with HTTP 400")

# Deactivating another employee synchronizes user.is_active = False
target_user = User.objects.create_user(username="target_user_suite11", password="password123")
target_emp = Employee.objects.create(tenant=tenant, branch=branch, user=target_user, name="Target Emp", employee_code="909", status="active")
res_deact_target = c_cashier.post(f"/api/employees/{target_emp.id}/", data=json.dumps({"status": "inactive"}), content_type="application/json")
assert_test(res_deact_target.status_code == 200, "Employee deactivated successfully (HTTP 200)")
target_user.refresh_from_db()
assert_test(target_user.is_active is False, "Deactivating employee in api_update_employee synchronizes User.is_active = False")

# Clean up Suite 11 artifacts
target_emp.delete()
target_user.delete()
order_in_b.delete()
inv_in_b.delete()
order_in_a.delete()
driver_b.delete()
area_b.delete()
branch_b.delete()
hq_emp.delete()
hq_user.delete()
hq_role.delete()
emp_gated2.delete()
user_gated2.delete()
role_gated2.delete()
branch_gated2.delete()
tenant_gated2.delete()
plan_no_kds_pos.delete()
cashier_emp.delete()
cashier_user.delete()
cashier_role.delete()
menu_item_test.delete()
if created_emp:
    if created_emp.user:
        created_emp.user.delete()
    created_emp.delete()
high_role.delete()
hr_creator_emp.delete()
hr_creator_user.delete()
hr_creator_role.delete()

print("\n--- SUITE 12: Tenant Fallback, System Role Protection, FastMCP Expiration, Order Inversion & Audit Trail ---")

# 1. Tenant Fallback Removal in AI Call Center MCP
c_anon = Client()
res_anon_sync = c_anon.post("/api/ai-callcenter/mcp/sync/")
assert_test(res_anon_sync.status_code in [400, 401], "Unauthenticated MCP sync blocked without leaking first tenant")

# 2. System Role Modification Protection
User.objects.filter(username="s12_mgr").delete()
JobRole.objects.filter(tenant=tenant, name="Role Manager S12").delete()
s12_mgr_user = User.objects.create_user(username="s12_mgr", password="password123")
s12_mgr_role = JobRole.objects.create(tenant=tenant, name="Role Manager S12", scope="branch")
s12_mgr_role.set_permissions(["manage_roles", "system_manage_roles"])
s12_mgr_emp = Employee.objects.create(tenant=tenant, branch=branch, user=s12_mgr_user, name="S12 Mgr", status="active", job_role=s12_mgr_role)
UserProfile.objects.update_or_create(user=s12_mgr_user, defaults={"tenant": tenant, "branch": branch, "role": "manager", "job_role": s12_mgr_role})

c_s12 = Client()
c_s12.login(username="s12_mgr", password="password123")
session_s12 = c_s12.session
session_s12["active_tenant_id"] = tenant.id
session_s12["active_branch_id"] = branch.id
session_s12.save()

sys_role = JobRole.objects.filter(tenant=tenant, is_system=True).first()
if not sys_role:
    sys_role = JobRole.objects.create(tenant=tenant, name="المالك الأساسي", is_system=True, scope="both")

res_edit_sys = c_s12.post(f"/api/job-roles/{sys_role.id}/", data=json.dumps({"name": "Tampered Owner", "permissions": []}), content_type="application/json")
assert_test(res_edit_sys.status_code == 403 and "الأساسية" in res_edit_sys.json().get("error", ""), "Subordinate with manage_roles blocked from modifying is_system role (HTTP 403)")

c_owner = Client()
c_owner.force_login(owner_user)
session_own = c_owner.session
session_own["active_tenant_id"] = tenant.id
session_own["active_branch_id"] = branch.id
session_own.save()

res_owner_edit = c_owner.post(f"/api/job-roles/{sys_role.id}/", data=json.dumps({"description": "Updated by Owner"}), content_type="application/json")
assert_test(res_owner_edit.status_code == 200, "Owner allowed to update system role (HTTP 200)")

# 3. FastMCP Temporal Subscription Expiration
from django.utils import timezone
from core.models import TenantApiKey
from core import mcp_server as ms
TenantApiKey.objects.filter(key="mcp_test_key_s12").delete()
s12_api_key = TenantApiKey.objects.create(tenant=tenant, key="mcp_test_key_s12", is_active=True)
orig_end = tenant.subscription_end
tenant.subscription_end = timezone.now() - timezone.timedelta(days=2)
tenant.save()

try:
    ms._authenticate("mcp_test_key_s12")
    mcp_blocked = False
except ValueError as e:
    mcp_blocked = "منتهي أو ملغي" in str(e)
assert_test(mcp_blocked, "FastMCP _authenticate strictly rejects access when subscription_end is in the past")

tenant.subscription_end = orig_end
tenant.save()
s12_api_key.delete()

# 4. Order State Inversion Safeguards (Cancelled/Refunded Orders)
Order.objects.filter(order_number="S12-ORD-001").delete()
s12_order = Order.objects.create(
    tenant=tenant,
    branch=branch,
    order_number="S12-ORD-001",
    status="cancelled",
    paid=False,
    subtotal=Decimal("100.00"),
    total=Decimal("100.00")
)

s12_mgr_role.set_permissions(["edit_orders", "pos_access"])
res_reactivate_fail = c_s12.post(f"/api/orders/{s12_order.id}/", data=json.dumps({"status": "preparing"}), content_type="application/json")
assert_test(res_reactivate_fail.status_code == 403 and "إعادة تنشيط" in res_reactivate_fail.json().get("error", ""), "Staff lacking cancel permissions blocked from reactivating cancelled order (HTTP 403)")

res_pay_cancelled = c_s12.post(f"/api/orders/{s12_order.id}/", data=json.dumps({"paid": True}), content_type="application/json")
assert_test(res_pay_cancelled.status_code == 400 and "إلغاؤها" in res_pay_cancelled.json().get("error", ""), "Marking cancelled order as paid blocked with HTTP 400")

s12_mgr_role.set_permissions(["edit_orders", "pos_cancel_order", "pos_access"])
res_reactivate_ok = c_s12.post(f"/api/orders/{s12_order.id}/", data=json.dumps({"status": "preparing"}), content_type="application/json")
assert_test(res_reactivate_ok.status_code == 200, "Supervisor with pos_cancel_order successfully reactivated order (HTTP 200)")
s12_order.refresh_from_db()
assert_test(s12_order.status == "preparing", "Order status correctly moved from cancelled to preparing")

# 5. Customer Directory Isolation & Scoping
from core.models import Customer
Branch.objects.filter(tenant=tenant, name="Branch C2 S12").delete()
Customer.objects.filter(tenant=tenant, phone__in=["0599990001", "0599990002"]).delete()
Order.objects.filter(order_number__in=["ORD-CA-1", "ORD-CB-1"]).delete()
branch_c2 = Branch.objects.create(tenant=tenant, name="Branch C2 S12", status="active")
cust_a = Customer.objects.create(tenant=tenant, name="Customer Branch A", phone="0599990001", address="Zone A")
cust_b = Customer.objects.create(tenant=tenant, name="Customer Branch B", phone="0599990002", address="Zone B")
Order.objects.create(tenant=tenant, branch=branch, customer=cust_a, order_number="ORD-CA-1", subtotal=10, total=10)
Order.objects.create(tenant=tenant, branch=branch_c2, customer=cust_b, order_number="ORD-CB-1", subtotal=10, total=10)

s12_mgr_role.set_permissions(["pos_access", "pos_create_order"])
res_search_branch = c_s12.get("/api/customers/search/?q=059999")
assert_test(res_search_branch.status_code == 200, "Branch cashier can search customers (HTTP 200)")
found_names = [c["name"] for c in res_search_branch.json().get("customers", [])]
assert_test("Customer Branch A" in found_names and "Customer Branch B" not in found_names, "Branch-locked cashier only sees customers with history in their branch")

res_search_owner = c_owner.get("/api/customers/search/?q=059999")
found_names_owner = [c["name"] for c in res_search_owner.json().get("customers", [])]
assert_test("Customer Branch A" in found_names_owner and "Customer Branch B" in found_names_owner, "Owner sees customers across all branches")

# 6. AuditLog Verification
from core.models import AuditLog
logs_count = AuditLog.objects.filter(tenant=tenant).count()
assert_test(logs_count > 0, f"AuditLog successfully recorded sensitive events (Found {logs_count} logs)")

res_audit_owner = c_owner.get("/api/audit-logs/")
assert_test(res_audit_owner.status_code == 200 and len(res_audit_owner.json().get("logs", [])) > 0, "Owner can access api_audit_logs endpoint (HTTP 200)")

res_audit_cashier = c_s12.get("/api/audit-logs/")
assert_test(res_audit_cashier.status_code == 403, "Cashier without system_view_audit_logs blocked from api_audit_logs (HTTP 403)")

cust_a.delete()
cust_b.delete()
branch_c2.delete()
s12_order.delete()
s12_mgr_emp.delete()
s12_mgr_user.delete()
s12_mgr_role.delete()

print("\n======================================================================")
print(f"  VERIFICATION FINISHED: {passed_tests} PASSED, {failed_tests} FAILED")
print("======================================================================")

if failed_tests > 0:
    sys.exit(1)


