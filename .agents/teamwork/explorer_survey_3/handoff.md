# Handoff Report: RBAC, Multi-Tenant Isolation & Test Infrastructure Survey

**Author**: `explorer_survey_3`  
**Working Directory**: `/root/motaem/.agents/teamwork/explorer_survey_3`  
**Handoff Type**: Hard (Task Complete)  
**Date**: 2026-10-23  

---

## 1. Observation

1. **Active Tenant Resolution & Middleware**:
   - `core/middleware.py:11-55` (`TenantMiddleware.__call__`) resolves `request.tenant` per request.
   - For authenticated users (`core/middleware.py:31-54`):
     - Platform admin: checks `request.session.get("active_tenant_id")`, then `profile.tenant`, then first active tenant.
     - Regular tenant users: strictly hard-bound to `profile.tenant` (line 48) or `emp.tenant` (line 52). Regular users cannot switch tenant via session.
   - Suspended tenants (`core/middleware.py:57-91`): redirects owner to `owner_subscription` or non-owner to `/login/?suspended=1` with 403 on API requests.
   - Helper function `get_active_tenant(request)` in `apps/tenants/helpers.py:5-28` provides fallback hierarchy matching middleware resolution.

2. **RBAC Architecture & Native Django Permissions**:
   - Model `Tenant` in `apps/tenants/models.py:25-35` already defines:
     `name`, `slug`, `logo_emoji`, `logo_image`, `cover_image`, `custom_domain`, `brand_color`, `bio`, `phone`, `email`, `address`.
   - `apps/accounts/models.py:7-65` registers 40 distinct permissions in `RESTAURANT_PERMISSIONS` under app label `core`.
   - `apps/accounts/models.py:162-176` defines `BRANCH_PERMISSIONS` and `HQ_PERMISSIONS` sets.
   - `JobRole` model (`apps/accounts/models.py:182-280`) syncs 1:1 with Django `Group` named `t{tenant_id}_role_{role_id}` (`sync_with_django_group`, lines 247-268).
   - Unified permission check `user_has_perm(user, perm_key)` in `apps/accounts/helpers.py:42-130`:
     - Line 55: `if profile and (profile.is_platform_admin or profile.role in ["owner", "platform_admin"]): return True`.
     - Lines 108-112: verifies `user.has_perm(f"core.{k}")` and `user.groups.filter(permissions__codename=k).exists()`.
     - Lines 61-94: resolves symmetric synonyms (`manage_branches` <-> `branch_manage_branches`, `view_hq_dashboard` <-> `hq_view_master_dashboard`, etc.).

3. **HTTP 403 Enforcement Patterns**:
   - In HTML views:
     - `core/views.py:243-249`: `dashboard_view` returns `HttpResponseForbidden("غير مصرح لك بالوصول إلى لوحة الإدارة العامة")` for non-HQ users.
     - `apps/tenants/views.py:178-179`: `branches_view` returns `HttpResponseForbidden("غير مصرح لك بالوصول لإدارة الفروع")`.
     - `apps/accounts/views.py:329-334`: `employees_view` returns `HttpResponseForbidden("غير مصرح لك باستعراض أو إدارة الموظفين")`.
   - In JSON API endpoints:
     - `apps/tenants/views.py:247-248`: `api_create_branch` returns `JsonResponse({"error": "غير مصرح لك بإنشاء فروع جديدة"}, status=403)`.
     - `apps/tenants/views.py:696-698`: `api_update_tenant_branding` checks:
       `if not is_owner and not user_has_perm(request.user, "manage_menu"): return JsonResponse({"error": "غير مصرح لك بتعديل هوية المطعم"}, status=403)`.

4. **Existing Test Suites & Baseline Verification**:
   - Verification command `./init.sh` executes:
     - `venv/bin/python manage.py check`: exited 0 with "System check identified no issues (0 silenced)".
     - `venv/bin/python test_system.py`: exited 0 with 8 tests passed ("ALL VERIFICATION TESTS PASSED SUCCESSFULLY! 100% WORKING.").
     - `venv/bin/python test_e2e_rbac.py`: exited 0 with 7 test sections passed ("ALL END-TO-END RBAC & PERMISSION TESTS PASSED PERFECTLY! (100%)").
   - Total runtime of `./init.sh`: ~10 seconds.
   - `feature_list.json` contains 5 placeholder items (`feat-001` through `feat-005`), all in `not-started` status.

5. **Navigation & UI Assets**:
   - `templates/_admin_nav_tabs.html` provides 5 admin tabs: branches (`branches`), menu (`branch_menu`), inventory (`inventory`), staff (`employees`), subscription (`owner_subscription`).
   - `templates/base.html:724-735` renders the General Admin sidebar link for users with `is_owner` or admin permissions.

---

## 2. Logic Chain

1. **Tenant Isolation Proof**:
   - Observation 1 demonstrates that regular users have `request.tenant` resolved exclusively from their linked `profile.tenant` or `employee_profile.tenant`. Session-based tenant switching is prevented unless `is_platform_admin` is True.
   - Any database lookup in views that filters by `tenant=get_active_tenant(request)` is therefore impossible for a regular tenant user to escape or pollute with cross-tenant data.
   - Modifying a tenant's profile via `get_active_tenant(request)` guarantees zero possibility of cross-tenant tampering.

2. **RBAC Scope Distinction & Flaw in Existing Branding Endpoint**:
   - Observation 2 & 3 show that `is_owner` bypasses all permission checks, while branch staff (Cashier, Kitchen Chef, Delivery Driver) have branch-scoped roles and do not have HQ permissions.
   - Observation 3 shows `api_update_tenant_branding` in `apps/tenants/views.py:697` allows anyone with `manage_menu`. In a multi-branch chain, a branch employee assigned to manage branch menu items could inappropriately modify the entire chain's brand name, logo, and cover.
   - To satisfy Requirement R3 of `ORIGINAL_REQUEST.md`, profile updates must be gated strictly to `is_owner` or users with HQ management authority (`view_hq_dashboard` / `manage_branches`), and branch staff (`cashier`, `chef`, `driver`) must receive HTTP 403 Forbidden.

3. **Schema Readiness**:
   - Observation 2 demonstrates that the `Tenant` model in `apps/tenants/models.py:25-35` already includes all required fields (`name`, `bio`, `phone`, `email`, `address`, `brand_color`, `logo_image`, `cover_image`).
   - Therefore, implementing the Restaurant Profile feature requires no schema migrations or database alterations, eliminating migration risk.

4. **Test Infrastructure Extensibility**:
   - Observation 4 confirms `./init.sh` is fast, reliable, and exits 0 cleanly.
   - The test patterns demonstrated in `test_e2e_rbac.py` (RequestFactory/Client, role creation, group sync, HTTP status assertions, JSON error verification, cross-tenant isolation checks, and DB cleanup) provide the exact blueprint for validating the Restaurant Profile feature.

---

## 3. Caveats

- **Media Storage Backend**: Media files (`logo_image`, `cover_image`) are saved to local filesystem `MEDIA_ROOT`. In automated tests, mock/dummy files should use `SimpleUploadedFile` and temporary test files should be removed from disk or overwritten safely.
- **Color Validation**: `Tenant.brand_color` is a `CharField(max_length=20)` without a regex validator at the model level; color format validation (e.g., `#RRGGBB`) must be enforced at the form/view layer.
- **Preset Roles Deprecation**: As verified in `test_e2e_rbac.py:85`, preset roles are deprecated in favor of dynamically synced `JobRole` instances. Tests must continue to create custom test roles or use `UserProfile(role="owner")` rather than relying on legacy preset roles.

---

## 4. Conclusion

1. **Multi-tenant isolation** is solid, enforced at the middleware layer via `request.tenant` and queried systematically through `get_active_tenant(request)`. Cross-tenant modification is prevented as long as handlers fetch tenant instances via `get_active_tenant(request)`.
2. **RBAC and 403 enforcement** follow strict native Django auth conventions (`user_has_perm`, `User.has_perm`, `auth_group`).
3. For the **Restaurant Profile feature**:
   - A dedicated HQ view (`restaurant_profile_view`) and template (`restaurant_profile.html`) must be introduced.
   - A navigation link must be added to `templates/_admin_nav_tabs.html` and `templates/base.html`.
   - The backend handler must handle all fields: `name`, `bio`, `phone`, `email`, `address`, `brand_color`, `logo_image`, `cover_image`.
   - Strict RBAC: only `is_owner` or HQ Manager permitted; branch staff (`cashier`, `chef`, `driver`, `branch_manager`) must receive HTTP 403 Forbidden.
   - Input validation must validate required fields (`name`), email format, and hex color syntax.
4. Existing test harness (`./init.sh`) is 100% operational and healthy.

---

## 5. Verification Method

To independently verify all findings and test infrastructure:

1. **Execute full verification baseline**:
   ```bash
   ./init.sh
   ```
   *Expected outcome*: Exits with code 0; Django check passes with 0 issues; all tests in `test_system.py` pass; all tests in `test_e2e_rbac.py` pass (100%).

2. **Verify Tenant model fields**:
   ```bash
   venv/bin/python manage.py shell -c "from core.models import Tenant; [print(f.name, f.get_internal_type()) for f in Tenant._meta.fields if f.name in ['name', 'bio', 'phone', 'email', 'address', 'brand_color', 'logo_image', 'cover_image']]"
   ```
   *Expected outcome*: Prints all 8 field names and types confirming schema presence.

3. **Verify RBAC permission registry**:
   ```bash
   venv/bin/python manage.py shell -c "from apps.accounts.models import RESTAURANT_PERMISSIONS; print('Permissions count:', len(RESTAURANT_PERMISSIONS))"
   ```
   *Expected outcome*: Prints `Permissions count: 40`.

4. **Inspect key survey documents**:
   - Analysis: `/root/motaem/.agents/teamwork/explorer_survey_3/analysis.md`
   - Handoff: `/root/motaem/.agents/teamwork/explorer_survey_3/handoff.md`
