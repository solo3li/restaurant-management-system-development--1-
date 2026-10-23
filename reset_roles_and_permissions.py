#!/usr/bin/env python
"""
Global RBAC Reset Script:
1. Unassigns all employees from job roles (job_role = None).
2. Unassigns user profiles from job roles (job_role = None).
3. Clears all Django auth Groups assigned to non-superuser users.
4. Clears all permission caches.
5. Deletes all JobRole records across all tenants.
6. Deletes all associated Django auth Groups (t*_role_*).
"""
import os
import sys
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "restaurant_system.settings")
django.setup()

from django.contrib.auth.models import User, Group
from core.models import Tenant, JobRole, Employee, UserProfile

def reset_all_roles():
    print("=" * 60)
    print("STARTING GLOBAL ROLES & PERMISSIONS RESET")
    print("=" * 60)

    # 1. Unassign employees
    emp_count = Employee.objects.filter(job_role__isnull=False).count()
    Employee.objects.all().update(job_role=None)
    print(f"✔ Reset {emp_count} employees to job_role=None")

    # 2. Unassign user profiles
    prof_count = UserProfile.objects.filter(job_role__isnull=False).count()
    UserProfile.objects.all().update(job_role=None)
    print(f"✔ Reset {prof_count} user profiles to job_role=None")

    # 3. Clear user groups and caches for non-superusers
    cleared_users = 0
    for u in User.objects.filter(is_superuser=False):
        u.groups.clear()
        for cache_field in ["_perm_cache", "_group_perm_cache", "_user_perm_cache"]:
            if hasattr(u, cache_field):
                delattr(u, cache_field)
        cleared_users += 1
    print(f"✔ Cleared groups and permission cache for {cleared_users} users")

    # 4. Delete all JobRole records
    role_count = JobRole.objects.count()
    for r in JobRole.objects.all():
        r.delete()
    print(f"✔ Deleted {role_count} JobRole records and their associated Groups")

    # 5. Clean any lingering role groups
    lingering_groups = Group.objects.filter(name__contains="_role_").count()
    Group.objects.filter(name__contains="_role_").delete()
    print(f"✔ Cleaned {lingering_groups} lingering role groups")

    print("=" * 60)
    print("✔ GLOBAL ROLES & PERMISSIONS RESET COMPLETED SUCCESSFULLY!")
    print(f"Current JobRole count in DB: {JobRole.objects.count()}")
    print("=" * 60)

if __name__ == "__main__":
    reset_all_roles()
