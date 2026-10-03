#!/usr/bin/env python3
"""
End-to-End Test Suite for Multi-Tenant RBAC & Native Django Permissions System.
Tests all roles, native permissions (User.has_perm / auth_permission / Group),
strict 403 enforcement, login redirects, and multi-tenant isolation.
"""
import os
import sys
import json
from decimal import Decimal

# Setup Django Environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "restaurant_system.settings")
import django
django.setup()

from django.contrib.auth.models import User, Group, Permission
from django.test import Client
from django.utils import timezone
from core.models import (
    Tenant, Branch, JobRole, Employee, UserProfile, Order,
    RESTAURANT_PERMISSIONS, PERMISSIONS_CATALOG, PRESET_ROLES_CONFIG,
    ensure_tenant_preset_roles
)
from core.views import user_has_perm, get_post_login_redirect

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

def print_header(title):
    print(f"\n{CYAN}{BOLD}{'='*70}{RESET}")
    print(f"{CYAN}{BOLD}>>> {title}{RESET}")
    print(f"{CYAN}{BOLD}{'='*70}{RESET}")

def assert_true(condition, test_name):
    if condition:
        print(f"  {GREEN}✔ PASS:{RESET} {test_name}")
    else:
        print(f"  {RED}✘ FAIL:{RESET} {test_name}")
        raise AssertionError(f"Test failed: {test_name}")

def assert_equal(actual, expected, test_name):
    if actual == expected:
        print(f"  {GREEN}✔ PASS:{RESET} {test_name} ({actual} == {expected})")
    else:
        print(f"  {RED}✘ FAIL:{RESET} {test_name} (Got: {actual}, Expected: {expected})")
        raise AssertionError(f"Expected {expected}, got {actual} in {test_name}")


def run_e2e_tests():
    print(f"{BOLD}Starting E2E RBAC & Permissions Verification...{RESET}")

    # -------------------------------------------------------------
    # 1. Verify Django Native Permissions in auth_permission table
    # -------------------------------------------------------------
    print_header("1. Native Django Permissions Table (auth_permission)")
    all_codenames = [p[0] for p in RESTAURANT_PERMISSIONS]
    db_perms = set(Permission.objects.filter(content_type__app_label="core").values_list("codename", flat=True))
    
    missing_perms = [p for p in all_codenames if p not in db_perms]
    assert_equal(len(missing_perms), 0, f"All {len(all_codenames)} permissions registered in auth_permission")
    print(f"     Total core permissions verified in DB: {len(db_perms)}")

    # -------------------------------------------------------------
    # 2. Verify Preset Roles & Group Synchronization for Tenant
    # -------------------------------------------------------------
    print_header("2. Preset Roles & Django Group (auth_group) Synchronization")
    tenant = Tenant.objects.first()
    if not tenant:
        tenant = Tenant.objects.create(name="E2E Test Tenant", slug="e2e_tenant", is_active=True)
    
    branch = Branch.objects.filter(tenant=tenant).first()
    if not branch:
        branch = Branch.objects.create(tenant=tenant, name="الفرع الرئيسي E2E", status="active")

    preset_roles = ensure_tenant_preset_roles(tenant)
    assert_equal(len(preset_roles), 8, "Tenant has exactly 8 preset roles")

    # Check ordering and Group sync
    for idx, role in enumerate(preset_roles):
        expected_ordering = (idx + 1) * 10
        assert_equal(role.ordering, expected_ordering, f"Role '{role.name}' ordering is {expected_ordering}")
        assert_true(role.group is not None, f"Role '{role.name}' has linked Django Group")
        assert_equal(role.group.name, f"t{tenant.id}_role_{role.id}", f"Group name follows t{tenant.id}_role_{role.id} pattern")
        
        # Check permissions attached to Django Group
        group_perms = set(role.group.permissions.values_list("codename", flat=True))
        role_perms = set(role.get_permissions_list())
        assert_equal(group_perms, role_perms, f"Group permissions match JobRole permissions for '{role.name}'")

    # -------------------------------------------------------------
    # 3. User & Group Integration via Django Native Auth
    # -------------------------------------------------------------
    print_header("3. User-Group Integration & User.has_perm / user_has_perm")
    floor_cashier_role = JobRole.objects.get(tenant=tenant, name="كاشير صالة")
    senior_cashier_role = JobRole.objects.get(tenant=tenant, name="كاشير رئيسي")
    kitchen_chef_role = JobRole.objects.get(tenant=tenant, name="طاهٍ رئيسي / مطبخ")
    delivery_driver_role = JobRole.objects.get(tenant=tenant, name="سائق توصيل")
    call_center_role = JobRole.objects.get(tenant=tenant, name="موظف كول سنتر")
    branch_manager_role = JobRole.objects.get(tenant=tenant, name="مدير فرع")
    hq_manager_role = JobRole.objects.get(tenant=tenant, name="مدير عام / إدارة عليا")

    # Create Test Floor Cashier User
    cashier_user, _ = User.objects.get_or_create(username="test_e2e_floor_cashier", defaults={"first_name": "كاشير تجريبي"})
    cashier_user.set_password("password123")
    cashier_user.save()
    cashier_user.groups.set([floor_cashier_role.group])

    cashier_profile, _ = UserProfile.objects.update_or_create(
        user=cashier_user,
        defaults={"tenant": tenant, "branch": branch, "job_role": floor_cashier_role, "role": "cashier"}
    )
    cashier_emp, _ = Employee.objects.update_or_create(
        tenant=tenant, employee_code="9901",
        defaults={"name": "كاشير تجريبي", "user": cashier_user, "job_role": floor_cashier_role, "branch": branch, "role": "cashier"}
    )
    cashier_emp.set_pin("4321")
    cashier_emp.save()

    # Re-fetch user to refresh cached permissions
    cashier_user = User.objects.get(id=cashier_user.id)

    # Native Django Permission check
    assert_true(cashier_user.has_perm("core.pos_access"), "Native User.has_perm('core.pos_access') is True")
    assert_true(cashier_user.has_perm("core.pos_create_order"), "Native User.has_perm('core.pos_create_order') is True")
    assert_equal(cashier_user.has_perm("core.pos_cancel_order"), False, "Native User.has_perm('core.pos_cancel_order') is False (Floor Cashier cannot cancel)")
    assert_equal(cashier_user.has_perm("core.kds_access"), False, "Native User.has_perm('core.kds_access') is False")

    # Unified user_has_perm check
    assert_true(user_has_perm(cashier_user, "pos_access"), "user_has_perm('pos_access') is True")
    assert_equal(user_has_perm(cashier_user, "pos_cancel_order"), False, "user_has_perm('pos_cancel_order') is False")

    # -------------------------------------------------------------
    # 4. Login Redirect Routing Verification
    # -------------------------------------------------------------
    print_header("4. Post-Login Redirect Routing for All 7 Key Roles")
    
    # Floor Cashier -> POS
    assert_equal(get_post_login_redirect(cashier_user), "pos", "Floor Cashier redirects to 'pos'")

    # Senior Cashier -> POS
    senior_user, _ = User.objects.get_or_create(username="test_e2e_senior_cashier")
    senior_user.groups.set([senior_cashier_role.group])
    UserProfile.objects.update_or_create(user=senior_user, defaults={"tenant": tenant, "branch": branch, "job_role": senior_cashier_role, "role": "cashier"})
    senior_user = User.objects.get(id=senior_user.id)
    assert_equal(get_post_login_redirect(senior_user), "pos", "Senior Cashier redirects to 'pos'")
    assert_true(senior_user.has_perm("core.pos_cancel_order"), "Senior Cashier has 'pos_cancel_order'")

    # Kitchen Chef -> Kitchen
    chef_user, _ = User.objects.get_or_create(username="test_e2e_chef")
    chef_user.groups.set([kitchen_chef_role.group])
    UserProfile.objects.update_or_create(user=chef_user, defaults={"tenant": tenant, "branch": branch, "job_role": kitchen_chef_role, "role": "chef"})
    chef_user = User.objects.get(id=chef_user.id)
    assert_equal(get_post_login_redirect(chef_user), "kitchen", "Kitchen Chef redirects to 'kitchen'")

    # Delivery Driver -> Delivery
    driver_user, _ = User.objects.get_or_create(username="test_e2e_driver")
    driver_user.groups.set([delivery_driver_role.group])
    UserProfile.objects.update_or_create(user=driver_user, defaults={"tenant": tenant, "branch": branch, "job_role": delivery_driver_role, "role": "driver"})
    driver_user = User.objects.get(id=driver_user.id)
    assert_equal(get_post_login_redirect(driver_user), "delivery", "Delivery Driver redirects to 'delivery'")

    # Call Center Agent -> Call Center
    cc_user, _ = User.objects.get_or_create(username="test_e2e_call_center")
    cc_user.groups.set([call_center_role.group])
    UserProfile.objects.update_or_create(user=cc_user, defaults={"tenant": tenant, "job_role": call_center_role, "role": "call_center"})
    cc_user = User.objects.get(id=cc_user.id)
    assert_equal(get_post_login_redirect(cc_user), "call_center", "Call Center Agent redirects to 'call_center'")

    # Branch Manager -> Branch Dashboard
    bm_user, _ = User.objects.get_or_create(username="test_e2e_branch_mgr")
    bm_user.groups.set([branch_manager_role.group])
    UserProfile.objects.update_or_create(user=bm_user, defaults={"tenant": tenant, "branch": branch, "job_role": branch_manager_role, "role": "branch_manager"})
    bm_user = User.objects.get(id=bm_user.id)
    assert_equal(get_post_login_redirect(bm_user), "branch_dashboard", "Branch Manager redirects to 'branch_dashboard'")

    # HQ General Manager -> HQ Dashboard
    hq_user, _ = User.objects.get_or_create(username="test_e2e_hq_mgr")
    hq_user.groups.set([hq_manager_role.group])
    UserProfile.objects.update_or_create(user=hq_user, defaults={"tenant": tenant, "job_role": hq_manager_role, "role": "branch_manager"})
    hq_user = User.objects.get(id=hq_user.id)
    assert_equal(get_post_login_redirect(hq_user), "dashboard", "HQ General Manager redirects to 'dashboard'")

    # -------------------------------------------------------------
    # 5. HTTP Client End-to-End Tests & Strict 403 Denial
    # -------------------------------------------------------------
    print_header("5. HTTP End-to-End Permission Enforcement & Strict 403 Denial")
    client = Client()

    import time
    unique_tag = str(int(time.time()))
    Order.objects.filter(order_number__startswith="E2E-").delete()
    Order.objects.filter(order_number__startswith="B-").delete()

    # Create a test order in this branch
    test_order = Order.objects.create(
        tenant=tenant,
        branch=branch,
        order_number=f"E2E-{unique_tag}",
        order_type="dine_in",
        status="new",
        subtotal=Decimal("150.00"),
        total=Decimal("150.00"),
    )

    # (A) Floor Cashier testing
    print(f"\n{YELLOW}Testing Floor Cashier (Should have POS, but STRICTLY BLOCKED from Cancel/KDS/Employees):{RESET}")
    client.force_login(cashier_user)
    session = client.session
    session["active_branch_id"] = branch.id
    session.save()

    # Access POS -> 200 OK
    res = client.get("/pos/")
    assert_equal(res.status_code, 200, "Floor Cashier accesses /pos/ (200 OK)")

    # Access KDS Kitchen -> 403 Forbidden
    res = client.get("/kitchen/")
    assert_equal(res.status_code, 403, "Floor Cashier blocked from /kitchen/ (403 Forbidden)")

    # Access Call Center -> 403 Forbidden
    res = client.get("/call-center/")
    assert_equal(res.status_code, 403, "Floor Cashier blocked from /call-center/ (403 Forbidden)")

    # Access Employees Management -> 403 Forbidden
    res = client.get("/employees/")
    assert_equal(res.status_code, 403, "Floor Cashier blocked from /employees/ (403 Forbidden)")

    # Attempt to cancel order without permission -> 403 Forbidden
    res = client.post(f"/api/orders/{test_order.id}/cancel/")
    assert_equal(res.status_code, 403, "Floor Cashier blocked from cancelling order (403 Forbidden)")
    resp_json = json.loads(res.content.decode("utf-8"))
    assert_true("غير مصرح لك" in resp_json.get("error", ""), "403 response contains clear Arabic rejection message")

    # Attempt to delete order -> 403 Forbidden
    res = client.post(f"/api/orders/{test_order.id}/delete/")
    assert_equal(res.status_code, 403, "Floor Cashier blocked from deleting order (403 Forbidden)")

    # Verify order is still 'new'
    test_order.refresh_from_db()
    assert_equal(test_order.status, "new", "Order remains 'new' after unauthorized cancel attempt")

    # (B) Senior Cashier testing (Has pos_cancel_order)
    print(f"\n{YELLOW}Testing Senior Cashier (Has pos_cancel_order, Can Cancel but NOT Delete):{RESET}")
    client.force_login(senior_user)
    session = client.session
    session["active_branch_id"] = branch.id
    session.save()

    # Cancel order -> 200 OK
    res = client.post(f"/api/orders/{test_order.id}/cancel/")
    assert_equal(res.status_code, 200, "Senior Cashier cancels order (200 OK)")
    test_order.refresh_from_db()
    assert_equal(test_order.status, "cancelled", "Order status updated to 'cancelled'")

    # Delete order -> still 403 Forbidden (Strict separation: cancel != delete)
    res = client.post(f"/api/orders/{test_order.id}/delete/")
    assert_equal(res.status_code, 403, "Senior Cashier cannot delete order permanently (403 Forbidden)")

    # (C) Kitchen Chef testing
    print(f"\n{YELLOW}Testing Kitchen Chef (Access KDS, Blocked from POS):{RESET}")
    client.force_login(chef_user)
    res = client.get("/kitchen/")
    assert_equal(res.status_code, 200, "Kitchen Chef accesses /kitchen/ (200 OK)")
    res = client.get("/pos/")
    assert_equal(res.status_code, 403, "Kitchen Chef blocked from /pos/ (403 Forbidden)")

    # (D) Delivery Driver testing
    print(f"\n{YELLOW}Testing Delivery Driver (Access Delivery, Blocked from POS):{RESET}")
    client.force_login(driver_user)
    res = client.get("/delivery/")
    assert_equal(res.status_code, 200, "Delivery Driver accesses /delivery/ (200 OK)")
    res = client.get("/pos/")
    assert_equal(res.status_code, 403, "Delivery Driver blocked from /pos/ (403 Forbidden)")

    # (E) Call Center testing
    print(f"\n{YELLOW}Testing Call Center Agent (Access Call Center, Blocked from Kitchen):{RESET}")
    client.force_login(cc_user)
    res = client.get("/call-center/")
    # If tenant has call_center in subscription plan, 200, otherwise 403 with plan message
    if tenant.has_feature("call_center"):
        assert_equal(res.status_code, 200, "Call Center Agent accesses /call-center/ (200 OK)")
    res = client.get("/kitchen/")
    assert_equal(res.status_code, 403, "Call Center Agent blocked from /kitchen/ (403 Forbidden)")

    # (F) Branch Manager Employee Creation & Role Sync
    print(f"\n{YELLOW}Testing Branch Manager (Employees Management & Role Assignment):{RESET}")
    client.force_login(bm_user)
    res = client.get("/employees/")
    assert_equal(res.status_code, 200, "Branch Manager accesses /employees/ (200 OK)")

    # Create new employee via API
    new_emp_payload = {
        "name": "محاسب تجريبي E2E",
        "phone": "0559988776",
        "job_role_id": str(floor_cashier_role.id),
        "branchId": str(branch.id),
        "salary": 6500,
        "employeeCode": "9902",
        "pin": "5566"
    }
    res = client.post(
        "/api/employees/create/",
        data=json.dumps(new_emp_payload),
        content_type="application/json"
    )
    assert_equal(res.status_code, 200, "Employee created via /api/employees/create/ (200 OK)")
    created_id = json.loads(res.content.decode("utf-8")).get("id")
    created_emp = Employee.objects.get(id=created_id)
    assert_equal(created_emp.job_role.id, floor_cashier_role.id, "Created employee assigned chosen JobRole")
    assert_true(created_emp.user is not None, "Created employee auto-linked to Django User")
    assert_true(floor_cashier_role.group in created_emp.user.groups.all(), "Created employee Django User synced to JobRole Group")

    # Update created employee to Senior Cashier
    update_payload = {
        "job_role_id": str(senior_cashier_role.id)
    }
    res = client.post(
        f"/api/employees/update/{created_id}/",
        data=json.dumps(update_payload),
        content_type="application/json"
    )
    assert_equal(res.status_code, 200, "Employee role updated to Senior Cashier (200 OK)")
    created_emp.refresh_from_db()
    assert_equal(created_emp.job_role.id, senior_cashier_role.id, "Employee job_role updated")
    assert_true(senior_cashier_role.group in created_emp.user.groups.all(), "Employee user.groups updated to Senior Cashier Group")
    assert_true(floor_cashier_role.group not in created_emp.user.groups.all(), "Old Floor Cashier group removed")

    # -------------------------------------------------------------
    # 6. Multi-Tenant Isolation Verification
    # -------------------------------------------------------------
    print_header("6. Multi-Tenant Isolation Verification")
    tenant_b = Tenant.objects.exclude(id=tenant.id).first()
    if not tenant_b:
        tenant_b = Tenant.objects.create(name="Tenant B Isolation Test", slug="tenant_b_iso", is_active=True)
    
    branch_b = Branch.objects.filter(tenant=tenant_b).first()
    if not branch_b:
        branch_b = Branch.objects.create(tenant=tenant_b, name="فرع المستأجر ب", status="active")

    order_b = Order.objects.create(
        tenant=tenant_b,
        branch=branch_b,
        order_number=f"B-{unique_tag}",
        order_type="dine_in",
        status="new",
        subtotal=Decimal("80.00"),
        total=Decimal("80.00"),
    )

    # Manager of Tenant A tries to cancel order of Tenant B
    client.force_login(bm_user)
    res = client.post(f"/api/orders/{order_b.id}/cancel/")
    assert_true(res.status_code in [403, 404], f"Cross-tenant order cancel strictly rejected (HTTP {res.status_code})")

    # Clean up test records
    print_header("7. Cleanup of Test Records")
    test_order.delete()
    order_b.delete()
    created_emp.user.delete()
    created_emp.delete()
    cashier_emp.delete()
    cashier_user.delete()
    senior_user.delete()
    chef_user.delete()
    driver_user.delete()
    cc_user.delete()
    bm_user.delete()
    hq_user.delete()
    print("  All temporary test records safely purged from DB.")

    print(f"\n{GREEN}{BOLD}{'='*70}{RESET}")
    print(f"{GREEN}{BOLD}🎉 ALL END-TO-END RBAC & PERMISSION TESTS PASSED PERFECTLY! (100%){RESET}")
    print(f"{GREEN}{BOLD}{'='*70}{RESET}\n")

if __name__ == "__main__":
    try:
        run_e2e_tests()
    except Exception as e:
        print(f"\n{RED}{BOLD}TEST SUITE ENCOUNTERED AN ERROR:{RESET} {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
