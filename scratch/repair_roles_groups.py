import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "restaurant_system.settings")
django.setup()

from django.contrib.auth.models import Group, Permission, User
from core.models import Tenant, JobRole, Employee, UserProfile, ensure_tenant_preset_roles, RESTAURANT_PERMISSIONS

print("=== Starting RBAC Native Migration and Data Repair ===")

# 1. Ensure all 70 permissions exist in auth_permission
print(f"Total defined permissions: {len(RESTAURANT_PERMISSIONS)}")
for codename, name in RESTAURANT_PERMISSIONS:
    p = Permission.objects.filter(codename=codename).first()
    if not p:
        print(f"WARNING: Permission {codename} missing in auth_permission!")

# 2. Iterate all tenants and seed/sync preset roles
for tenant in Tenant.objects.all():
    print(f"\nProcessing Tenant: {tenant.name} (ID: {tenant.id}, Slug: {tenant.slug})")
    ensure_tenant_preset_roles(tenant)

# 3. Synchronize all JobRoles with their Django Groups
print("\n--- Synchronizing all JobRoles with Groups ---")
for role in JobRole.objects.all():
    grp = role.sync_with_django_group()
    perms_count = grp.permissions.count() if grp else 0
    print(f"Role ID {role.id}: '{role.name}' (Tenant {role.tenant_id}) -> Group '{grp.name if grp else None}' with {perms_count} perms")

# 4. Synchronize all Employees with Users and Groups
print("\n--- Synchronizing all Employees with Users and Groups ---")
for emp in Employee.objects.select_related("user", "job_role", "tenant").all():
    if not emp.user and emp.employee_code:
        tenant_slug = emp.tenant.slug if emp.tenant else "sys"
        username = f"emp_{tenant_slug}_{emp.employee_code}"
        user_obj, created = User.objects.get_or_create(username=username, defaults={"first_name": emp.name})
        user_obj.set_password("admin123")
        user_obj.save()
        emp.user = user_obj
        emp.save(update_fields=["user"])
        print(f"Created missing user {username} for Employee {emp.name}")

    if emp.user:
        # Sync is_active
        is_act = (emp.status == "active")
        if emp.user.is_active != is_act:
            emp.user.is_active = is_act
            emp.user.save(update_fields=["is_active"])

        # Sync group
        if emp.job_role and emp.job_role.group:
            emp.user.groups.set([emp.job_role.group])
        elif emp.job_role:
            grp = emp.job_role.sync_with_django_group()
            if grp:
                emp.user.groups.set([grp])
        else:
            emp.user.groups.clear()

        # Sync profile
        UserProfile.objects.update_or_create(
            user=emp.user,
            defaults={
                "tenant": emp.tenant,
                "branch": emp.branch,
                "role": "branch_manager" if emp.role == "manager" else emp.role,
                "job_role": emp.job_role,
            }
        )

        group_names = [g.name for g in emp.user.groups.all()]
        print(f"Emp ID {emp.id} ('{emp.name}', {emp.employee_code}): Status={emp.status}, UserActive={emp.user.is_active}, Groups={group_names}")

print("\n=== RBAC Native Migration and Data Repair Complete ===")
