# Handoff Report: Restaurant Profile Backend Survey

**Agent**: `explorer_survey_2`  
**Date**: 2026-10-23  
**Working Directory**: `/root/motaem/.agents/teamwork/explorer_survey_2`  
**Recipient**: `edcd0c06-1ae8-42c0-a1b9-d21bcdbc28d7` (orchestrator_1)

---

## 1. Observation

1. **Existing Models**:
   - In `/root/motaem/apps/tenants/models.py:6-90`, the `Tenant` model is defined with `app_label = 'core'`.
   - In `/root/motaem/core/models.py:16-21`, `Tenant` is re-exported via facade:
     ```python
     from apps.tenants.models import (
         Tenant,
         Branch,
         DeliveryArea,
         PlatformConfiguration,
     )
     ```
   - No separate `Restaurant`, `Company`, or `Organization` model exists in the database.

2. **Existing Fields on `Tenant`**:
   - The `Tenant` model in `/root/motaem/apps/tenants/models.py` has:
     - `name`: `models.CharField(max_length=255, verbose_name="اسم المطعم / المنشأة")` (line 25)
     - `slug`: `models.SlugField(max_length=100, unique=True, verbose_name="المعرف اللاتيني (Slug)")` (line 26)
     - `logo_emoji`: `models.CharField(max_length=20, default="🍽️", blank=True, verbose_name="شعار / أيقونة")` (line 27)
     - `logo_image`: `models.FileField(upload_to="tenant_logos/", blank=True, null=True, verbose_name="شعار المطعم (Logo)")` (line 28)
     - `cover_image`: `models.FileField(upload_to="tenant_covers/", blank=True, null=True, verbose_name="صورة الغلاف (Cover)")` (line 29)
     - `brand_color`: `models.CharField(max_length=20, default="#0E382A", blank=True, verbose_name="اللون الأساسي للهوية")` (line 31)
     - `bio`: `models.CharField(max_length=255, default="", blank=True, verbose_name="نبذة عن المطعم")` (line 32)
     - `phone`: `models.CharField(max_length=50, default="", blank=True, verbose_name="رقم الهاتف")` (line 33)
     - `email`: `models.EmailField(blank=True, default="", verbose_name="البريد الإلكتروني")` (line 34)
     - `address`: `models.CharField(max_length=255, default="", blank=True, verbose_name="المقر الرئيسي")` (line 35)
   - Running `venv/bin/python manage.py showmigrations` confirmed all 28 `core` migrations are applied, including `0003_tenant_...` and `0015_menuitem_description_menuitem_image_tenant_bio_and_more.py`.

3. **Media Configuration & Libraries**:
   - In `/root/motaem/restaurant_system/settings.py:214-215`:
     ```python
     MEDIA_URL = '/media/'
     MEDIA_ROOT = BASE_DIR / 'media'
     ```
   - In `/root/motaem/restaurant_system/urls.py:35-37`:
     ```python
     from django.urls import re_path
     from django.views.static import serve

     urlpatterns += [
         re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
     ]
     ```
   - Running `venv/bin/python -c "import PIL"` returned `ModuleNotFoundError: No module named 'PIL'`.
   - Models intentionally use `models.FileField`, avoiding `models.ImageField` because PIL/Pillow is absent from `venv`.

4. **View Patterns and Existing Endpoints**:
   - Views throughout the project are 100% Function-Based Views (FBVs).
   - In `/root/motaem/apps/tenants/views.py:685-735`, `api_update_tenant_branding(request)` updates `name`, `bio`, `brand_color`, `logo_emoji`, `logo_image`, `cover_image`.
   - `api_update_tenant_branding` does NOT update `phone`, `email`, or `address`.
   - Its permission check (`apps/tenants/views.py:696-698`) allows `user_has_perm(request.user, "manage_menu")`:
     ```python
     profile = getattr(request.user, "profile", None)
     is_owner = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))
     if not is_owner and not user_has_perm(request.user, "manage_menu"):
         return JsonResponse({"error": "غير مصرح لك بتعديل هوية المطعم"}, status=403)
     ```
   - Currently, there is NO dedicated page view or URL pattern for the Restaurant Profile (`restaurant_profile`).

5. **Navigation & Verification Baseline**:
   - Top navigation tabs for General Admin reside in `/root/motaem/templates/_admin_nav_tabs.html` (includes Branches, Menu, Inventory, Staff, Subscription).
   - Running `./init.sh` executed `manage.py check`, `test_system.py`, and `test_e2e_rbac.py` with 100% pass rate (zero errors).

---

## 2. Logic Chain

1. From **Observation 1 & 2**, all 8 fields specified in R1 and R2 (`name`, `bio`, `phone`, `email`, `address`, `brand_color`, `logo_image`, `cover_image`) already exist as database columns on `Tenant` in the active SQLite schema. Therefore, **no database migrations or model schema edits are necessary**.
2. From **Observation 3**, `Pillow` is not installed, and the fields are `FileField`. Therefore, **image validation must be handled programmatically in the view/form handler** (validating file extension, MIME type, and max size: e.g. 2MB for logo, 5MB for cover) rather than converting to `models.ImageField`.
3. From **Observation 4**, the existing endpoint `api_update_tenant_branding` is incomplete for R2 (omits `phone`, `email`, `address`) and insecure for R3 (allows branch menu staff via `manage_menu`). Therefore, an updated/dedicated endpoint (`api_update_restaurant_profile` or upgraded `api_update_tenant_branding`) and dedicated page view (`restaurant_profile_view`) are required.
4. From **Observation 4 & 5**, the system uses standard FBVs and a unified navigation component `_admin_nav_tabs.html`. Therefore, adding `restaurant_profile_view` that renders `restaurant_profile.html` (which includes `_admin_nav_tabs.html`) directly matches the existing architecture.
5. From **Observation 4**, to satisfy R3, the permission check must strictly enforce:
   ```python
   is_owner = request.user.is_superuser or (profile and (profile.role in ["owner", "platform_admin"] or profile.is_platform_admin))
   is_hq_manager = (
       is_owner
       or user_has_perm(request.user, "view_hq_dashboard")
       or user_has_perm(request.user, "manage_branches")
       or (profile and profile.job_role and profile.job_role.scope in ["hq", "both"])
       or (emp and emp.job_role and emp.job_role.scope in ["hq", "both"])
   )
   if not is_hq_manager:
       return HttpResponseForbidden("غير مصرح لك بإدارة الملف التعريفي للمطعم")
   ```
   Branch-only staff (Cashier, Chef, Driver, Waiter) will evaluate `is_hq_manager` to `False` and be rejected with HTTP 403 Forbidden.

---

## 3. Caveats

- **Pillow**: The environment deliberately does not include `Pillow`. Image conversion or cropping via PIL is not possible without adding a new external package. Standard browser multipart upload with FileField is the established pattern in this repository.
- **Audit Logging**: While not explicitly mentioned in R1–R3, the system possesses `apps.audit.models.log_audit_event`, which should be called on profile updates to match the security standards of other HQ settings.

---

## 4. Conclusion

The backend data model is completely ready and requires zero database migrations. The implementation for R1, R2, and R3 requires:
1. **View**: Create `restaurant_profile_view` in `apps/tenants/views.py` (and export in `core/views.py`), handling GET (renders `templates/restaurant_profile.html`) and POST updates.
2. **Endpoint**: Support all 8 fields (`name`, `bio`, `phone`, `email`, `address`, `brand_color`, `logo_image`, `cover_image`) with input validation (email validator, hex color check, file size limits: 2MB for logo, 5MB for cover, and extension checks).
3. **Permissions (R3)**: Enforce `@login_required` and verify user is Owner or HQ Manager; return HTTP 403 for branch staff. Enforce tenant isolation via `get_active_tenant(request)`.
4. **Navigation**: Add `"restaurant_profile"` tab to `templates/_admin_nav_tabs.html`, sidebar in `templates/base.html`, and action button in `templates/dashboard.html`.
5. **Testing**: Add test cases to `test_e2e_rbac.py` and/or `test_system.py` verifying 200 for owner/HQ, 403 for cashier/chef/driver, redirect for unauthenticated, and full persistence of all 8 fields.

---

## 5. Verification Method

1. **System Health**:
   ```bash
   ./init.sh
   ```
2. **Model & Migration Integrity**:
   ```bash
   venv/bin/python manage.py check
   venv/bin/python manage.py showmigrations
   ```
3. **Inspect Models & Settings**:
   - Inspect `/root/motaem/apps/tenants/models.py:25-36` to verify fields.
   - Inspect `/root/motaem/restaurant_system/settings.py:214-215` for media root/url.
   - Inspect `/root/motaem/restaurant_system/urls.py:35-37` for media static serve.
4. **Invalidation Condition**:
   - The findings in this report would be invalidated if new fields are required that do not exist on `Tenant`, or if `Pillow` is introduced as a hard requirement.
