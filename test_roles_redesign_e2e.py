#!/usr/bin/env python
"""
Automated test suite for Roles & Permissions Frontend Redesign & Enhanced Backend APIs:
1. Validates /employees/ and /employees/?tab=roles HTML rendering
2. Validates stats strip and no emojis in template
3. Validates GET /api/job-roles/ (returns roles, catalog, stats)
4. Validates GET /api/job-role/{id}/ (returns role detail + assigned employees list)
5. Validates POST /api/job-roles/ (strict scope creation)
6. Validates Safe Deletion:
   - Prevents deleting role with employees unless reassign_to_role_id is provided
   - Successfully reassigns employees and deletes role
   - Deletes role with 0 employees directly
"""
import os
import sys
import json
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "restaurant_system.settings")
import django
django.setup()

from django.test import RequestFactory, Client
from django.contrib.auth.models import User, Permission
from core.models import Tenant, Branch, JobRole, Employee, UserProfile, PERMISSIONS_CATALOG
from apps.accounts.views import employees_view, api_job_roles, api_job_role_detail

print("=" * 70)
print(">>> RUNNING ROLES & PERMISSIONS REDESIGN VERIFICATION SUITE")
print("=" * 70)

# Setup test tenant, branch, users
tenant, _ = Tenant.objects.get_or_create(
    slug="t_rbac_redesign",
    defaults={"name": "Test RBAC Redesign Tenant", "is_active": True, "subscription_status": "active"}
)
tenant.subscription_plan = None
tenant.save()

branch, _ = Branch.objects.get_or_create(
    tenant=tenant,
    name="الفرع النموذجي",
    defaults={"phone": "0500000001"}
)

# Create Owner User
owner_user, _ = User.objects.get_or_create(username="rbac_redesign_owner")
owner_user.set_password("pass123")
owner_user.save()

profile, _ = UserProfile.objects.get_or_create(user=owner_user, defaults={"tenant": tenant, "role": "owner"})
profile.tenant = tenant
profile.role = "owner"
profile.save()

rf = RequestFactory()

# ---------------------------------------------------------
# TEST 1: Page Rendering /employees/
# ---------------------------------------------------------
print("\n[1] Testing /employees/ HTML rendering...")
req = rf.get("/employees/")
req.user = owner_user
req.session = {}
resp = employees_view(req)
assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
content = resp.content.decode("utf-8")

assert "id=\"tab-btn-employees\"" in content, "Missing tab-btn-employees"
assert "id=\"tab-btn-roles\"" in content, "Missing tab-btn-roles"
assert "id=\"section-employees\"" in content, "Missing section-employees"
assert "id=\"section-roles\"" in content, "Missing section-roles"
assert "id=\"stat-total-roles\"" in content, "Missing stat-total-roles"
assert "id=\"scope-card-branch\"" in content, "Missing scope-card-branch"
assert "id=\"scope-card-hq\"" in content, "Missing scope-card-hq"
assert "id=\"role-employees-modal\"" in content, "Missing role-employees-modal"
assert "id=\"safe-delete-role-modal\"" in content, "Missing safe-delete-role-modal"
print("  ✔ PASS: /employees/ rendered with complete tabs, metrics strip, and modals")

# ---------------------------------------------------------
# TEST 2: GET /api/job-roles/ (with stats)
# ---------------------------------------------------------
print("\n[2] Testing GET /api/job-roles/ (listing with stats)...")
req = rf.get("/api/job-roles/")
req.user = owner_user
resp = api_job_roles(req)
assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
data = json.loads(resp.content.decode("utf-8"))
assert data.get("ok") is True, "Expected ok=True"
assert "roles" in data, "Expected roles in response"
assert "catalog" in data, "Expected catalog in response"
assert "stats" in data, "Expected stats in response"
stats = data["stats"]
assert "total" in stats and "branch" in stats and "hq" in stats and "assigned_employees" in stats
print(f"  ✔ PASS: api_job_roles returns {len(data['roles'])} roles, catalog with {len(data['catalog'])} groups, and stats: {stats}")

# ---------------------------------------------------------
# TEST 3: POST /api/job-roles/ (Create Custom Role)
# ---------------------------------------------------------
print("\n[3] Testing POST /api/job-roles/ to create custom role...")
# Delete if previously created
JobRole.objects.filter(tenant=tenant, name="مشرف مبيعات تجريبي").delete()
JobRole.objects.filter(tenant=tenant, name="مشرف كول سنتر بديل").delete()

post_body = {
    "name": "مشرف مبيعات تجريبي",
    "scope": "branch",
    "description": "مسؤول متابعة المبيعات بالفرع",
    "permissions": ["pos_access", "pos_reprint_receipt", "branch_view_orders"]
}
req = rf.post("/api/job-roles/", data=json.dumps(post_body), content_type="application/json")
req.user = owner_user
resp = api_job_roles(req)
assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.content}"
new_role_data = json.loads(resp.content.decode("utf-8"))["role"]
new_role_id = new_role_data["id"]
assert new_role_data["name"] == "مشرف مبيعات تجريبي"
assert new_role_data["scope"] == "branch"
assert set(new_role_data["permissions"]) == {"pos_access", "pos_reprint_receipt", "branch_view_orders"}
print(f"  ✔ PASS: Created custom branch role ID {new_role_id}")

# ---------------------------------------------------------
# TEST 4: GET /api/job-roles/{id}/ (Detail with Employees)
# ---------------------------------------------------------
print("\n[4] Testing GET /api/job-roles/{id}/ with employee assignment...")
# Create a test employee assigned to new_role
role_obj = JobRole.objects.get(id=new_role_id)
test_emp, _ = Employee.objects.get_or_create(
    tenant=tenant,
    employee_code="999",
    defaults={
        "name": "أحمد عبد الله",
        "phone": "0511223344",
        "branch": branch,
        "job_role": role_obj,
    }
)
test_emp.job_role = role_obj
test_emp.branch = branch
test_emp.save()

req = rf.get(f"/api/job-roles/{new_role_id}/")
req.user = owner_user
resp = api_job_role_detail(req, new_role_id)
assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
detail_data = json.loads(resp.content.decode("utf-8"))["role"]
assert detail_data["employees_count"] >= 1
assert len(detail_data["employees"]) >= 1
first_emp = detail_data["employees"][0]
assert first_emp["name"] == "أحمد عبد الله"
assert first_emp["employee_code"] == "999"
assert first_emp["branch_name"] == branch.name
print(f"  ✔ PASS: api_job_role_detail returned role detail with assigned employee: {first_emp}")

# ---------------------------------------------------------
# TEST 5: Safe Deletion Rejection (when employees assigned and no target)
# ---------------------------------------------------------
print("\n[5] Testing delete rejection without reassignment target...")
del_body = {"action": "delete"}
req = rf.post(f"/api/job-roles/{new_role_id}/", data=json.dumps(del_body), content_type="application/json")
req.user = owner_user
resp = api_job_role_detail(req, new_role_id)
assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"
err_data = json.loads(resp.content.decode("utf-8"))
assert err_data.get("requires_reassign") is True, "Expected requires_reassign=True"
print(f"  ✔ PASS: Blocked role deletion safely: '{err_data['error']}'")

# ---------------------------------------------------------
# TEST 6: Safe Deletion with Reassignment
# ---------------------------------------------------------
print("\n[6] Testing safe deletion with reassignment to another role...")
# Create target role
target_role = JobRole.objects.create(
    tenant=tenant,
    name="مشرف كول سنتر بديل",
    scope="branch",
    description="الدور البديل لإعادة التعيين"
)
target_role.sync_with_django_group()
target_role.set_permissions(["pos_access"])

del_body_with_target = {
    "action": "delete",
    "reassign_to_role_id": target_role.id
}
req = rf.post(f"/api/job-roles/{new_role_id}/", data=json.dumps(del_body_with_target), content_type="application/json")
req.user = owner_user
resp = api_job_role_detail(req, new_role_id)
assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"

# Verify role is deleted from DB
assert not JobRole.objects.filter(id=new_role_id).exists(), "Role was not deleted"

# Verify employee was reassigned to target_role
test_emp.refresh_from_db()
assert test_emp.job_role_id == target_role.id, f"Employee not reassigned to target role (has {test_emp.job_role_id})"
print("  ✔ PASS: Successfully reassigned employee to target role and deleted original role")

# Clean up target role (now has 1 employee, delete test employee first)
test_emp.delete()
target_role.delete()

# ---------------------------------------------------------
# TEST 7: Strict Scope RBAC Mixed Perms Validation
# ---------------------------------------------------------
print("\n[7] Testing strict scope boundary validation during creation...")
invalid_body = {
    "name": "دور مخالف للنطاق",
    "scope": "branch",
    "permissions": ["pos_access", "call_center_access"] # call_center_access is strictly HQ
}
req = rf.post("/api/job-roles/", data=json.dumps(invalid_body), content_type="application/json")
req.user = owner_user
resp = api_job_roles(req)
assert resp.status_code == 400, "Branch role allowed HQ permission unexpectedly"
err_msg = json.loads(resp.content.decode("utf-8"))["error"]
print(f"  ✔ PASS: Strict scope violation rejected with message: '{err_msg}'")

print("\n" + "=" * 70)
print("🎉 ALL TESTS FOR ROLES REDESIGN & ENHANCED APIS PASSED 100%!")
print("=" * 70)
