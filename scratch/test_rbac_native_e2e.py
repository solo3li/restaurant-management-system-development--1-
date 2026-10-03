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
test_role.set_permissions(["manage_employees", "hr_deactivate_employee"])
res_force_del = client.post(f"/api/employees/{test_emp.id}/delete/", data=json.dumps({"force": True}), content_type="application/json")
assert_test(res_force_del.status_code == 200 and res_force_del.json().get("action") == "archived", "Non-owner passing force=True on employee with order history safely archived instead of hard deleted")

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

print("\n======================================================================")
print(f"  VERIFICATION FINISHED: {passed_tests} PASSED, {failed_tests} FAILED")
print("======================================================================")

if failed_tests > 0:
    sys.exit(1)

